#!/usr/bin/env python3
"""Emit a per-invocation local identity shared by Molecule lifecycle children."""

from __future__ import annotations

import argparse
import os
import re
import stat
from pathlib import Path

SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")
VALID_RUN_ID = re.compile(r"^local-[A-Za-z0-9._-]+-[1-9][0-9]*-[0-9]+$")


def _process(pid: int) -> tuple[int, int, list[str]] | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat[stat.rfind(")") + 2 :].split()
        parent_pid = int(fields[1])
        start_time = int(fields[19])
        command_line = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", errors="replace").split("\0")
    except (FileNotFoundError, IndexError, OSError, ValueError):
        return None
    return parent_pid, start_time, [item for item in command_line if item]


def _invocation() -> tuple[int, int]:
    pid = os.getppid()
    ansible_invocation: tuple[int, int] | None = None
    while pid > 1:
        process = _process(pid)
        if process is None:
            break
        parent_pid, start_time, command_line = process
        executable_names = {Path(argument).name for argument in command_line}
        if "ansible-playbook" in executable_names and ansible_invocation is None:
            ansible_invocation = (pid, start_time)
        if "molecule" in executable_names:
            return pid, start_time
        pid = parent_pid
    return ansible_invocation or (os.getppid(), 0)


def _new_run_id() -> str:
    user = SAFE_COMPONENT.sub("-", os.environ.get("USER", "user")).strip("-.") or "user"
    pid, start_time = _invocation()
    return f"local-{user}-{pid}-{start_time}"


def _read_state(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimeError(f"local run identity is not a regular file: {path}")
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise RuntimeError(f"local run identity has unsafe ownership or mode: {path}")
        content = os.read(descriptor, 257)
    finally:
        os.close(descriptor)
    if len(content) > 256:
        raise RuntimeError(f"local run identity is unexpectedly large: {path}")
    value = content.decode("utf-8").strip()
    if VALID_RUN_ID.fullmatch(value) is None:
        raise RuntimeError(f"local run identity has invalid content: {path}")
    return value


def persistent_run_id(path: Path) -> str:
    """Atomically create or securely reuse a context-scoped local run identity."""

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = path.parent.stat(follow_symlinks=False)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o022:
        raise RuntimeError(f"local run identity directory is unsafe: {path.parent}")
    try:
        return _read_state(path)
    except FileNotFoundError:
        pass

    value = _new_run_id()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        return _read_state(path)
    try:
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(f"{value}\n".encode())
        while remaining:
            remaining = remaining[os.write(descriptor, remaining) :]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-file",
        type=Path,
        help="secure context-scoped file used to persist identity across Molecule processes",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    print(persistent_run_id(args.state_file) if args.state_file is not None else _new_run_id())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
