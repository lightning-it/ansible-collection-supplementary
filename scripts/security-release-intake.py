"""Validate and materialize an evidence-bound Security release intake.

The intake contract deliberately starts after a trusted system has confirmed a
Security fix. It never infers Security semantics from a branch, label, commit
message, or AI result. Instead, it binds an exact source range and its binary
Git diff to reviewed metadata already present in that range.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
EVIDENCE_ID = re.compile(r"^MLX90-[A-Z0-9][A-Z0-9._-]{2,127}$")
SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,127}$")
SECURITY_ID = re.compile(
    r"^(?:CVE-[0-9]{4}-[0-9]{4,}|"
    r"GHSA-[23456789cfghjmpqrvwx]{4}(?:-[23456789cfghjmpqrvwx]{4}){2}|"
    r"LIT-SEC-[A-Z0-9._-]+)$"
)
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CANONICAL_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
REQUEST_KEYS = {
    "schemaVersion",
    "event",
    "repository",
    "baseSha",
    "candidateRef",
    "candidateBaseSha",
    "candidateHeadSha",
    "candidateDiffSha256",
    "evidenceId",
    "fixedVersion",
    "issuedAt",
    "expiresAt",
    "humanActions",
}
METADATA_KEYS = {
    "schemaVersion",
    "evidenceId",
    "createdAt",
    "securityIdentifiers",
    "affectedVersion",
    "fixedVersion",
    "consumers",
    "acceptanceProfile",
    "validity",
}
VALIDITY_KEYS = {"notBefore", "expiresAt", "revoked"}
FORBIDDEN_PATHS = {
    ".lit/security-release-profiles.json",
    "scripts/security-release-intake.py",
    ".github/workflows/security-release-intake.yml",
}
RUNTIME_PRODUCT_PREFIXES = (
    "bootstrap/",
    "collections/",
    "containerfiles/",
    "manifests/",
    "playbooks/",
    "plugins/",
    "roles/",
)
SUPPORTING_PRODUCT_PREFIXES = (
    "docs/",
    "examples/",
    "molecule/",
    "tests/integration/",
    "tests/unit/",
)
PRODUCT_PATH_PREFIXES = RUNTIME_PRODUCT_PREFIXES + SUPPORTING_PRODUCT_PREFIXES
FORBIDDEN_SUPPORTING_PATHS = {
    "tests/unit/test_workflow_security.py",
}
MAX_DIFF_BYTES = 4 * 1024 * 1024


class IntakeError(ValueError):
    """Raised when the intake cannot be proven safe."""


def fail(message: str) -> None:
    raise IntakeError(message)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda value: fail(f"invalid JSON constant: {value}"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntakeError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def load_json_file(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        fail(f"{label} must be a regular non-symlink file")
    return load_json_bytes(path.read_bytes(), label)


def exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        fail(f"{label} fields mismatch; missing={missing}, unknown={unknown}")


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        fail(f"{label} must be a non-empty trimmed string")
    if "\n" in value or "\r" in value or "\x00" in value:
        fail(f"{label} must be a single-line string")
    return value


def timestamp(value: object, label: str) -> datetime:
    text = require_string(value, label)
    if CANONICAL_TIME.fullmatch(text) is None:
        fail(f"{label} must be canonical UTC RFC3339")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise IntakeError(f"{label} is not a valid timestamp") from exc


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(variable, None)
    return environment


def run_git(root: Path, *args: str, text: bool = False) -> bytes | str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=text,
            env=git_environment(),
        )
    except subprocess.CalledProcessError as exc:
        stderr = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else exc.stderr.decode("utf-8", errors="replace")
        )
        raise IntakeError(f"git {' '.join(args)} failed: {stderr.strip()}") from exc
    return result.stdout


def git_text(root: Path, *args: str) -> str:
    value = run_git(root, *args, text=True)
    assert isinstance(value, str)
    return value


def git_bytes(root: Path, *args: str) -> bytes:
    value = run_git(root, *args)
    assert isinstance(value, bytes)
    return value


def validate_request(
    request: dict[str, Any], repository: str, now: datetime
) -> dict[str, Any]:
    exact_keys(request, REQUEST_KEYS, "Security intake request")
    if request["schemaVersion"] != 1:
        fail("Security intake schemaVersion must be 1")
    if request["event"] != "mlx90-security-release":
        fail("Security intake event is unsupported")
    if request["repository"] != repository:
        fail("Security intake repository does not match the live repository")
    if request["humanActions"] != 0:
        fail("Security Zero-Touch intake must declare humanActions=0")

    for field in ("baseSha", "candidateBaseSha", "candidateHeadSha"):
        value = require_string(request[field], field)
        if SHA.fullmatch(value) is None:
            fail(f"{field} must be a full lowercase commit SHA")
    if request["candidateBaseSha"] == request["candidateHeadSha"]:
        fail("candidate source range must not be empty")
    if request["candidateBaseSha"] != request["baseSha"]:
        fail("candidate source range must start at the authorized protected-main SHA")
    digest = require_string(request["candidateDiffSha256"], "candidateDiffSha256")
    if DIGEST.fullmatch(digest) is None:
        fail("candidateDiffSha256 must be a canonical SHA-256 digest")
    evidence_id = require_string(request["evidenceId"], "evidenceId")
    if EVIDENCE_ID.fullmatch(evidence_id) is None:
        fail("evidenceId is invalid")
    version = require_string(request["fixedVersion"], "fixedVersion")
    if SEMVER.fullmatch(version) is None:
        fail("fixedVersion must be stable SemVer")
    candidate_ref = require_string(request["candidateRef"], "candidateRef")
    if REF.fullmatch(candidate_ref) is None or candidate_ref.startswith("/"):
        fail("candidateRef is invalid")
    if candidate_ref != "develop":
        fail("candidateRef must be the protected develop integration branch")

    issued = timestamp(request["issuedAt"], "issuedAt")
    expires = timestamp(request["expiresAt"], "expiresAt")
    if expires <= issued:
        fail("Security intake validity interval is empty")
    if now < issued or now >= expires:
        fail("Security intake request is not currently valid")
    return request


def canonical_diff(root: Path, base_sha: str, head_sha: str) -> bytes:
    value = git_bytes(
        root,
        "-c",
        "core.safecrlf=false",
        "diff",
        "--binary",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        base_sha,
        head_sha,
        "--",
        ".",
    )
    if not value:
        fail("candidate diff is empty")
    if len(value) > MAX_DIFF_BYTES:
        fail(f"candidate diff exceeds {MAX_DIFF_BYTES} bytes")
    return value


def sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def changed_paths(root: Path, base_sha: str, head_sha: str) -> list[tuple[str, str]]:
    raw = git_bytes(
        root,
        "diff",
        "--name-status",
        "-z",
        "--no-renames",
        base_sha,
        head_sha,
        "--",
        ".",
    )
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        fail("candidate diff contains an unsupported name-status record")
    result: list[tuple[str, str]] = []
    for index in range(0, len(fields), 2):
        try:
            status = fields[index].decode("ascii")
            path = fields[index + 1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IntakeError("candidate path is not canonical UTF-8") from exc
        if status not in {"A", "M", "D"}:
            fail(f"candidate path has unsupported status {status}: {path}")
        if (
            not path
            or path.startswith("/")
            or "\x00" in path
            or any(part in {"", ".", ".."} for part in Path(path).parts)
        ):
            fail(f"candidate path is unsafe: {path}")
        result.append((status, path))
    if not result:
        fail("candidate source range has no changed paths")
    return result


def show_json(root: Path, sha: str, path: str, label: str) -> dict[str, Any]:
    return load_json_bytes(git_bytes(root, "show", f"{sha}:{path}"), label)


def validate_metadata(
    root: Path,
    request: dict[str, Any],
    paths: list[tuple[str, str]],
    now: datetime,
) -> tuple[str, str]:
    version = request["fixedVersion"]
    metadata_path = f".lit/security-releases/{version}.json"
    if paths.count(("A", metadata_path)) != 1:
        fail("candidate must add exactly one immutable Security metadata file")
    if any(path == metadata_path and status != "A" for status, path in paths):
        fail("existing Security metadata must never be replaced")
    if any(
        path.startswith(".github/") or path in FORBIDDEN_PATHS
        for _path_status, path in paths
    ):
        fail("candidate diff modifies Security controls or workflow policy")
    fragments = [
        path
        for status, path in paths
        if status == "A" and re.fullmatch(r"changelogs/fragments/[^/]+\.ya?ml", path)
    ]
    if len(fragments) != 1:
        fail("candidate must add exactly one Security changelog fragment")
    product_paths = [
        path
        for _path_status, path in paths
        if path not in {metadata_path, fragments[0]}
    ]
    if not product_paths:
        fail("candidate must contain an evidence-bound product change")
    unsupported_paths = [
        path
        for path in product_paths
        if path in FORBIDDEN_SUPPORTING_PATHS
        or not path.startswith(PRODUCT_PATH_PREFIXES)
    ]
    if unsupported_paths:
        fail(
            "candidate modifies paths outside the Security product allowlist: "
            + ", ".join(sorted(unsupported_paths))
        )
    if not any(path.startswith(RUNTIME_PRODUCT_PREFIXES) for path in product_paths):
        fail("candidate must contain a runtime product change")

    metadata = show_json(
        root,
        request["candidateHeadSha"],
        metadata_path,
        "Security release metadata",
    )
    exact_keys(metadata, METADATA_KEYS, "Security release metadata")
    if metadata["schemaVersion"] != 1:
        fail("Security release metadata schemaVersion must be 1")
    if metadata["evidenceId"] != request["evidenceId"]:
        fail("Security metadata evidenceId does not match the intake")
    if metadata["fixedVersion"] != version:
        fail("Security metadata fixedVersion does not match the intake")
    identifiers = metadata["securityIdentifiers"]
    if (
        not isinstance(identifiers, list)
        or not identifiers
        or len(identifiers) != len(set(identifiers))
        or any(
            not isinstance(item, str) or SECURITY_ID.fullmatch(item) is None
            for item in identifiers
        )
    ):
        fail("Security metadata identifiers are invalid")
    affected_version = require_string(metadata["affectedVersion"], "affectedVersion")
    if SEMVER.fullmatch(affected_version) is None or affected_version == version:
        fail("Security metadata affectedVersion is invalid")
    consumers = metadata["consumers"]
    if (
        not isinstance(consumers, list)
        or not consumers
        or len(consumers) != len(set(consumers))
        or any(
            not isinstance(consumer, str) or REPOSITORY.fullmatch(consumer) is None
            for consumer in consumers
        )
    ):
        fail("Security metadata consumer allowlist is invalid")
    if metadata["validity"].__class__ is not dict:
        fail("Security metadata validity must be an object")
    exact_keys(metadata["validity"], VALIDITY_KEYS, "Security release validity")
    if metadata["validity"]["revoked"] is not False:
        fail("Security release metadata is revoked")
    created = timestamp(metadata["createdAt"], "createdAt")
    not_before = timestamp(metadata["validity"]["notBefore"], "validity.notBefore")
    expires = timestamp(metadata["validity"]["expiresAt"], "validity.expiresAt")
    if created < not_before or created >= expires:
        fail("Security metadata createdAt is outside its validity interval")
    if now < not_before or now >= expires:
        fail("Security release metadata is not currently valid")

    profile_id = require_string(metadata["acceptanceProfile"], "acceptanceProfile")
    if PROFILE.fullmatch(profile_id) is None:
        fail("acceptanceProfile is invalid")
    profiles = show_json(
        root,
        request["baseSha"],
        ".lit/security-release-profiles.json",
        "protected-main acceptance-profile registry",
    )
    exact_keys(profiles, {"schemaVersion", "profiles"}, "acceptance-profile registry")
    if profiles["schemaVersion"] != 1 or not isinstance(profiles["profiles"], dict):
        fail("acceptance-profile registry is unsupported")
    profile = profiles["profiles"].get(profile_id)
    if not isinstance(profile, dict) or profile.get("releaseEligible") is not True:
        fail("acceptance profile was not pre-approved on protected main")

    galaxy = git_text(root, "show", f"{request['baseSha']}:galaxy.yml")
    match = re.search(r"(?m)^version:\s*[\"']?([^\s\"']+)", galaxy)
    if match is None or SEMVER.fullmatch(match.group(1)) is None:
        fail("protected-main galaxy.yml has no stable version")
    current = tuple(int(part) for part in match.group(1).split("."))
    fixed = tuple(int(part) for part in version.split("."))
    if fixed != (current[0], current[1], current[2] + 1):
        fail("Security intake fixedVersion must be the next patch after protected main")
    return metadata_path, profile_id


def reject_special_modes(root: Path, base_sha: str, head_sha: str) -> None:
    raw = git_text(root, "diff", "--raw", "--no-renames", base_sha, head_sha, "--", ".")
    for line in raw.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 5:
            fail("candidate diff contains an invalid raw record")
        old_mode = fields[0].removeprefix(":")
        new_mode = fields[1]
        if old_mode in {"120000", "160000"} or new_mode in {"120000", "160000"}:
            fail("candidate diff contains a symlink or Gitlink")


def verify_repository(
    root: Path,
    request: dict[str, Any],
    now: datetime,
) -> tuple[bytes, dict[str, Any]]:
    if not (root / ".git").exists():
        fail("--root must be a Git worktree")
    for sha in (
        request["baseSha"],
        request["candidateBaseSha"],
        request["candidateHeadSha"],
    ):
        git_text(root, "cat-file", "-e", f"{sha}^{{commit}}")
    live_main = git_text(root, "rev-parse", "refs/remotes/origin/main").strip()
    if live_main != request["baseSha"]:
        fail("protected main changed after Security intake authorization")
    live_candidate = git_text(
        root, "rev-parse", f"refs/remotes/origin/{request['candidateRef']}"
    ).strip()
    if (
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                request["candidateHeadSha"],
                live_candidate,
            ],
            cwd=root,
            check=False,
            env=git_environment(),
        ).returncode
        != 0
    ):
        fail("candidateHeadSha is not reachable from the declared live candidateRef")
    if (
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                request["candidateBaseSha"],
                request["candidateHeadSha"],
            ],
            cwd=root,
            check=False,
            env=git_environment(),
        ).returncode
        != 0
    ):
        fail("candidate source range is not an ancestry-ordered range")

    patch = canonical_diff(
        root, request["candidateBaseSha"], request["candidateHeadSha"]
    )
    actual_digest = sha256(patch)
    if actual_digest != request["candidateDiffSha256"]:
        fail("candidate diff digest does not match the approved intake")
    paths = changed_paths(
        root, request["candidateBaseSha"], request["candidateHeadSha"]
    )
    reject_special_modes(root, request["candidateBaseSha"], request["candidateHeadSha"])
    metadata_path, profile_id = validate_metadata(root, request, paths, now)
    result = {
        "branch": f"security-release/{request['evidenceId']}",
        "baseSha": request["baseSha"],
        "candidateBaseSha": request["candidateBaseSha"],
        "candidateHeadSha": request["candidateHeadSha"],
        "candidateDiffSha256": actual_digest,
        "evidenceId": request["evidenceId"],
        "fixedVersion": request["fixedVersion"],
        "metadataPath": metadata_path,
        "acceptanceProfile": profile_id,
        "changedPaths": [path for _path_status, path in paths],
        "humanActions": 0,
    }
    return patch, result


def write_exclusive(path: Path, value: bytes) -> None:
    if path.exists() or path.is_symlink():
        fail(f"refusing to replace output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--now", default="")
    parser.add_argument("--output-patch", type=Path)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    try:
        now = timestamp(args.now, "--now") if args.now else datetime.now(UTC)
        request = validate_request(
            load_json_file(args.request, "Security intake request"),
            require_string(args.repository, "--repository"),
            now,
        )
        patch, result = verify_repository(args.root.resolve(), request, now)
        serialized = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
        if args.output_patch:
            write_exclusive(args.output_patch, patch)
        if args.output_json:
            write_exclusive(args.output_json, serialized.encode("utf-8"))
        print(serialized, end="")
    except (IntakeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
