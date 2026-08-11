"""Validate and materialize an evidence-bound Security release intake.

The intake contract deliberately starts after a trusted system has confirmed a
Security fix. It never infers Security semantics from a branch, label, commit
message, or AI result. Instead, it binds an exact source range and its binary
Git diff to reviewed metadata already present in that range.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import security_release_contract as CONTRACT  # noqa: E402

SHA = CONTRACT.SHA
DIGEST = CONTRACT.DIGEST
EVIDENCE_ID = CONTRACT.EVIDENCE_ID
SEMVER = CONTRACT.SEMVER
REF = CONTRACT.REF
PROFILE = CONTRACT.PROFILE
SECURITY_ID = CONTRACT.SECURITY_ID
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
CANONICAL_TIME = CONTRACT.CANONICAL_TIME
REQUEST_KEYS = CONTRACT.REQUEST_KEYS
METADATA_KEYS = CONTRACT.METADATA_KEYS
VALIDITY_KEYS = CONTRACT.VALIDITY_KEYS
FORBIDDEN_PATHS = {
    ".lit/security-release-profiles.json",
    "scripts/security_release_contract.py",
    "scripts/security-release-dispatch.py",
    "scripts/security-release-intake.py",
    "scripts/release-version.py",
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
SUPPORTING_PRODUCT_PATHS = frozenset({"meta/source-dependencies.yml"})
PRODUCT_PATH_PREFIXES = RUNTIME_PRODUCT_PREFIXES + SUPPORTING_PRODUCT_PREFIXES
FORBIDDEN_SUPPORTING_PATHS = {
    "tests/unit/test_workflow_security.py",
}
MAX_DIFF_BYTES = 4 * 1024 * 1024


IntakeError = CONTRACT.ContractError
fail = CONTRACT.fail
reject_duplicate_keys = CONTRACT.reject_duplicate_keys
load_json_bytes = CONTRACT.load_json_bytes
require_string = CONTRACT.require_string
timestamp = CONTRACT.timestamp


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(variable, None)
    return environment


def git_binary() -> str:
    executable = shutil.which("git")
    if executable is None:
        fail("git executable is unavailable")
    return executable


def run_git(root: Path, *args: str, text: bool = False) -> bytes | str:
    try:
        result = subprocess.run(  # noqa: S603 -- arguments are exact validated contract inputs.
            [git_binary(), *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=text,
            env=git_environment(),
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", errors="replace")
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


def validate_request(request: dict[str, Any], repository: str, now: datetime) -> dict[str, Any]:
    return CONTRACT.validate_request(request, repository, now)


def load_canonical_document(path: Path, label: str) -> dict[str, Any]:
    raw = CONTRACT.read_bounded_regular_file(
        path.parent,
        Path(path.name),
        label,
        CONTRACT.MAX_JSON_BYTES,
    )
    value = load_json_bytes(raw, label)
    if raw != CONTRACT.canonical_document_bytes(value):
        fail(f"{label} must be canonical compact JSON with one trailing newline")
    return value


def load_canonical_request(path: Path) -> dict[str, Any]:
    return load_canonical_document(path, "Security intake request")


def canonical_diff(root: Path, base_sha: str, head_sha: str) -> bytes:
    value = git_bytes(
        root,
        "-c",
        "core.safecrlf=false",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "diff.renames=false",
        "-c",
        "diff.algorithm=myers",
        "-c",
        "diff.indentHeuristic=false",
        "diff",
        "--binary",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--diff-algorithm=myers",
        "--no-indent-heuristic",
        "--unified=3",
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
    return CONTRACT.sha256_bytes(value)


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
) -> tuple[str, str, str, str]:
    version = request["fixedVersion"]
    metadata_path = f".lit/security-releases/{version}.json"
    CONTRACT.validate_immutable_marker_changes(paths, version)
    if any(path.startswith(".github/") or path in FORBIDDEN_PATHS for _path_status, path in paths):
        fail("candidate diff modifies Security controls or workflow policy")
    fragments = [
        path for status, path in paths if status == "A" and re.fullmatch(r"changelogs/fragments/[^/]+\.ya?ml", path)
    ]
    if len(fragments) != 1:
        fail("candidate must add exactly one Security changelog fragment")
    fragment_raw = git_bytes(root, "show", f"{request['candidateHeadSha']}:{fragments[0]}")
    CONTRACT.validate_security_fragment(fragment_raw, "Security changelog fragment")
    fragment_digest = sha256(fragment_raw)
    product_paths = [path for _path_status, path in paths if path not in {metadata_path, fragments[0]}]
    if not product_paths:
        fail("candidate must contain an evidence-bound product change")
    unsupported_paths = [
        path
        for path in product_paths
        if path in FORBIDDEN_SUPPORTING_PATHS
        or (path not in SUPPORTING_PRODUCT_PATHS and not path.startswith(PRODUCT_PATH_PREFIXES))
    ]
    if unsupported_paths:
        fail("candidate modifies paths outside the Security product allowlist: " + ", ".join(sorted(unsupported_paths)))
    if not any(path.startswith(RUNTIME_PRODUCT_PREFIXES) for path in product_paths):
        fail("candidate must contain a runtime product change")

    metadata_raw = git_bytes(root, "show", f"{request['candidateHeadSha']}:{metadata_path}")
    metadata_digest = sha256(metadata_raw)
    if metadata_digest != request["metadataSha256"]:
        fail("Security metadata digest does not match the intake request")
    metadata = load_json_bytes(metadata_raw, "Security release metadata")
    profile_id = request["acceptanceProfile"]
    CONTRACT.validate_metadata_payload(
        metadata,
        expected_evidence_id=request["evidenceId"],
        expected_version=version,
        expected_profile=profile_id,
        checked_at=now,
    )
    CONTRACT.validate_request_metadata_binding(request, metadata)
    profiles = show_json(
        root,
        request["baseSha"],
        ".lit/security-release-profiles.json",
        "protected-main acceptance-profile registry",
    )
    CONTRACT.validate_profile_registry(profiles, profile_id)

    galaxy = git_text(root, "show", f"{request['baseSha']}:galaxy.yml")
    match = re.search(r"(?m)^version:\s*[\"']?([^\s\"']+)", galaxy)
    if match is None or SEMVER.fullmatch(match.group(1)) is None:
        fail("protected-main galaxy.yml has no stable version")
    current = tuple(int(part) for part in match.group(1).split("."))
    fixed = tuple(int(part) for part in version.split("."))
    if fixed != (current[0], current[1], current[2] + 1):
        fail("Security intake fixedVersion must be the next patch after protected main")
    return metadata_path, profile_id, fragments[0], fragment_digest


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
    live_candidate = git_text(root, "rev-parse", f"refs/remotes/origin/{request['candidateRef']}").strip()
    if (
        subprocess.run(  # noqa: S603 -- commit identities are exact validated lowercase SHAs.
            [
                git_binary(),
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
        subprocess.run(  # noqa: S603 -- commit identities are exact validated lowercase SHAs.
            [
                git_binary(),
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

    patch = canonical_diff(root, request["candidateBaseSha"], request["candidateHeadSha"])
    actual_digest = sha256(patch)
    if actual_digest != request["candidateDiffSha256"]:
        fail("candidate diff digest does not match the approved intake")
    paths = changed_paths(root, request["candidateBaseSha"], request["candidateHeadSha"])
    reject_special_modes(root, request["candidateBaseSha"], request["candidateHeadSha"])
    metadata_path, profile_id, fragment_path, fragment_digest = validate_metadata(root, request, paths, now)
    result = {
        "schemaVersion": CONTRACT.INTAKE_RESULT_SCHEMA_VERSION,
        "chainId": request["chainId"],
        "branch": f"security-release/{request['evidenceId']}",
        "baseSha": request["baseSha"],
        "candidateBaseSha": request["candidateBaseSha"],
        "candidateHeadSha": request["candidateHeadSha"],
        "candidateDiffSha256": actual_digest,
        "evidenceId": request["evidenceId"],
        "fixedVersion": request["fixedVersion"],
        "metadataPath": metadata_path,
        "metadataSha256": request["metadataSha256"],
        "acceptanceProfile": profile_id,
        "changelogFragmentPath": fragment_path,
        "changelogFragmentSha256": fragment_digest,
        "changedPaths": sorted(path for _path_status, path in paths),
        "humanActions": 0,
    }
    CONTRACT.validate_intake_result(request, result)
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
    parser.add_argument("--output-intake-receipt", type=Path)
    parser.add_argument("--workflow-run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--workflow-attempt", default=os.environ.get("GITHUB_RUN_ATTEMPT", ""))
    parser.add_argument("--workflow-ref", default=os.environ.get("GITHUB_WORKFLOW_REF", ""))
    parser.add_argument("--workflow-event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    parser.add_argument("--workflow-actor", default=os.environ.get("GITHUB_ACTOR", ""))
    parser.add_argument(
        "--workflow-triggering-actor",
        default=os.environ.get("GITHUB_TRIGGERING_ACTOR", ""),
    )
    parser.add_argument("--observed-app-slug", default="")
    parser.add_argument("--observed-app-installation-id", default="")
    parser.add_argument("--observed-app-login", default="")
    parser.add_argument("--observed-app-account-id", default="")
    parser.add_argument("--observed-app-permissions", type=Path)
    parser.add_argument("--observed-app-repository", action="append", default=[])
    args = parser.parse_args()
    try:
        now = timestamp(args.now, "--now") if args.now else datetime.now(UTC)
        request = validate_request(
            load_canonical_request(args.request),
            require_string(args.repository, "--repository"),
            now,
        )
        patch, result = verify_repository(args.root.resolve(), request, now)
        serialized = CONTRACT.canonical_document_bytes(result)
        if args.output_patch:
            write_exclusive(args.output_patch, patch)
        if args.output_json:
            write_exclusive(args.output_json, serialized)
        if args.output_intake_receipt:
            if args.observed_app_permissions is None:
                fail("--observed-app-permissions is required for an intake receipt")
            observed_automation = {
                "slug": args.observed_app_slug,
                "installationId": args.observed_app_installation_id,
                "login": args.observed_app_login,
                "accountId": args.observed_app_account_id,
                "type": "Bot",
                "selectedRepositories": sorted(args.observed_app_repository),
                "permissions": load_canonical_document(
                    args.observed_app_permissions,
                    "observed App permissions",
                ),
            }
            receipt = CONTRACT.build_intake_receipt(
                request,
                result,
                checked_at=now,
                workflow_run_id=args.workflow_run_id,
                workflow_attempt=args.workflow_attempt,
                workflow_ref=args.workflow_ref,
                workflow_event=args.workflow_event,
                workflow_actor=args.workflow_actor,
                workflow_triggering_actor=args.workflow_triggering_actor,
                observed_automation=observed_automation,
            )
            write_exclusive(
                args.output_intake_receipt,
                CONTRACT.canonical_document_bytes(receipt),
            )
        print(serialized.decode("utf-8"), end="")
    except (IntakeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
