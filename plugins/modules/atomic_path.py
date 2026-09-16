#!/usr/bin/python
"""Descriptor-relative directory creation and atomic regular-file replacement."""

from __future__ import annotations

import ctypes
import errno
import grp
import hashlib
import os
import pwd
import re
import secrets
import stat

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r"""
---
module: atomic_path
short_description: Mutate one path below an identity-bound parent chain
options:
  path: {type: path, required: true}
  state: {type: str, choices: [directory, file], required: true}
  content: {type: str, no_log: true}
  mode: {type: str, required: true}
  owner: {type: str, required: true}
  group: {type: str, required: true}
  parent_identities: {type: dict, required: true}
  expected_checksum: {type: str}
  allow_absent: {type: bool, default: false}
author: [Lightning IT]
"""


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
            identity = (
                _strict_integer(expected["device"], "device"),
                _strict_integer(expected["inode"], "inode"),
            )
            opened = os.fstat(current)
            if (opened.st_dev, opened.st_ino) != identity:
                raise OSError("parent identity changed: /")
            return current
        for component in path[1:].split("/"):
            if not component:
                continue
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
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
        os.close(current)
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
    if any(not hasattr(os, flag) for flag in flags) or any(
        function not in getattr(os, "supports_dir_fd", ()) for function in functions
    ):
        raise OSError("descriptor-relative no-follow filesystem operations are unavailable")
    if os.stat not in getattr(os, "supports_follow_symlinks", ()):
        raise OSError("no-follow stat is unavailable")
    library = ctypes.CDLL(None, use_errno=True)
    if not (hasattr(library, "renameat2") or hasattr(library, "renameatx_np")):
        raise OSError("kernel-conditional rename is unavailable")


def _private_workspace(parent: int) -> tuple[int, str, os.stat_result]:
    for _attempt in range(10):
        name = f".atomic-path-{os.getpid()}-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
        except FileExistsError:
            continue
        try:
            expected = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except OSError:
            try:
                os.rmdir(name, dir_fd=parent)
            except OSError:
                pass
            raise
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        except OSError:
            _remove_private_if_same(parent, name, expected, directory=True)
            raise
        opened = os.fstat(descriptor)
        if not _same_inode(expected, opened):
            os.close(descriptor)
            _remove_private_if_same(parent, name, expected, directory=True)
            raise OSError("private workspace identity changed while opening")
        return descriptor, name, opened
    raise OSError("cannot allocate a private atomic-path workspace")


def _remove_private_if_same(parent: int, name: str, expected: os.stat_result, *, directory: bool = False) -> bool:
    """Best-effort cleanup inside a random private 0700 workspace."""
    try:
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return True
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


def _capture_and_remove(
    parent: int,
    name: str,
    expected: os.stat_result,
    workspace: int,
    capture: str,
    *,
    directory: bool = False,
) -> bool:
    """Move a public entry atomically before identity-bound private cleanup."""
    try:
        _renameat(parent, name, workspace, capture, "noreplace")
    except FileNotFoundError:
        return True
    captured = os.stat(capture, dir_fd=workspace, follow_symlinks=False)
    matches = _same_inode(captured, expected) if directory else _same_identity(captured, expected)
    if matches:
        return _remove_private_if_same(workspace, capture, captured, directory=directory)
    try:
        _renameat(workspace, capture, parent, name, "noreplace")
    except OSError:
        pass
    return False


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


def _existing(parent: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _revalidate_parent(module: AnsibleModule, parent: int) -> None:
    parent_path = os.path.dirname(module.params["path"])
    reopened = _open_bound_directory(parent_path, module.params["parent_identities"])
    try:
        original = os.fstat(parent)
        current = os.fstat(reopened)
        if (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino):
            raise OSError("parent identity changed across mutation")
    finally:
        os.close(reopened)


def _create_directory(module: AnsibleModule, parent: int, name: str, mode: int, uid: int, gid: int) -> None:
    before = _existing(parent, name)
    if before is not None:
        if not stat.S_ISDIR(before.st_mode) or not _matches(before, mode, uid, gid):
            module.fail_json(
                msg="directory boundary has an unexpected identity or metadata", path=module.params["path"]
            )
        _revalidate_parent(module, parent)
        current = _existing(parent, name)
        if current is None or not _same_snapshot(current, before):
            module.fail_json(msg="directory boundary changed before no-op completion", path=module.params["path"])
        module.exit_json(changed=False, path=module.params["path"])
    if module.check_mode:
        module.exit_json(changed=True, path=module.params["path"])
    workspace, workspace_name, workspace_identity = _private_workspace(parent)
    directory = -1
    created_identity: os.stat_result | None = None
    installed = False
    try:
        os.mkdir("payload", 0o700, dir_fd=workspace)
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
        if not _same_identity(created_identity, os.stat(name, dir_fd=parent, follow_symlinks=False)):
            raise OSError("created directory identity changed while installing")
        os.fsync(parent)
        _revalidate_parent(module, parent)
        final = _existing(parent, name)
        if final is None or not _same_identity(final, created_identity):
            raise OSError("created directory identity changed before completion")
    except Exception:
        if installed and created_identity is not None:
            _capture_and_remove(parent, name, created_identity, workspace, "failed", directory=True)
        raise
    finally:
        if directory >= 0:
            os.close(directory)
        if not installed and created_identity is not None:
            _remove_private_if_same(workspace, "payload", created_identity, directory=True)
        os.close(workspace)
        _remove_private_if_same(parent, workspace_name, workspace_identity, directory=True)
    module.exit_json(changed=True, path=module.params["path"])


def _write_file(module: AnsibleModule, parent: int, name: str, mode: int, uid: int, gid: int) -> None:
    content = module.params.get("content")
    if not isinstance(content, str):
        module.fail_json(msg="content is required for file state", path=module.params["path"])
    payload = content.encode("utf-8")
    desired = hashlib.sha256(payload).hexdigest()
    before = _existing(parent, name)
    expected_checksum = module.params.get("expected_checksum")
    if before is None:
        if not module.params["allow_absent"]:
            module.fail_json(msg="file boundary is absent", path=module.params["path"])
    else:
        if not stat.S_ISREG(before.st_mode) or not _matches(before, mode, uid, gid):
            module.fail_json(msg="file boundary has unexpected type or metadata", path=module.params["path"])
        if not isinstance(expected_checksum, str):
            module.fail_json(msg="expected_checksum is required for an existing file", path=module.params["path"])
        if not re.fullmatch(r"[0-9a-f]{64}", expected_checksum):
            module.fail_json(msg="expected_checksum must be one lowercase SHA-256 digest", path=module.params["path"])
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
        _revalidate_parent(module, parent)
        current = _existing(parent, name)
        if current is None or not _same_snapshot(current, before):
            module.fail_json(msg="file boundary changed before no-op completion", path=module.params["path"])
        module.exit_json(changed=False, path=module.params["path"], checksum=desired)
    if module.check_mode:
        module.exit_json(changed=True, path=module.params["path"], checksum=desired)
    workspace, workspace_name, workspace_identity = _private_workspace(parent)
    descriptor = -1
    staged_identity: os.stat_result | None = None
    displaced_identity: os.stat_result | None = None
    installed = False
    preserve_workspace = False
    try:
        descriptor = os.open(
            "payload",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
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
            displaced_identity = os.stat("payload", dir_fd=workspace, follow_symlinks=False)
            if not _verified_file(workspace, "payload", before, expected_checksum):
                preserve_workspace = True
                raise OSError(
                    f"file boundary changed during replacement; entries preserved at "
                    f"{os.path.dirname(module.params['path'])}/{workspace_name}"
                )
        installed_details = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if staged_identity is None or not _same_identity(installed_details, staged_identity):
            preserve_workspace = True
            raise OSError("installed file identity changed after replacement")
        os.fsync(parent)
        _revalidate_parent(module, parent)
        final = _existing(parent, name)
        if staged_identity is None or final is None or not _same_identity(final, staged_identity):
            preserve_workspace = displaced_identity is not None
            raise OSError("installed file identity changed before completion")
        if displaced_identity is not None and not _remove_private_if_same(workspace, "payload", displaced_identity):
            raise OSError("replaced file could not be removed from the private recovery workspace")
    except Exception as exc:
        if installed and staged_identity is not None:
            if displaced_identity is None:
                installed = not _capture_and_remove(parent, name, staged_identity, workspace, "failed")
            else:
                preserve_workspace = True
        if preserve_workspace:
            module.fail_json(
                msg=f"atomic path mutation failed: {exc}; recovery workspace preserved",
                path=module.params["path"],
                recovery_path=f"{os.path.dirname(module.params['path'])}/{workspace_name}/payload",
            )
        raise
    finally:
        cleanup_identity = os.fstat(descriptor) if descriptor >= 0 else None
        if descriptor >= 0:
            os.close(descriptor)
        if not installed and cleanup_identity is not None:
            _remove_private_if_same(workspace, "payload", cleanup_identity)
        os.close(workspace)
        if not preserve_workspace:
            _remove_private_if_same(parent, workspace_name, workspace_identity, directory=True)
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
            os.close(parent)
    except (KeyError, OSError, OverflowError, TypeError, ValueError) as exc:
        module.fail_json(msg=f"atomic path mutation failed: {exc}", path=path)


if __name__ == "__main__":
    main()
