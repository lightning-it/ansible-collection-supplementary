"""Build an exact MLX-90 Security dispatch request from protected Git refs."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

METADATA_PATH = re.compile(r"^\.lit/security-releases/([^/]+)\.json$")


def load_intake_module() -> ModuleType:
    path = Path(__file__).with_name("security-release-intake.py")
    spec = importlib.util.spec_from_file_location("mlx90_security_intake", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Security intake module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INTAKE = load_intake_module()


def build_envelope(
    root: Path,
    repository: str,
    base_sha: str,
    head_sha: str,
    now: datetime,
) -> dict[str, Any]:
    if INTAKE.REPOSITORY.fullmatch(repository) is None:
        INTAKE.fail("dispatch repository is invalid")
    for label, value in (("baseSha", base_sha), ("candidateHeadSha", head_sha)):
        if INTAKE.SHA.fullmatch(value) is None:
            INTAKE.fail(f"{label} must be a full lowercase commit SHA")

    live_main = INTAKE.git_text(root, "rev-parse", "refs/remotes/origin/main").strip()
    live_develop = INTAKE.git_text(root, "rev-parse", "refs/remotes/origin/develop").strip()
    if live_main != base_sha or live_develop != head_sha:
        INTAKE.fail("dispatch source refs changed after protected CI")

    paths = INTAKE.changed_paths(root, base_sha, head_sha)
    security_metadata = [(status, path) for status, path in paths if path.startswith(".lit/security-releases/")]
    if not security_metadata:
        if any(path.startswith(".lit/security-release-intakes/") for _status, path in paths):
            INTAKE.fail("partial Security marker: candidate changes an App-owned intake receipt without metadata")
        return {"dispatch": False}
    if len(security_metadata) != 1 or security_metadata[0][0] != "A":
        INTAKE.fail("dispatch range must add exactly one immutable Security metadata file")
    match = METADATA_PATH.fullmatch(security_metadata[0][1])
    if match is None or INTAKE.SEMVER.fullmatch(match.group(1)) is None:
        INTAKE.fail("dispatch Security metadata path is invalid")
    assert match is not None
    fixed_version = match.group(1)
    metadata_raw = INTAKE.git_bytes(root, "show", f"{head_sha}:{security_metadata[0][1]}")
    metadata = INTAKE.load_json_bytes(metadata_raw, "Security release metadata")
    issued_at = metadata.get("createdAt")
    validity = metadata.get("validity")
    expires_at = validity.get("expiresAt") if isinstance(validity, dict) else None
    acceptance_profile = metadata.get("acceptanceProfile")
    if not isinstance(issued_at, str) or not isinstance(expires_at, str):
        INTAKE.fail("Security metadata cannot bind the dispatch validity interval")
    if not isinstance(acceptance_profile, str):
        INTAKE.fail("Security metadata cannot bind the acceptance profile")

    candidate_diff_sha256 = INTAKE.sha256(INTAKE.canonical_diff(root, base_sha, head_sha))
    metadata_sha256 = INTAKE.sha256(metadata_raw)
    chain_id = INTAKE.CONTRACT.compute_chain_id(
        repository=repository,
        repository_id=INTAKE.CONTRACT.PRODUCER_REPOSITORY_ID,
        base_sha=base_sha,
        candidate_head_sha=head_sha,
        candidate_diff_sha256=candidate_diff_sha256,
        evidence_id=str(metadata.get("evidenceId", "")),
        fixed_version=fixed_version,
        acceptance_profile=acceptance_profile,
    )

    request = {
        "schemaVersion": INTAKE.CONTRACT.INTAKE_REQUEST_SCHEMA_VERSION,
        "event": "mlx90-security-release",
        "repository": repository,
        "repositoryId": INTAKE.CONTRACT.PRODUCER_REPOSITORY_ID,
        "baseSha": base_sha,
        "candidateRef": "develop",
        "candidateBaseSha": base_sha,
        "candidateHeadSha": head_sha,
        "candidateDiffSha256": candidate_diff_sha256,
        "evidenceId": metadata.get("evidenceId"),
        "fixedVersion": fixed_version,
        "acceptanceProfile": acceptance_profile,
        "metadataSha256": metadata_sha256,
        "chainId": chain_id,
        "issuedAt": issued_at,
        "expiresAt": expires_at,
        "humanActions": 0,
    }
    validated = INTAKE.validate_request(request, repository, now)
    _patch, result = INTAKE.verify_repository(root, validated, now)
    if (
        result["evidenceId"] != request["evidenceId"]
        or result["fixedVersion"] != fixed_version
        or result["candidateHeadSha"] != head_sha
        or result["chainId"] != chain_id
        or result["metadataSha256"] != metadata_sha256
        or result["humanActions"] != 0
    ):
        INTAKE.fail("verified Security intake differs from the dispatch request")
    return {"dispatch": True, "request": request}


def build_recovery_envelope(
    root: Path,
    repository: str,
    base_sha: str,
    head_sha: str,
    now: datetime,
) -> dict[str, Any]:
    """Build only the single approved existing-marker recovery request."""

    if INTAKE.REPOSITORY.fullmatch(repository) is None:
        INTAKE.fail("recovery repository is invalid")
    for label, value in (("baseSha", base_sha), ("headSha", head_sha)):
        if INTAKE.SHA.fullmatch(value) is None:
            INTAKE.fail(f"{label} must be a full lowercase commit SHA")
    live_main = INTAKE.git_text(root, "rev-parse", "refs/remotes/origin/main").strip()
    live_develop = INTAKE.git_text(root, "rev-parse", "refs/remotes/origin/develop").strip()
    if live_main != base_sha or live_develop != head_sha:
        INTAKE.fail("recovery source refs changed after protected CI")

    receipt_path = f".lit/security-release-intakes/{INTAKE.CONTRACT.RECOVERY_FIXED_VERSION}.json"
    if INTAKE.git_text(root, "ls-tree", "--name-only", base_sha, "--", receipt_path).strip():
        return {"dispatch": False}
    metadata_path = f".lit/security-releases/{INTAKE.CONTRACT.RECOVERY_FIXED_VERSION}.json"
    metadata_raw = INTAKE.git_bytes(
        root,
        "show",
        f"{base_sha}:{metadata_path}",
    )
    if len(metadata_raw) > INTAKE.CONTRACT.MAX_JSON_BYTES:
        INTAKE.fail("Security recovery metadata exceeds the size limit")
    if INTAKE.sha256(metadata_raw) != INTAKE.CONTRACT.RECOVERY_METADATA_SHA256:
        INTAKE.fail("Security recovery metadata digest differs from the approved binding")
    metadata = INTAKE.load_json_bytes(metadata_raw, "Security recovery metadata")

    request = {
        "schemaVersion": INTAKE.CONTRACT.INTAKE_REQUEST_SCHEMA_VERSION,
        "event": INTAKE.CONTRACT.RECOVERY_EVENT,
        "repository": repository,
        "repositoryId": INTAKE.CONTRACT.PRODUCER_REPOSITORY_ID,
        "baseSha": base_sha,
        "candidateRef": "develop",
        "candidateBaseSha": INTAKE.CONTRACT.RECOVERY_CANDIDATE_BASE_SHA,
        "candidateHeadSha": INTAKE.CONTRACT.RECOVERY_CANDIDATE_HEAD_SHA,
        "candidateDiffSha256": INTAKE.CONTRACT.RECOVERY_CANDIDATE_DIFF_SHA256,
        "evidenceId": INTAKE.CONTRACT.RECOVERY_EVIDENCE_ID,
        "fixedVersion": INTAKE.CONTRACT.RECOVERY_FIXED_VERSION,
        "acceptanceProfile": INTAKE.CONTRACT.RECOVERY_ACCEPTANCE_PROFILE,
        "metadataSha256": INTAKE.CONTRACT.RECOVERY_METADATA_SHA256,
        "chainId": INTAKE.CONTRACT.compute_chain_id(
            repository=repository,
            repository_id=INTAKE.CONTRACT.PRODUCER_REPOSITORY_ID,
            base_sha=base_sha,
            candidate_head_sha=INTAKE.CONTRACT.RECOVERY_CANDIDATE_HEAD_SHA,
            candidate_diff_sha256=INTAKE.CONTRACT.RECOVERY_CANDIDATE_DIFF_SHA256,
            evidence_id=INTAKE.CONTRACT.RECOVERY_EVIDENCE_ID,
            fixed_version=INTAKE.CONTRACT.RECOVERY_FIXED_VERSION,
            acceptance_profile=INTAKE.CONTRACT.RECOVERY_ACCEPTANCE_PROFILE,
        ),
        "issuedAt": metadata.get("createdAt"),
        "expiresAt": metadata.get("validity", {}).get("expiresAt")
        if isinstance(metadata.get("validity"), dict)
        else None,
        "humanActions": 0,
    }
    validated = INTAKE.validate_request(request, repository, now)
    _patch, result = INTAKE.verify_repository(root, validated, now)
    if (
        result["baseSha"] != base_sha
        or result["evidenceId"] != INTAKE.CONTRACT.RECOVERY_EVIDENCE_ID
        or result["fixedVersion"] != INTAKE.CONTRACT.RECOVERY_FIXED_VERSION
        or result["candidateDiffSha256"] != INTAKE.CONTRACT.RECOVERY_CANDIDATE_DIFF_SHA256
        or result["humanActions"] != 0
    ):
        INTAKE.fail("verified Security recovery differs from the approved request")
    return {"dispatch": True, "request": request}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--now", default="")
    parser.add_argument("--recover-existing-marker", action="store_true")
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-request-json", type=Path)
    args = parser.parse_args()
    try:
        now = INTAKE.timestamp(args.now, "--now") if args.now else datetime.now(UTC)
        builder = build_recovery_envelope if args.recover_existing_marker else build_envelope
        envelope = builder(
            args.root.resolve(),
            INTAKE.require_string(args.repository, "--repository"),
            INTAKE.require_string(args.base_sha, "--base-sha"),
            INTAKE.require_string(args.head_sha, "--head-sha"),
            now,
        )
        serialized = INTAKE.CONTRACT.canonical_document_bytes(envelope)
        INTAKE.write_exclusive(args.output_json, serialized)
        if args.output_request_json:
            request = envelope.get("request")
            if envelope.get("dispatch") is not True or not isinstance(request, dict):
                INTAKE.fail("canonical Security request output requires dispatch=true")
            INTAKE.write_exclusive(
                args.output_request_json,
                INTAKE.CONTRACT.canonical_document_bytes(request),
            )
        print(serialized.decode("utf-8"), end="")
    except (INTAKE.IntakeError, OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
