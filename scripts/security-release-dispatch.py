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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--now", default="")
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-request-json", type=Path)
    args = parser.parse_args()
    try:
        now = INTAKE.timestamp(args.now, "--now") if args.now else datetime.now(UTC)
        envelope = build_envelope(
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
