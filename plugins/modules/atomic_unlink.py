#!/usr/bin/python
# Copyright: (c) 2026 Lightning IT
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
# ruff: noqa: E402

DOCUMENTATION = r"""
---
module: atomic_unlink
version_added: "3.3.0"
short_description: Unlink one exactly identified regular file
description:
  - Descriptor-binds and verifies one file before quarantined removal.
  - Requires exclusive trust in the effective UID; hostile concurrent processes
    with that same UID are outside the isolation boundary.
options:
  path:
    description: Canonical absolute path of the regular file to remove.
    type: path
    required: true
  checksum:
    description: Exact lowercase SHA-256 checksum required before removal.
    type: str
    required: true
  mode:
    description: Exact octal permissions required before removal.
    type: str
    required: true
  owner:
    description: Exact owner name or numeric UID required before removal.
    type: str
    required: true
  group:
    description: Exact group name or numeric GID required before removal.
    type: str
    required: true
  allow_absent:
    description: Treat an already absent path as an unchanged success.
    type: bool
    default: false
  parent_identities:
    description: Canonical parent paths mapped to their device and inode identities.
    type: dict
    required: true
author:
  - Lightning IT (@lightning-it)
"""

EXAMPLES = r"""
- name: Remove one exact role-owned file
  lit.supplementary.atomic_unlink:
    path: /etc/lit/forward-proxy/squid.conf
    checksum: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
    mode: "0644"
    owner: root
    group: root
    parent_identities:
      /etc/lit/forward-proxy:
        device: 2049
        inode: 123456
"""

RETURN = r"""
path:
  description: Canonical path that was verified for removal.
  type: str
  returned: always
recovery_path:
  description: Descriptor-stable quarantine path retained after uncertain cleanup.
  type: str
  returned: on failure after quarantine
quarantine_cleanup_warning:
  description: Warning emitted when removal succeeded but private cleanup did not.
  type: str
  returned: on successful unlink with a quarantine cleanup error
"""

import grp
import hashlib
import os
import pwd
import re
import secrets
import stat

from ansible.module_utils.basic import AnsibleModule


def _numeric_identity(value: str, database: object, kind: str) -> int:
    if re.fullmatch(r"[+-]?\d+", value):
        identity = int(value, 10)
        if identity < 0 or identity >= 2**32 - 1:
            raise ValueError(f"{kind} ID must fit a non-negative 32-bit identity")
        return identity
    try:
        record = database(value)
    except KeyError as exc:
        raise ValueError(f"unknown {kind}: {value}") from exc
    identity = record.pw_uid if kind == "owner" else record.gr_gid
    if identity < 0 or identity >= 2**32 - 1:
        raise ValueError(f"{kind} ID must fit a non-negative 32-bit identity")
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


def _open_parent(path: str, parent_identities: dict) -> tuple[int, str]:
    parts = path[1:].split("/")
    name = parts.pop()
    current_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    current_path = ""
    try:
        for component in parts:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
            current_path += "/" + component
            if current_path in parent_identities:
                opened = os.fstat(current_fd)
                expected = parent_identities[current_path]
                if (opened.st_dev, opened.st_ino) != (
                    _strict_integer(expected["device"], "device"),
                    _strict_integer(expected["inode"], "inode"),
                ):
                    raise OSError(f"trusted parent identity changed: {current_path}")
        parent_path = os.path.dirname(path)
        if parent_path not in parent_identities:
            raise OSError("exact parent identity binding is missing")
        if parent_path == "/":
            expected = parent_identities[parent_path]
            opened = os.fstat(current_fd)
            if (opened.st_dev, opened.st_ino) != (
                _strict_integer(expected["device"], "device"),
                _strict_integer(expected["inode"], "inode"),
            ):
                raise OSError("trusted parent identity changed: /")
        return current_fd, name
    except Exception:
        os.close(current_fd)
        raise


def _checksum_fd(file_fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(file_fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(file_fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


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


def _require_capabilities() -> None:
    flags = ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    functions = (os.open, os.stat, os.mkdir, os.rename, os.link, os.unlink, os.rmdir)
    if any(not hasattr(os, flag) for flag in flags) or any(
        function not in getattr(os, "supports_dir_fd", ()) for function in functions
    ):
        raise OSError("descriptor-relative no-follow filesystem operations are unavailable")
    if os.stat not in getattr(os, "supports_follow_symlinks", ()):
        raise OSError("no-follow stat is unavailable")
    if not os.path.isdir("/proc/self/fd"):
        raise OSError("descriptor-linking procfs is unavailable")


def _make_private_quarantine(parent_fd: int) -> tuple[int, str]:
    for _attempt in range(10):
        quarantine_name = f".atomic-unlink-{os.getpid()}-{secrets.token_hex(16)}"
        try:
            os.mkdir(quarantine_name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        try:
            quarantine_fd = os.open(
                quarantine_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except OSError:
            try:
                os.rmdir(quarantine_name, dir_fd=parent_fd)
            except OSError:
                pass
            raise
        return quarantine_fd, quarantine_name
    raise OSError("cannot allocate a private atomic-unlink quarantine")


def _preserve_open_file(file_fd: int, quarantine_fd: int, expected: os.stat_result) -> None:
    """Hard-link the descriptor-bound inode before any pathname mutation."""
    os.link(
        f"/proc/self/fd/{file_fd}",
        "verified",
        dst_dir_fd=quarantine_fd,
        follow_symlinks=True,
    )
    preserved = os.stat("verified", dir_fd=quarantine_fd, follow_symlinks=False)
    if not _same_identity(expected, preserved):
        os.unlink("verified", dir_fd=quarantine_fd)
        raise OSError("descriptor-bound quarantine identity changed")


def _restore_quarantined_file(parent_fd: int, name: str, quarantine_fd: int) -> bool:
    try:
        os.link(
            "target",
            name,
            src_dir_fd=quarantine_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except OSError:
        return False
    try:
        os.unlink("target", dir_fd=quarantine_fd)
    except OSError:
        # The canonical path is already restored as a hard link. Preserve the
        # quarantined second link for operator recovery rather than undoing it.
        pass
    return True


def _recover_quarantine(
    parent_fd: int,
    name: str,
    quarantine_fd: int,
    quarantine_name: str,
) -> tuple[bool, bool]:
    restored = _restore_quarantined_file(parent_fd, name, quarantine_fd)
    cleaned = False
    if restored:
        try:
            os.rmdir(quarantine_name, dir_fd=parent_fd)
            cleaned = True
        except OSError:
            pass
    return restored, cleaned


def _quarantine_recovery_path(path: str, quarantine_name: str, cleaned: bool) -> str:
    if cleaned:
        return ""
    return os.path.join(os.path.dirname(path), quarantine_name, "verified")


def _quarantine_recovery_summary(restored: bool, cleaned: bool) -> str:
    if restored and cleaned:
        return "entry restored"
    if restored:
        return "entry restored; recovery copy preserved in quarantine"
    return "entry preserved in quarantine"


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "path": {"type": "path", "required": True},
            "checksum": {"type": "str", "required": True, "no_log": False},
            "mode": {"type": "str", "required": True},
            "owner": {"type": "str", "required": True},
            "group": {"type": "str", "required": True},
            "allow_absent": {"type": "bool", "default": False},
            "parent_identities": {"type": "dict", "required": True},
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
        module.fail_json(msg="path must be one canonical absolute file path", path=path)

    try:
        _require_capabilities()
        expected_uid = _numeric_identity(str(module.params["owner"]), pwd.getpwnam, "owner")
        expected_gid = _numeric_identity(str(module.params["group"]), grp.getgrnam, "group")
        mode_value = str(module.params["mode"])
        if not re.fullmatch(r"[0-7]{3,4}", mode_value):
            raise ValueError("mode must contain three or four octal permission digits")
        expected_mode = int(mode_value, 8)
        if expected_mode > 0o7777:
            raise ValueError("mode exceeds the POSIX permission-bit range")
        parent_fd, name = _open_parent(path, module.params["parent_identities"])
    except (KeyError, OSError, OverflowError, TypeError, ValueError) as exc:
        module.fail_json(msg=f"cannot bind trusted parent chain: {exc}", path=path)

    file_fd = -1
    quarantine_fd = -1
    quarantine_name = ""
    try:
        checksum = str(module.params["checksum"])
        if checksum:
            if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                module.fail_json(msg="checksum must be one lowercase SHA-256 digest", path=path)
        elif not module.params["allow_absent"]:
            module.fail_json(msg="checksum must be one lowercase SHA-256 digest", path=path)

        try:
            before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            if module.params["allow_absent"]:
                module.exit_json(changed=False, path=path)
            module.fail_json(msg="owned file is absent", path=path)

        if not stat.S_ISREG(before.st_mode):
            module.fail_json(msg="removal target is not a regular file", path=path)
        if stat.S_IMODE(before.st_mode) != expected_mode:
            module.fail_json(msg="removal target mode changed", path=path)
        if before.st_uid != expected_uid or before.st_gid != expected_gid:
            module.fail_json(msg="removal target ownership changed", path=path)

        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
        opened = os.fstat(file_fd)
        if not _same_snapshot(opened, before):
            module.fail_json(msg="removal target changed while opening", path=path)
        if _checksum_fd(file_fd) != module.params["checksum"]:
            module.fail_json(msg="removal target checksum changed", path=path)

        final_fd = os.fstat(file_fd)
        final_name = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_snapshot(final_fd, final_name):
            module.fail_json(msg="removal target changed at the unlink boundary", path=path)
        if (
            not stat.S_ISREG(final_fd.st_mode)
            or stat.S_IMODE(final_fd.st_mode) != expected_mode
            or final_fd.st_uid != expected_uid
            or final_fd.st_gid != expected_gid
        ):
            module.fail_json(msg="removal target metadata changed at the unlink boundary", path=path)

        if module.check_mode:
            module.exit_json(changed=True, path=path)

        quarantine_fd, quarantine_name = _make_private_quarantine(parent_fd)
        _preserve_open_file(file_fd, quarantine_fd, final_fd)
        try:
            os.rename(
                name,
                "target",
                src_dir_fd=parent_fd,
                dst_dir_fd=quarantine_fd,
            )
        except OSError as exc:
            module.fail_json(
                msg=f"cannot quarantine the removal target: {exc}; verified inode preserved in quarantine",
                path=path,
                recovery_path=os.path.join(os.path.dirname(path), quarantine_name, "verified"),
            )
        try:
            quarantined = os.stat("target", dir_fd=quarantine_fd, follow_symlinks=False)
        except OSError as exc:
            restored, cleaned = _recover_quarantine(
                parent_fd,
                name,
                quarantine_fd,
                quarantine_name,
            )
            recovery_path = _quarantine_recovery_path(path, quarantine_name, cleaned)
            if cleaned:
                quarantine_name = ""
            module.fail_json(
                msg=(
                    f"cannot inspect the atomic quarantine: {exc}; " + _quarantine_recovery_summary(restored, cleaned)
                ),
                path=path,
                recovery_path=recovery_path,
            )
        if not _same_identity(final_fd, quarantined):
            restored, cleaned = _recover_quarantine(
                parent_fd,
                name,
                quarantine_fd,
                quarantine_name,
            )
            if cleaned:
                quarantine_name = ""
            recovery_path = _quarantine_recovery_path(path, quarantine_name, cleaned)
            module.fail_json(
                msg=(
                    "removal target changed at the atomic quarantine boundary; "
                    + _quarantine_recovery_summary(restored, cleaned)
                ),
                path=path,
                recovery_path=recovery_path,
            )

        try:
            final_quarantine = os.stat("target", dir_fd=quarantine_fd, follow_symlinks=False)
            final_checksum = _checksum_fd(file_fd)
        except OSError as exc:
            restored, cleaned = _recover_quarantine(
                parent_fd,
                name,
                quarantine_fd,
                quarantine_name,
            )
            recovery_path = _quarantine_recovery_path(path, quarantine_name, cleaned)
            if cleaned:
                quarantine_name = ""
            module.fail_json(
                msg=(
                    f"cannot revalidate the quarantined target: {exc}; "
                    + _quarantine_recovery_summary(restored, cleaned)
                ),
                path=path,
                recovery_path=recovery_path,
            )
        if (
            not _same_identity(final_fd, final_quarantine)
            or not stat.S_ISREG(final_quarantine.st_mode)
            or stat.S_IMODE(final_quarantine.st_mode) != expected_mode
            or final_quarantine.st_uid != expected_uid
            or final_quarantine.st_gid != expected_gid
            or final_checksum != module.params["checksum"]
        ):
            restored, cleaned = _recover_quarantine(
                parent_fd,
                name,
                quarantine_fd,
                quarantine_name,
            )
            if cleaned:
                quarantine_name = ""
            recovery_path = _quarantine_recovery_path(path, quarantine_name, cleaned)
            module.fail_json(
                msg=(
                    "quarantined removal target changed before deletion; "
                    + _quarantine_recovery_summary(restored, cleaned)
                ),
                path=path,
                recovery_path=recovery_path,
            )
        try:
            os.unlink("target", dir_fd=quarantine_fd)
        except OSError as exc:
            restored, cleaned = _recover_quarantine(
                parent_fd,
                name,
                quarantine_fd,
                quarantine_name,
            )
            if cleaned:
                quarantine_name = ""
            recovery_path = _quarantine_recovery_path(path, quarantine_name, cleaned)
            module.fail_json(
                msg=(
                    f"atomic unlink failed after quarantine: {exc}; " + _quarantine_recovery_summary(restored, cleaned)
                ),
                path=path,
                recovery_path=recovery_path,
            )
        try:
            os.unlink("verified", dir_fd=quarantine_fd)
        except OSError as exc:
            module.exit_json(
                changed=True,
                path=path,
                quarantine_cleanup_warning=str(exc),
                recovery_path=os.path.join(os.path.dirname(path), quarantine_name, "verified"),
            )
        os.close(quarantine_fd)
        quarantine_fd = -1
        try:
            os.rmdir(quarantine_name, dir_fd=parent_fd)
        except OSError as exc:
            module.exit_json(
                changed=True,
                path=path,
                quarantine_cleanup_warning=str(exc),
            )
        quarantine_name = ""
        module.exit_json(changed=True, path=path)
    except OSError as exc:
        module.fail_json(msg=f"atomic unlink failed: {exc}", path=path)
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if quarantine_fd >= 0:
            os.close(quarantine_fd)
        if quarantine_name:
            try:
                os.rmdir(quarantine_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


if __name__ == "__main__":
    main()
