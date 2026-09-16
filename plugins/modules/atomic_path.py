#!/usr/bin/python
"""Descriptor-relative directory creation and atomic regular-file replacement."""

from __future__ import annotations

import grp
import hashlib
import os
import pwd
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
    try:
        return int(value, 10)
    except ValueError:
        record = database(value)
        return int(getattr(record, attribute))


def _open_bound_directory(path: str, identities: dict) -> int:
    current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    walked = ""
    try:
        for component in path[1:].split("/"):
            if not component:
                continue
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = following
            walked += "/" + component
            expected = identities.get(walked)
            if not isinstance(expected, dict):
                raise OSError(f"parent identity is missing: {walked}")
            opened = os.fstat(current)
            try:
                identity = (int(expected["device"]), int(expected["inode"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise OSError(f"parent identity is malformed: {walked}") from exc
            if (opened.st_dev, opened.st_ino) != identity:
                raise OSError(f"parent identity changed: {walked}")
        return current
    except BaseException:
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
        module.exit_json(changed=False, path=module.params["path"])
    if module.check_mode:
        module.exit_json(changed=True, path=module.params["path"])
    os.mkdir(name, mode, dir_fd=parent)
    directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        os.fchown(directory, uid, gid)
        os.fchmod(directory, mode)
        if not _matches(os.fstat(directory), mode, uid, gid):
            raise OSError("created directory metadata could not be bound")
    finally:
        os.close(directory)
    os.fsync(parent)
    _revalidate_parent(module, parent)
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
        bound = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            opened = os.fstat(bound)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                module.fail_json(msg="file boundary changed while opening", path=module.params["path"])
            if not isinstance(expected_checksum, str) or _checksum(bound) != expected_checksum:
                module.fail_json(msg="file boundary checksum changed", path=module.params["path"])
        finally:
            os.close(bound)
    if before is not None and expected_checksum == desired:
        _revalidate_parent(module, parent)
        module.exit_json(changed=False, path=module.params["path"], checksum=desired)
    if module.check_mode:
        module.exit_json(changed=True, path=module.params["path"], checksum=desired)
    temporary = f".atomic-path-{os.getpid()}-{secrets.token_hex(16)}"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
    try:
        os.fchown(descriptor, uid, gid)
        os.fchmod(descriptor, mode)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("atomic file write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        if not _matches(os.fstat(descriptor), mode, uid, gid):
            raise OSError("temporary file metadata could not be bound")
        current = _existing(parent, name)
        if before is None:
            if current is not None:
                raise OSError("file boundary appeared before replacement")
        elif current is None or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise OSError("file boundary changed before replacement")
        os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        temporary = ""
        os.fsync(parent)
        _revalidate_parent(module, parent)
    finally:
        os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary, dir_fd=parent)
            except OSError:
                pass
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
    if not os.path.isabs(path) or os.path.normpath(path) != path or path == "/" or "\x00" in path:
        module.fail_json(msg="path must be one canonical absolute path", path=path)
    try:
        mode = int(str(module.params["mode"]), 8)
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
    except (KeyError, OSError, TypeError, ValueError) as exc:
        module.fail_json(msg=f"atomic path mutation failed: {exc}", path=path)


if __name__ == "__main__":
    main()
