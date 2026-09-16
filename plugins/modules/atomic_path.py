#!/usr/bin/python
# Copyright: (c) 2026 Lightning IT
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
# ruff: noqa: E402
"""Descriptor-relative directory creation and atomic regular-file replacement."""

DOCUMENTATION = r"""
---
module: atomic_path
version_added: "3.3.0"
short_description: Mutate one path below an identity-bound parent chain
description:
  - Creates one directory or atomically replaces one regular file.
  - Binds every mutation to descriptor-opened, no-follow parent identities.
  - Requires exclusive trust in the effective UID; hostile concurrent processes
    with that same UID are outside the isolation boundary.
  - The exact target parent must be owned by the effective UID and must not be
    writable by its group or by other users.
  - Every canonical parent component, including the exact target parent, must
    have a matching device and inode entry in C(parent_identities).
requirements:
  - Python and operating-system support for descriptor-relative C(dir_fd) APIs,
    C(O_DIRECTORY), C(O_NOFOLLOW), and C(O_NONBLOCK).
  - C(renameat2) on Linux or C(renameatx_np) on macOS.
  - A descriptor path facility at C(/proc/self/fd) or C(/dev/fd).
options:
  path:
    description: Canonical absolute target path.
    type: path
    required: true
  state:
    description: Target type to create or replace.
    type: str
    choices: [directory, file]
    required: true
  content:
    description: UTF-8 content required for C(state=file).
    type: str
  mode:
    description: Exact octal permissions required on the target.
    type: str
    required: true
  owner:
    description: Exact owner name or numeric UID required on the target.
    type: str
    required: true
  group:
    description: Exact group name or numeric GID required on the target.
    type: str
    required: true
  parent_identities:
    description: Canonical parent paths mapped to their device and inode identities.
    type: dict
    required: true
  expected_checksum:
    description: Existing lowercase SHA-256 checksum required for replacement.
    type: str
  allow_absent:
    description: Permit creation when a file target does not yet exist.
    type: bool
    default: false
author:
  - Lightning IT (@lightning-it)
"""

EXAMPLES = r"""
- name: Replace one exact role-owned file
  lit.supplementary.atomic_path:
    path: /etc/lit/forward-proxy/squid.conf
    state: file
    content: "http_access deny all\n"
    mode: "0644"
    owner: root
    group: root
    expected_checksum: 9070ed193a574a857cc619cfbfee6c89bfe03d9af481e62f6c85f9ee0a3fb09c
    parent_identities:
      /etc/lit/forward-proxy:
        device: 2049
        inode: 123456
"""

RETURN = r"""
path:
  description: Canonical target path.
  type: str
  returned: always
checksum:
  description: SHA-256 checksum of the requested file content.
  type: str
  returned: for file state
recovery_path:
  description: Preserved workspace or entry location whenever private cleanup is uncertain.
  type: str
  returned: on failure with preserved recovery state
"""

import ctypes
import errno
import fcntl
import grp
import hashlib
import os
import pwd
import re
import secrets
import stat
from typing import Optional, Tuple

from ansible.module_utils.basic import AnsibleModule


def _identity(value: str, database: object, attribute: str) -> int:
    if re.fullmatch(r"[+-]?\d+", value):
        identity = int(value, 10)
        if identity < 0 or identity >= 2**32 - 1:
            raise ValueError("owner and group IDs must fit a non-negative 32-bit identity")
        return identity
    record = database(value)
    identity = int(getattr(record, attribute))
    if identity < 0 or identity >= 2**32 - 1:
        raise ValueError("owner and group IDs must fit a non-negative 32-bit identity")
    return identity


def _strict_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{label} must be a non-negative integer")
    if isinstance(value, str) and not re.fullmatch(r"\d+", value):
        raise ValueError(f"{label} must be a non-negative integer")
    result = int(value)
    if result < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return result


def _open_bound_directory(path: str, identities: dict) -> int:
    current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    walked = ""
    try:
        if path == "/":
            if path not in identities or not isinstance(identities[path], dict):
                raise OSError("exact parent identity is missing or malformed: /")
            expected = identities[path]
            try:
                identity = (
                    _strict_integer(expected["device"], "device"),
                    _strict_integer(expected["inode"], "inode"),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise OSError("parent identity is malformed: /") from exc
            opened = os.fstat(current)
            if (opened.st_dev, opened.st_ino) != identity:
                raise OSError("parent identity changed: /")
            return current
        for component in path[1:].split("/"):
            if not component:
                continue
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            previous = current
            current = -1
            try:
                os.close(previous)
            except OSError:
                try:
                    os.close(following)
                except OSError:
                    pass
                raise
            current = following
            walked += "/" + component
            if walked not in identities:
                continue
            expected = identities[walked]
            if not isinstance(expected, dict):
                raise OSError(f"parent identity is malformed: {walked}")
            opened = os.fstat(current)
            try:
                identity = (
                    _strict_integer(expected["device"], "device"),
                    _strict_integer(expected["inode"], "inode"),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise OSError(f"parent identity is malformed: {walked}") from exc
            if (opened.st_dev, opened.st_ino) != identity:
                raise OSError(f"parent identity changed: {walked}")
        if path not in identities:
            raise OSError(f"exact parent identity is missing: {path}")
        return current
    except Exception:
        if current >= 0:
            try:
                os.close(current)
            except OSError:
                pass
        raise


def _checksum(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _matches(details: os.stat_result, mode: int, uid: int, gid: int) -> bool:
    return stat.S_IMODE(details.st_mode) == mode and details.st_uid == uid and details.st_gid == gid


IDENTITY_FIELDS = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_uid",
    "st_gid",
    "st_size",
    "st_mtime_ns",
)


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return all(getattr(left, field) == getattr(right, field) for field in IDENTITY_FIELDS)


def _same_snapshot(left: os.stat_result, right: os.stat_result) -> bool:
    return _same_identity(left, right) and left.st_ctime_ns == right.st_ctime_ns


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_directory_identity(left: os.stat_result, right: os.stat_result) -> bool:
    """Compare directory identity and managed metadata, not mutable contents."""
    return (
        _same_inode(left, right)
        and stat.S_ISDIR(left.st_mode)
        and stat.S_ISDIR(right.st_mode)
        and stat.S_IMODE(left.st_mode) == stat.S_IMODE(right.st_mode)
        and left.st_uid == right.st_uid
        and left.st_gid == right.st_gid
    )


def _same_entry_snapshot(left: Optional[os.stat_result], right: Optional[os.stat_result]) -> bool:
    if left is None or right is None:
        return left is right
    if stat.S_ISDIR(left.st_mode) or stat.S_ISDIR(right.st_mode):
        return _same_directory_identity(left, right)
    return _same_snapshot(left, right)


def _renameat(source_fd: int, source: str, target_fd: int, target: str, operation: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    source_name = os.fsencode(source)
    target_name = os.fsencode(target)
    if hasattr(library, "renameat2"):
        function = library.renameat2
        flag = 1 if operation == "noreplace" else 2
    elif hasattr(library, "renameatx_np"):
        function = library.renameatx_np
        flag = 4 if operation == "noreplace" else 2
    else:
        raise OSError(errno.ENOSYS, "kernel-conditional rename is unavailable")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(source_fd, source_name, target_fd, target_name, flag) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def _require_capabilities() -> None:
    flags = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    functions = (os.open, os.stat, os.mkdir, os.rename, os.unlink, os.rmdir)
    if any(
        not isinstance(getattr(os, flag, None), int)
        or isinstance(getattr(os, flag, None), bool)
        or getattr(os, flag) == 0
        for flag in flags
    ) or any(
        function not in getattr(os, "supports_dir_fd", ()) for function in functions
    ):
        raise OSError("descriptor-relative no-follow filesystem operations are unavailable")
    if os.stat not in getattr(os, "supports_follow_symlinks", ()):
        raise OSError("no-follow stat is unavailable")
    library = ctypes.CDLL(None, use_errno=True)
    if not (hasattr(library, "renameat2") or hasattr(library, "renameatx_np")):
        raise OSError("kernel-conditional rename is unavailable")
    probe = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _descriptor_path(probe)
    finally:
        os.close(probe)


def _descriptor_path(descriptor: int) -> str:
    proc_path = f"/proc/self/fd/{descriptor}"
    try:
        resolved = os.readlink(proc_path)
    except OSError:
        resolved = fcntl.fcntl(descriptor, 50, b"\0" * 1024).split(b"\0", 1)[0].decode()
    if not os.path.isabs(resolved) or resolved.endswith(" (deleted)"):
        raise OSError("descriptor path cannot be reported for recovery")
    return resolved


def _private_workspace(parent: int) -> Tuple[int, str, os.stat_result]:
    for _attempt in range(10):
        name = f".atomic-path-{os.getpid()}-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            continue
        try:
            expected = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except OSError as exc:
            raise _PreservedWorkspace(os.path.join(_descriptor_path(parent), name)) from exc
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        except OSError as exc:
            if not _remove_private_if_same(parent, name, expected, directory=True):
                raise _PreservedWorkspace(os.path.join(_descriptor_path(parent), name)) from exc
            raise
        try:
            opened = os.fstat(descriptor)
        except OSError as exc:
            try:
                os.close(descriptor)
            except OSError as close_exc:
                raise _PreservedWorkspace(os.path.join(_descriptor_path(parent), name)) from close_exc
            if not _remove_private_if_same(parent, name, expected, directory=True):
                raise _PreservedWorkspace(os.path.join(_descriptor_path(parent), name)) from exc
            raise
        if opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) != 0o700:
            try:
                os.close(descriptor)
            except OSError as exc:
                raise _PreservedWorkspace(os.path.join(_descriptor_path(parent), name)) from exc
            if not _remove_private_if_same(parent, name, expected, directory=True):
                raise _PreservedWorkspace(os.path.join(_descriptor_path(parent), name))
            raise OSError("private workspace ownership or mode changed")
        if not _same_inode(expected, opened):
            try:
                os.close(descriptor)
            except OSError as exc:
                raise _PreservedWorkspace(os.path.join(_descriptor_path(parent), name)) from exc
            if not _remove_private_if_same(parent, name, expected, directory=True):
                raise _PreservedWorkspace(os.path.join(_descriptor_path(parent), name))
            raise OSError("private workspace identity changed while opening")
        return descriptor, name, opened
    raise OSError("cannot allocate a private atomic-path workspace")


def _remove_private_if_same(parent: int, name: str, expected: os.stat_result, *, directory: bool = False) -> bool:
    """Clean an entry below a locked exclusive parent or private workspace."""
    try:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if not (_same_inode(current, expected) if directory else _same_identity(current, expected)):
        return False
    try:
        if directory:
            os.rmdir(name, dir_fd=parent)
        else:
            os.unlink(name, dir_fd=parent)
    except OSError:
        return False
    return True


class _PreservedRecovery(OSError):
    """Signal that an entry remains in the private workspace."""

    def __init__(self, entry: str) -> None:
        super().__init__(f"recovery entry preserved as {entry}")
        self.entry = entry


class _PreservedWorkspace(OSError):
    """Signal that a private workspace could not be safely removed."""

    def __init__(self, path: str) -> None:
        super().__init__(f"private workspace preserved as {path}")
        self.path = path


def _capture_and_remove(
    parent: int,
    name: str,
    expected: os.stat_result,
    workspace: int,
    capture: str,
    *,
    directory: bool = False,
    checksum: Optional[str] = None,
) -> bool:
    """Move a public entry atomically before identity-bound private cleanup."""
    try:
        _renameat(parent, name, workspace, capture, "noreplace")
    except FileNotFoundError:
        return True
    try:
        captured = os.stat(capture, dir_fd=workspace, follow_symlinks=False)
    except OSError as exc:
        raise _PreservedRecovery(capture) from exc
    matches = (
        _same_directory_identity(captured, expected)
        if directory
        else checksum is not None
        and _same_identity(captured, expected)
        and _verified_file(workspace, capture, captured, checksum)
    )
    if matches:
        return _remove_private_if_same(workspace, capture, captured, directory=directory)
    # Never restore a workspace pathname after its one-time verification. A
    # same-UID process could replace it between verification and rename. Keep
    # the uncertain entry private and require explicit operator recovery.
    raise _PreservedRecovery(capture)


def _verified_file(parent: int, name: str, expected: os.stat_result, checksum: str) -> bool:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    except OSError:
        return False
    try:
        opened = os.fstat(descriptor)
        if not _same_identity(opened, expected) or _checksum(descriptor) != checksum:
            return False
        return _same_snapshot(opened, os.fstat(descriptor))
    finally:
        os.close(descriptor)


def _verified_descriptor(descriptor: int, expected: os.stat_result, checksum: str) -> bool:
    """Verify a file through an already-open readable descriptor."""
    opened = os.fstat(descriptor)
    if not _same_snapshot(opened, expected) or _checksum(descriptor) != checksum:
        return False
    return _same_snapshot(opened, os.fstat(descriptor))


def _existing(parent: int, name: str) -> Optional[os.stat_result]:
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _require_exclusive_parent(parent: int) -> None:
    details = os.fstat(parent)
    if details.st_uid != os.geteuid() or stat.S_IMODE(details.st_mode) & 0o022:
        raise OSError("mutation parent must be owned by the effective user and not group/world writable")
    try:
        fcntl.flock(parent, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise OSError("another atomic path transaction holds the mutation parent") from exc


def _fsync_directory(parent: int) -> None:
    """Persist a committed directory entry when the filesystem supports it."""
    try:
        os.fsync(parent)
    except OSError as exc:
        unsupported = {errno.EINVAL, errno.ENOTSUP}
        if hasattr(errno, "EOPNOTSUPP"):
            unsupported.add(errno.EOPNOTSUPP)
        if exc.errno not in unsupported:
            raise


def _revalidated_entry(module: AnsibleModule, parent: int, name: str) -> Optional[os.stat_result]:
    """Read the target between two independently bound canonical-parent opens."""
    parent_path = os.path.dirname(module.params["path"])
    original = os.fstat(parent)
    first = _open_bound_directory(parent_path, module.params["parent_identities"])
    try:
        if not _same_inode(original, os.fstat(first)):
            raise OSError("parent identity changed across mutation")
        observed = _existing(first, name)
    finally:
        os.close(first)
    second = _open_bound_directory(parent_path, module.params["parent_identities"])
    try:
        if not _same_inode(original, os.fstat(second)):
            raise OSError("parent identity changed across mutation")
        confirmed = _existing(second, name)
        if not _same_entry_snapshot(observed, confirmed):
            raise OSError("target changed across canonical revalidation")
        return confirmed
    finally:
        os.close(second)


def _create_directory(module: AnsibleModule, parent: int, name: str, mode: int, uid: int, gid: int) -> None:
    _require_exclusive_parent(parent)
    before = _existing(parent, name)
    if before is not None:
        if not stat.S_ISDIR(before.st_mode) or not _matches(before, mode, uid, gid):
            module.fail_json(
                msg="directory boundary has an unexpected identity or metadata", path=module.params["path"]
            )
        current = _revalidated_entry(module, parent, name)
        if current is None or not _same_directory_identity(current, before):
            module.fail_json(msg="directory boundary changed before no-op completion", path=module.params["path"])
        module.exit_json(changed=False, path=module.params["path"])
    if module.check_mode:
        module.exit_json(changed=True, path=module.params["path"])
    workspace, workspace_name, workspace_identity = _private_workspace(parent)
    directory = -1
    created_identity: Optional[os.stat_result] = None
    installed = False
    private_entry: Optional[str] = None
    preserve_workspace = False
    recovery_name: Optional[str] = None
    cleanup_failed = False
    failure: Optional[Exception] = None
    try:
        os.mkdir("payload", 0o700, dir_fd=workspace)
        private_entry = "payload"
        created_identity = os.stat("payload", dir_fd=workspace, follow_symlinks=False)
        directory = os.open("payload", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=workspace)
        if not _same_inode(created_identity, os.fstat(directory)):
            raise OSError("private directory payload identity changed while opening")
        os.fchown(directory, uid, gid)
        os.fchmod(directory, mode)
        created_identity = os.fstat(directory)
        if not _matches(created_identity, mode, uid, gid):
            raise OSError("created directory metadata could not be bound")
        _renameat(workspace, "payload", parent, name, "noreplace")
        installed = True
        private_entry = None
        if not _same_directory_identity(created_identity, os.stat(name, dir_fd=parent, follow_symlinks=False)):
            raise OSError("created directory identity changed while installing")
        _fsync_directory(parent)
        final = _existing(parent, name)
        if final is None or not _same_directory_identity(final, created_identity):
            raise OSError("created directory identity changed before completion")
        canonical = _revalidated_entry(module, parent, name)
        if canonical is None or not _same_directory_identity(canonical, final):
            raise OSError("created directory identity changed at the canonical boundary")
    except Exception as exc:
        failure = exc
        if installed and created_identity is not None:
            try:
                removed = _capture_and_remove(
                    parent, name, created_identity, workspace, "failed", directory=True
                )
                installed = False
                if not removed:
                    preserve_workspace = True
                    private_entry = "failed"
                    recovery_name = private_entry
            except _PreservedRecovery as recovery:
                installed = False
                preserve_workspace = True
                private_entry = recovery.entry
                recovery_name = private_entry
    finally:
        cleanup_exception: Optional[Exception] = None
        if directory >= 0:
            try:
                os.close(directory)
            except OSError as exc:
                cleanup_exception = exc
                preserve_workspace = True
                if not installed and private_entry is not None:
                    recovery_name = private_entry
        if (
            cleanup_exception is None
            and not installed
            and private_entry == "payload"
            and created_identity is not None
        ):
            if not _remove_private_if_same(workspace, "payload", created_identity, directory=True):
                preserve_workspace = True
                recovery_name = "payload"
            else:
                private_entry = None
        try:
            os.close(workspace)
        except OSError as exc:
            cleanup_exception = cleanup_exception or exc
            preserve_workspace = True
        if failure is None and cleanup_exception is not None:
            failure = cleanup_exception
        if not preserve_workspace:
            cleanup_failed = not _remove_private_if_same(
                parent, workspace_name, workspace_identity, directory=True
            )
    if failure is not None:
        if preserve_workspace or cleanup_failed:
            recovery_root = os.path.join(_descriptor_path(parent), workspace_name)
            module.fail_json(
                msg=f"atomic directory mutation failed: {failure}; recovery workspace preserved",
                path=module.params["path"],
                recovery_path=os.path.join(recovery_root, recovery_name) if recovery_name else recovery_root,
            )
        raise failure
    if cleanup_failed:
        recovery_root = os.path.join(_descriptor_path(parent), workspace_name)
        module.fail_json(
            msg="created directory but private workspace cleanup failed",
            path=module.params["path"],
            recovery_path=recovery_root,
        )
    module.exit_json(changed=True, path=module.params["path"])


def _write_file(module: AnsibleModule, parent: int, name: str, mode: int, uid: int, gid: int) -> None:
    _require_exclusive_parent(parent)
    content = module.params.get("content")
    if not isinstance(content, str):
        module.fail_json(msg="content is required for file state", path=module.params["path"])
    payload = content.encode("utf-8")
    desired = hashlib.sha256(payload).hexdigest()
    before = _existing(parent, name)
    expected_checksum = module.params.get("expected_checksum")
    if expected_checksum is not None and (
        not isinstance(expected_checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_checksum)
    ):
        module.fail_json(msg="expected_checksum must be one lowercase SHA-256 digest", path=module.params["path"])
    if before is None:
        if not module.params["allow_absent"]:
            module.fail_json(msg="file boundary is absent", path=module.params["path"])
    else:
        if not stat.S_ISREG(before.st_mode) or not _matches(before, mode, uid, gid):
            module.fail_json(msg="file boundary has unexpected type or metadata", path=module.params["path"])
        if expected_checksum is None:
            module.fail_json(msg="expected_checksum is required for an existing file", path=module.params["path"])
        bound = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            opened = os.fstat(bound)
            if not _same_snapshot(opened, before):
                module.fail_json(msg="file boundary changed while opening", path=module.params["path"])
            if _checksum(bound) != expected_checksum:
                module.fail_json(msg="file boundary checksum changed", path=module.params["path"])
            final_bound = os.fstat(bound)
            if not _same_snapshot(opened, final_bound):
                module.fail_json(msg="file boundary changed while checksumming", path=module.params["path"])
            before = final_bound
        finally:
            os.close(bound)
    if before is not None and expected_checksum == desired:
        current = _revalidated_entry(module, parent, name)
        if current is None or not _same_snapshot(current, before):
            module.fail_json(msg="file boundary changed before no-op completion", path=module.params["path"])
        module.exit_json(changed=False, path=module.params["path"], checksum=desired)
    if module.check_mode:
        module.exit_json(changed=True, path=module.params["path"], checksum=desired)
    workspace, workspace_name, workspace_identity = _private_workspace(parent)
    descriptor = -1
    staged_identity: Optional[os.stat_result] = None
    displaced_identity: Optional[os.stat_result] = None
    installed = False
    preserve_workspace = False
    recovery_name: Optional[str] = None
    cleanup_failed = False
    failure: Optional[Exception] = None
    try:
        descriptor = os.open(
            "payload",
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=workspace,
        )
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, mode)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("atomic file write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        staged_identity = os.fstat(descriptor)
        if not _matches(staged_identity, mode, uid, gid):
            raise OSError("temporary file metadata could not be bound")
        if before is None:
            _renameat(workspace, "payload", parent, name, "noreplace")
            installed = True
        else:
            _renameat(workspace, "payload", parent, name, "exchange")
            installed = True
            preserve_workspace = True
            recovery_name = "payload"
            displaced_identity = os.stat("payload", dir_fd=workspace, follow_symlinks=False)
            if not _verified_file(workspace, "payload", before, expected_checksum):
                raise OSError("file boundary changed during replacement; both entries were preserved")
        installed_details = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            staged_identity is None
            or not _same_identity(installed_details, staged_identity)
            or not _verified_descriptor(descriptor, installed_details, desired)
        ):
            preserve_workspace = displaced_identity is not None
            recovery_name = "payload" if preserve_workspace else None
            raise OSError("installed file identity changed after replacement")
        _fsync_directory(parent)
        final = _existing(parent, name)
        if staged_identity is None or final is None or not _same_snapshot(final, installed_details):
            preserve_workspace = displaced_identity is not None
            recovery_name = "payload" if preserve_workspace else None
            raise OSError("installed file identity changed before completion")
        canonical = _revalidated_entry(module, parent, name)
        if canonical is None or not _same_snapshot(canonical, final):
            preserve_workspace = displaced_identity is not None
            raise OSError("installed file identity changed at the canonical boundary")
        if displaced_identity is not None and not _remove_private_if_same(workspace, "payload", displaced_identity):
            preserve_workspace = True
            recovery_name = "payload"
            raise OSError("replaced file could not be removed from the private recovery workspace")
        preserve_workspace = False
        recovery_name = None
    except Exception as exc:
        failure = exc
        if installed and staged_identity is not None:
            if displaced_identity is None:
                try:
                    installed = not _capture_and_remove(
                        parent,
                        name,
                        staged_identity,
                        workspace,
                        "failed",
                        checksum=desired,
                    )
                except _PreservedRecovery as recovery:
                    preserve_workspace = True
                    recovery_name = recovery.entry
            else:
                preserve_workspace = True
                recovery_name = "payload"
    finally:
        cleanup_identity: Optional[os.stat_result] = None
        cleanup_exception: Optional[Exception] = None
        if descriptor >= 0:
            try:
                if not installed:
                    cleanup_identity = os.fstat(descriptor)
            except OSError as exc:
                cleanup_exception = exc
                preserve_workspace = True
                recovery_name = "payload"
            finally:
                try:
                    os.close(descriptor)
                except OSError as exc:
                    cleanup_exception = cleanup_exception or exc
                    preserve_workspace = True
                    if not installed:
                        recovery_name = "payload"
        if not installed and cleanup_identity is not None:
            if not _remove_private_if_same(workspace, "payload", cleanup_identity):
                preserve_workspace = True
                recovery_name = "payload"
        try:
            os.close(workspace)
        except OSError as exc:
            cleanup_exception = cleanup_exception or exc
            preserve_workspace = True
        if failure is None and cleanup_exception is not None:
            failure = cleanup_exception
        if not preserve_workspace:
            cleanup_failed = not _remove_private_if_same(
                parent, workspace_name, workspace_identity, directory=True
            )
    if failure is not None:
        if preserve_workspace or cleanup_failed:
            recovery_root = os.path.join(_descriptor_path(parent), workspace_name)
            module.fail_json(
                msg=f"atomic path mutation failed: {failure}; recovery workspace preserved",
                path=module.params["path"],
                recovery_path=os.path.join(recovery_root, recovery_name) if recovery_name else recovery_root,
            )
        raise failure
    if cleanup_failed:
        recovery_root = os.path.join(_descriptor_path(parent), workspace_name)
        module.fail_json(
            msg="file mutation completed but private workspace cleanup failed",
            path=module.params["path"],
            recovery_path=recovery_root,
        )
    module.exit_json(changed=True, path=module.params["path"], checksum=desired)


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "path": {"type": "path", "required": True},
            "state": {"type": "str", "choices": ["directory", "file"], "required": True},
            "content": {"type": "str", "no_log": True},
            "mode": {"type": "str", "required": True},
            "owner": {"type": "str", "required": True},
            "group": {"type": "str", "required": True},
            "parent_identities": {"type": "dict", "required": True},
            "expected_checksum": {"type": "str"},
            "allow_absent": {"type": "bool", "default": False},
        },
        supports_check_mode=True,
    )
    path = module.params["path"]
    if (
        not os.path.isabs(path)
        or path.startswith("//")
        or os.path.normpath(path) != path
        or not os.path.basename(path)
        or path == "/"
        or "\x00" in path
    ):
        module.fail_json(msg="path must be one canonical absolute path", path=path)
    try:
        _require_capabilities()
        mode_value = str(module.params["mode"])
        if not re.fullmatch(r"[0-7]{3,4}", mode_value):
            raise ValueError("mode must contain three or four octal permission digits")
        mode = int(mode_value, 8)
        if mode > 0o7777:
            raise ValueError("mode exceeds the POSIX permission-bit range")
        uid = _identity(str(module.params["owner"]), pwd.getpwnam, "pw_uid")
        gid = _identity(str(module.params["group"]), grp.getgrnam, "gr_gid")
        parent_path, name = os.path.split(path)
        parent = _open_bound_directory(parent_path, module.params["parent_identities"])
        try:
            if module.params["state"] == "directory":
                _create_directory(module, parent, name, mode, uid, gid)
            _write_file(module, parent, name, mode, uid, gid)
        finally:
            try:
                os.close(parent)
            except OSError:
                # The helper has already selected the Ansible result and,
                # where needed, its bound recovery path. A close outcome must
                # not replace that transaction result.
                pass
    except _PreservedWorkspace as exc:
        module.fail_json(msg=f"atomic path mutation failed: {exc}", path=path, recovery_path=exc.path)
    except (KeyError, OSError, OverflowError, TypeError, ValueError) as exc:
        module.fail_json(msg=f"atomic path mutation failed: {exc}", path=path)


if __name__ == "__main__":
    main()
