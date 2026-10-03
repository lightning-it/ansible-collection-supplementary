"""Bind the exact staged release files for a later publication job.

This pure, secret-free handoff checks bytes and source identities. The protected
workflow must supply the expected binding independently of the downloaded
artifact and carry the manifest SHA-256 in a trusted job output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

SCHEMA = "lit.supplementary.release-stage-handoff/v1"
ROOTS = ("dist", "incoming")
MAX_FILES = 1024
MAX_DIRECTORIES = 4096
MAX_TOTAL_BYTES = 2_000_000_000
MAX_MANIFEST_BYTES = 1_000_000
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z")
EVIDENCE = re.compile(r"MLX90-[A-Z0-9][A-Z0-9._-]{2,127}\Z")
BINDING_KEYS = {
    "candidateName",
    "ciRunAttempt",
    "ciRunId",
    "galaxyRequired",
    "releaseVersion",
    "securityEvidenceId",
    "securityRelease",
    "sourceRunAttempt",
    "sourceRunId",
    "sourceSha",
}


class HandoffError(ValueError):
    """A staged release cannot be trusted or restored."""


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
        + b"\n"
    )


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HandoffError("duplicate JSON key")
        result[key] = value
    return result


def load_canonical(payload: bytes, label: str) -> dict[str, Any]:
    if not payload or len(payload) > MAX_MANIFEST_BYTES:
        raise HandoffError(f"{label} size is invalid")
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"), object_pairs_hook=unique_pairs)
    except HandoffError:
        raise
    except (UnicodeError, ValueError, RecursionError) as error:
        raise HandoffError(f"{label} is invalid JSON") from error
    try:
        canonical_payload = canonical(value)
    except (ValueError, RecursionError) as error:
        raise HandoffError(f"{label} is invalid JSON") from error
    if type(value) is not dict or canonical_payload != payload:
        raise HandoffError(f"{label} is not canonical JSON")
    return value


def positive(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise HandoffError(f"{label} must be a positive integer")
    return value


def validate_binding(binding: dict[str, Any]) -> None:
    if type(binding) is not dict or set(binding) != BINDING_KEYS:
        raise HandoffError("handoff binding shape differs")
    if type(binding["sourceSha"]) is not str or SHA.fullmatch(binding["sourceSha"]) is None:
        raise HandoffError("source SHA is invalid")
    for key in ("sourceRunId", "sourceRunAttempt", "ciRunId", "ciRunAttempt"):
        positive(binding[key], key)
    if type(binding["releaseVersion"]) is not str or VERSION.fullmatch(binding["releaseVersion"]) is None:
        raise HandoffError("release version is invalid")
    if type(binding["candidateName"]) is not str or NAME.fullmatch(binding["candidateName"]) is None:
        raise HandoffError("candidate name is invalid")
    if binding["candidateName"] != f"lit-supplementary-{binding['releaseVersion']}.tar.gz":
        raise HandoffError("candidate name does not match release version")
    if type(binding["securityRelease"]) is not bool or type(binding["galaxyRequired"]) is not bool:
        raise HandoffError("release flags must be boolean")
    evidence = binding["securityEvidenceId"]
    if binding["securityRelease"]:
        if type(evidence) is not str or EVIDENCE.fullmatch(evidence) is None:
            raise HandoffError("security release evidence binding is invalid")
    elif evidence is not None:
        raise HandoffError("ordinary release must not carry security evidence ID")


def safe_relative(path: str) -> None:
    try:
        encoded = path.encode("utf-8") if type(path) is str else b""
    except UnicodeError as error:
        raise HandoffError("handoff file path is invalid") from error
    if not (0 < len(encoded) <= 1024):
        raise HandoffError("handoff file path is invalid")
    parts = path.split("/")
    if parts[0] not in ROOTS or any(part in ("", ".", "..", ".git") for part in parts):
        raise HandoffError("handoff file path is unsafe")
    if any(
        any(ord(character) < 32 or ord(character) == 127 or character == "\\" for character in part) for part in parts
    ):
        raise HandoffError("handoff file path contains control characters")


def digest_file(path: Path) -> tuple[str, int]:
    if not hasattr(os, "O_NOFOLLOW"):
        raise HandoffError("platform lacks safe no-follow file open")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise HandoffError("handoff file cannot be opened safely") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_mode & 0o111:
            raise HandoffError("handoff file is not ordinary nonexecutable data")
        if before.st_size > MAX_TOTAL_BYTES:
            raise HandoffError("handoff byte limit exceeded")
        digest = hashlib.sha256()
        with os.fdopen(os.dup(descriptor), "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
        ):
            raise HandoffError("handoff file changed while being hashed")
        return digest.hexdigest(), after.st_size
    finally:
        os.close(descriptor)


def inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pending = [root / name for name in ROOTS]
    directories = len(pending)
    total_bytes = 0
    for directory in pending:
        if not directory.is_dir() or directory.is_symlink():
            raise HandoffError("handoff root directory is missing or unsafe")
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for child in children:
            relative = Path(child.path).relative_to(root).as_posix()
            safe_relative(relative)
            if child.is_symlink():
                raise HandoffError("handoff tree contains a symlink")
            if child.is_dir(follow_symlinks=False):
                pending.append(Path(child.path))
                directories += 1
                if directories > MAX_DIRECTORIES:
                    raise HandoffError("handoff directory limit exceeded")
            elif child.is_file(follow_symlinks=False):
                digest, size = digest_file(Path(child.path))
                rows.append({"path": relative, "sha256": digest, "size": size})
                total_bytes += size
                if len(rows) > MAX_FILES or total_bytes > MAX_TOTAL_BYTES:
                    raise HandoffError("handoff file or byte limit exceeded")
            else:
                raise HandoffError("handoff tree contains a special file")
    rows.sort(key=lambda row: row["path"])
    return rows


def build_manifest(root: Path, binding: dict[str, Any]) -> dict[str, Any]:
    validate_binding(binding)
    rows = inventory(root)
    by_path = {row["path"]: row for row in rows}
    name = binding["candidateName"]
    candidate = by_path.get(f"incoming/candidate/{name}")
    attachment = by_path.get(f"dist/release/{name}")
    if candidate is None or attachment is None or candidate["sha256"] != attachment["sha256"]:
        raise HandoffError("candidate and release attachment are missing or differ")
    nexus = by_path.get("dist/validation/nexus-stage.json")
    if binding["securityRelease"] and binding["galaxyRequired"] and nexus is None:
        raise HandoffError("security release lacks staged Nexus manifest")
    return {
        "binding": binding,
        "files": rows,
        "nexusStageSha256": nexus["sha256"] if nexus is not None else None,
        "schema": SCHEMA,
        "totalBytes": sum(row["size"] for row in rows),
    }


def verify(root: Path, binding: dict[str, Any], manifest_payload: bytes, expected_sha256: str) -> None:
    if type(expected_sha256) is not str or DIGEST.fullmatch(expected_sha256) is None:
        raise HandoffError("handoff manifest digest is invalid")
    if not manifest_payload or len(manifest_payload) > MAX_MANIFEST_BYTES:
        raise HandoffError("handoff manifest size is invalid")
    if hashlib.sha256(manifest_payload).hexdigest() != expected_sha256:
        raise HandoffError("handoff manifest digest differs")
    recorded = load_canonical(manifest_payload, "handoff manifest")
    if set(recorded) != {"schema", "binding", "files", "totalBytes", "nexusStageSha256"}:
        raise HandoffError("handoff manifest shape differs")
    if manifest_payload != canonical(build_manifest(root, binding)):
        raise HandoffError("staged release files or source binding changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("create", "verify"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    try:
        binding = load_canonical(args.binding.read_bytes(), "handoff binding")
        if args.mode == "create":
            if args.expected_sha256 is not None:
                raise HandoffError("create mode cannot accept an expected digest")
            payload = canonical(build_manifest(args.root, binding))
            if len(payload) > MAX_MANIFEST_BYTES:
                raise HandoffError("handoff manifest output is unsafe")
            with args.manifest.open("xb") as stream:
                stream.write(payload)
            print(hashlib.sha256(payload).hexdigest())
        else:
            verify(args.root, binding, args.manifest.read_bytes(), args.expected_sha256)
    except (OSError, HandoffError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
