#!/usr/bin/python
# Copyright: (c) 2026 Lightning IT
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
# ruff: noqa: E402

DOCUMENTATION = r"""
---
module: atomic_unlink
short_description: Unlink one exactly identified regular file
description:
  - Opens every parent component without following symlinks.
  - Binds the target to a file descriptor, verifies its complete identity, and
    atomically moves it into a private quarantine before revalidation and
    deletion.
options:
  path:
    description:
      - Canonical absolute path of the regular file to remove.
    type: path
    required: true
  checksum:
    description:
      - Expected SHA-256 checksum of the file contents.
    type: str
    required: true
  mode:
    description:
      - Expected octal permission mode.
    type: str
    required: true
  owner:
    description:
      - Expected owner name or numeric UID.
    type: str
    required: true
  group:
    description:
      - Expected group name or numeric GID.
    type: str
    required: true
  allow_absent:
    description:
      - Treat an already absent path as an unchanged success.
    type: bool
    default: false
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
"""

RETURN = r"""
path:
  description: Absolute path considered by the module.
  type: str
  returned: always
"""

import grp
import hashlib
import os
import pwd
import secrets
import stat
from typing import Tuple

from ansible.module_utils.basic import AnsibleModule


def _numeric_identity(value: str, database: object, kind: str) -> int:
    try:
        return int(value, 10)
    except ValueError:
        try:
            record = database(value)
        except KeyError as exc:
            raise ValueError(f"unknown {kind}: {value}") from exc
        return record.pw_uid if kind == "owner" else record.gr_gid


def _open_parent(path: str) -> Tuple[int, str]:
    parts = path[1:].split("/")
    name = parts.pop()
    current_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in parts:
            next_fd = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
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


def _make_private_quarantine(parent_fd: int) -> Tuple[int, str]:
    for _attempt in range(10):
        quarantine_name = f".atomic-unlink-{os.getpid()}-{secrets.token_hex(16)}"
        try:
            os.mkdir(quarantine_name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        quarantine_fd = os.open(
            quarantine_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        return quarantine_fd, quarantine_name
    raise OSError("cannot allocate a private atomic-unlink quarantine")


def _restore_quarantined_file(parent_fd: int, name: str, quarantine_fd: int) -> bool:
    try:
        os.link(
            "target",
            name,
            src_dir_fd=quarantine_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        return False
    os.unlink("target", dir_fd=quarantine_fd)
    return True


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "path": {"type": "path", "required": True},
            "checksum": {"type": "str", "required": True, "no_log": False},
            "mode": {"type": "str", "required": True},
            "owner": {"type": "str", "required": True},
            "group": {"type": "str", "required": True},
            "allow_absent": {"type": "bool", "default": False},
        },
        supports_check_mode=True,
    )
    path = module.params["path"]
    if not os.path.isabs(path) or os.path.normpath(path) != path or path == "/" or "\x00" in path:
        module.fail_json(msg="path must be one canonical absolute file path", path=path)

    try:
        expected_uid = _numeric_identity(str(module.params["owner"]), pwd.getpwnam, "owner")
        expected_gid = _numeric_identity(str(module.params["group"]), grp.getgrnam, "group")
        expected_mode = int(str(module.params["mode"]), 8)
        parent_fd, name = _open_parent(path)
    except (OSError, TypeError, ValueError) as exc:
        module.fail_json(msg=f"cannot bind trusted parent chain: {exc}", path=path)

    file_fd = -1
    quarantine_fd = -1
    quarantine_name = ""
    try:
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

        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        opened = os.fstat(file_fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            module.fail_json(msg="removal target changed while opening", path=path)
        if _checksum_fd(file_fd) != module.params["checksum"]:
            module.fail_json(msg="removal target checksum changed", path=path)

        final_fd = os.fstat(file_fd)
        final_name = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_identity(final_fd, final_name):
            module.fail_json(msg="removal target changed at the unlink boundary", path=path)

        if module.check_mode:
            module.exit_json(changed=True, path=path)

        quarantine_fd, quarantine_name = _make_private_quarantine(parent_fd)
        os.rename(
            name,
            "target",
            src_dir_fd=parent_fd,
            dst_dir_fd=quarantine_fd,
        )
        quarantined = os.stat("target", dir_fd=quarantine_fd, follow_symlinks=False)
        if not _same_identity(final_fd, quarantined):
            restored = _restore_quarantined_file(parent_fd, name, quarantine_fd)
            if restored:
                os.close(quarantine_fd)
                quarantine_fd = -1
                os.rmdir(quarantine_name, dir_fd=parent_fd)
                quarantine_name = ""
            module.fail_json(
                msg=(
                    "removal target changed at the atomic quarantine boundary; "
                    + ("foreign entry restored" if restored else "foreign entry preserved in quarantine")
                ),
                path=path,
            )

        final_quarantine = os.stat("target", dir_fd=quarantine_fd, follow_symlinks=False)
        if not _same_identity(final_fd, final_quarantine):
            module.fail_json(
                msg="quarantined removal target changed before deletion",
                path=path,
            )
        os.unlink("target", dir_fd=quarantine_fd)
        os.close(quarantine_fd)
        quarantine_fd = -1
        os.rmdir(quarantine_name, dir_fd=parent_fd)
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
