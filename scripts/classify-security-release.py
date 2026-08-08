#!/usr/bin/env python3
"""Classify only evidence-bound MLX-90 Security release events."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA = re.compile(r"^[0-9a-f]{40}$")
EVIDENCE_ID = re.compile(r"^MLX90-[A-Z0-9][A-Z0-9._-]{2,127}$")
SECURITY_ID = re.compile(r"^(?:CVE-[0-9]{4}-[0-9]{4,}|GHSA-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4}-[23456789cfghjmpqrvwx]{4})$")
PROFILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{2,127}$")
METADATA_PATH = re.compile(r"^\.lit/security-releases/([0-9]+\.[0-9]+\.[0-9]+)\.json$")
RELEASE_BRANCH = re.compile(r"^release/v([0-9]+\.[0-9]+\.[0-9]+)$")
SECURITY_BRANCH = re.compile(r"^security-release/(MLX90-[A-Z0-9][A-Z0-9._-]{2,127})$")
PREPARE_TITLE = re.compile(r"(?:^|\n)chore\(release\): prepare v([0-9]+\.[0-9]+\.[0-9]+)(?:$|\n)")
PRODUCER = "lightning-it/ansible-collection-supplementary"
CONSUMER = "lightning-it/container-ee-wunder-ansible-ubi9"
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


class ClassificationError(ValueError):
    """Raised when an event claims Security semantics without valid evidence."""


@dataclass(frozen=True)
class Classification:
    security_release: bool
    evidence_id: str = ""
    version: str = ""


def fail(message: str) -> None:
    raise ClassificationError(message)


def timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        fail(f"{field} must be a non-empty RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClassificationError(f"{field} must be RFC3339") from exc
    if parsed.tzinfo is None:
        fail(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        fail(f"{label} must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClassificationError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        fail(f"{label} must be a JSON object")
    return payload


def exact_keys(payload: dict[str, Any], expected: set[str], label: str) -> None:
    if set(payload) != expected:
        fail(f"{label} has unexpected or missing fields")


def classify_version(
    root: Path,
    version: str,
    expected_evidence_id: str,
    checked_at: datetime,
) -> Classification:
    if SEMVER.fullmatch(version) is None:
        fail("Security release version is not stable SemVer")
    metadata_path = root / ".lit" / "security-releases" / f"{version}.json"
    if not metadata_path.exists():
        if expected_evidence_id:
            fail("claimed Security release metadata is missing")
        return Classification(False)

    metadata = load_json(metadata_path, "Security release metadata")
    exact_keys(metadata, METADATA_KEYS, "Security release metadata")
    if metadata["schemaVersion"] != 1:
        fail("Security release metadata schemaVersion must be 1")
    evidence_id = metadata["evidenceId"]
    if not isinstance(evidence_id, str) or EVIDENCE_ID.fullmatch(evidence_id) is None:
        fail("Security release evidenceId is invalid")
    if expected_evidence_id and evidence_id != expected_evidence_id:
        fail("Security release evidenceId does not match the event binding")
    if metadata["fixedVersion"] != version:
        fail("Security release fixedVersion does not match its path")
    affected = metadata["affectedVersion"]
    if not isinstance(affected, str) or SEMVER.fullmatch(affected) is None or affected == version:
        fail("Security release affectedVersion is invalid")
    identifiers = metadata["securityIdentifiers"]
    if (
        not isinstance(identifiers, list)
        or not identifiers
        or len(identifiers) != len(set(identifiers))
        or any(not isinstance(item, str) or SECURITY_ID.fullmatch(item) is None for item in identifiers)
    ):
        fail("Security release identifiers are invalid")
    if metadata["consumers"] != [CONSUMER]:
        fail("Security release consumer allowlist is invalid")
    profile_id = metadata["acceptanceProfile"]
    if not isinstance(profile_id, str) or PROFILE_ID.fullmatch(profile_id) is None:
        fail("Security release acceptanceProfile is invalid")

    profiles = load_json(
        root / ".lit" / "security-release-profiles.json",
        "Security release profile registry",
    )
    exact_keys(profiles, {"schemaVersion", "profiles"}, "Security release profile registry")
    if profiles["schemaVersion"] != 1 or not isinstance(profiles["profiles"], dict):
        fail("Security release profile registry is unsupported")
    profile = profiles["profiles"].get(profile_id)
    if not isinstance(profile, dict) or profile.get("releaseEligible") is not True:
        fail("Security release acceptanceProfile is not release eligible")

    validity = metadata["validity"]
    if not isinstance(validity, dict):
        fail("Security release validity must be an object")
    exact_keys(validity, VALIDITY_KEYS, "Security release validity")
    if validity["revoked"] is not False:
        fail("Security release metadata is revoked")
    created_at = timestamp(metadata["createdAt"], "createdAt")
    not_before = timestamp(validity["notBefore"], "validity.notBefore")
    expires_at = timestamp(validity["expiresAt"], "validity.expiresAt")
    if not_before > created_at or created_at >= expires_at:
        fail("Security release createdAt is outside its validity interval")
    if checked_at < not_before or checked_at >= expires_at:
        fail("Security release metadata is not currently valid")
    return Classification(True, evidence_id, version)


def changed_security_versions(root: Path, base_sha: str, head_sha: str) -> list[str]:
    for label, value in (("base SHA", base_sha), ("head SHA", head_sha)):
        if SHA.fullmatch(value) is None:
            fail(f"{label} is invalid")
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=AM",
            base_sha,
            head_sha,
            "--",
            ".lit/security-releases",
        ],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    versions: list[str] = []
    for raw in result.stdout.splitlines():
        match = METADATA_PATH.fullmatch(raw)
        if match is None:
            fail("Security release metadata change has an invalid path")
        versions.append(match.group(1))
    if len(versions) > 1 or len(versions) != len(set(versions)):
        fail("an event may bind at most one Security release metadata file")
    return versions


def classify(args: argparse.Namespace, root: Path, checked_at: datetime) -> Classification:
    if args.event_kind == "version":
        if not args.version:
            if args.evidence_id:
                fail("Security evidenceId requires an exact version")
            return Classification(False)
        return classify_version(root, args.version, args.evidence_id, checked_at)

    if args.event_kind == "pull_request":
        if args.base_ref != "main":
            return Classification(False)
        release = RELEASE_BRANCH.fullmatch(args.head_ref)
        if release is not None:
            return classify_version(root, release.group(1), args.evidence_id, checked_at)
        security = SECURITY_BRANCH.fullmatch(args.head_ref)
        if security is None:
            return Classification(False)
        versions = changed_security_versions(root, args.base_sha, args.head_sha)
        if len(versions) != 1:
            fail("Security release branch must change exactly one metadata file")
        return classify_version(root, versions[0], security.group(1), checked_at)

    if args.event_kind == "push":
        if args.ref != "refs/heads/main":
            return Classification(False)
        versions = changed_security_versions(root, args.base_sha, args.head_sha)
        if versions:
            return classify_version(root, versions[0], args.evidence_id, checked_at)
        prepared = PREPARE_TITLE.search(args.commit_message)
        if prepared is not None:
            return classify_version(root, prepared.group(1), args.evidence_id, checked_at)
        return Classification(False)

    fail("unsupported event kind")


def write_output(classification: Classification, path: str) -> None:
    fields = {
        "security_release": str(classification.security_release).lower(),
        "security_evidence_id": classification.evidence_id,
        "security_version": classification.version,
    }
    if path:
        output = Path(path)
        with output.open("a", encoding="utf-8") as stream:
            for key, value in fields.items():
                stream.write(f"{key}={value}\n")
    print(json.dumps(fields, sort_keys=True, separators=(",", ":")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-kind", choices=("pull_request", "push", "version"), required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", default="")
    parser.add_argument("--base-ref", default="")
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--ref", default="")
    parser.add_argument("--commit-message", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--evidence-id", default="")
    parser.add_argument("--checked-at", default="")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = parser.parse_args()
    checked_at = (
        timestamp(args.checked_at, "--checked-at")
        if args.checked_at
        else datetime.now(timezone.utc)
    )
    try:
        result = classify(args, Path.cwd(), checked_at)
    except (ClassificationError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    write_output(result, args.github_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
