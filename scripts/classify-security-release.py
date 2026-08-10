"""Classify only evidence-bound MLX-90 Security release events."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent))

import security_release_contract as CONTRACT  # noqa: E402

SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
SHA = re.compile(r"^[0-9a-f]{40}$")
EVIDENCE_ID = re.compile(r"^MLX90-[A-Z0-9][A-Z0-9._-]{2,127}$")
METADATA_PATH = re.compile(r"^\.lit/security-releases/([0-9]+\.[0-9]+\.[0-9]+)\.json$")
RELEASE_BRANCH = re.compile(r"^release/v([0-9]+\.[0-9]+\.[0-9]+)$")
SECURITY_BRANCH = re.compile(r"^security-release/(MLX90-[A-Z0-9][A-Z0-9._-]{2,127})$")
PREPARE_TITLE = re.compile(r"(?:^|\n)chore\(release\): prepare v([0-9]+\.[0-9]+\.[0-9]+)(?:$|\n)")


class ClassificationError(ValueError):
    """Raised when an event claims Security semantics without valid evidence."""


@dataclass(frozen=True)
class Classification:
    security_release: bool
    evidence_id: str = ""
    version: str = ""


def fail(message: str) -> NoReturn:
    raise ClassificationError(message)


def git_binary() -> str:
    executable = shutil.which("git")
    if executable is None:
        fail("git executable is unavailable")
    return executable


def timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        fail(f"{field} must be a non-empty RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClassificationError(f"{field} must be RFC3339") from exc
    if parsed.tzinfo is None:
        fail(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def is_regular_file_beneath(root: Path, relative: Path) -> bool:
    """Reject symlinks at every repository-relative path component."""
    current = root
    if current.is_symlink() or not current.is_dir():
        return False
    for component in relative.parts:
        if component in {"", ".", ".."}:
            return False
        current /= component
        if current.is_symlink():
            return False
    return current.is_file()


def classify_version(
    root: Path,
    version: str,
    expected_evidence_id: str,
    checked_at: datetime,
    binding_root: Path | None = None,
) -> Classification:
    if SEMVER.fullmatch(version) is None:
        fail("Security release version is not stable SemVer")
    metadata_path = root / ".lit" / "security-releases" / f"{version}.json"
    intake_path = root / ".lit" / "security-release-intakes" / f"{version}.json"
    metadata_exists = metadata_path.exists() or metadata_path.is_symlink()
    intake_exists = intake_path.exists() or intake_path.is_symlink()
    if metadata_exists != intake_exists:
        fail("partial Security marker: metadata and intake receipt must exist together")
    if not metadata_exists:
        if expected_evidence_id:
            fail("claimed Security release binding is missing")
        return Classification(False)
    source = root
    if binding_root is not None:
        source = binding_root
        for relative in (
            Path(".lit/security-releases") / f"{version}.json",
            Path(".lit/security-release-intakes") / f"{version}.json",
            Path(".lit/security-release-profiles.json"),
        ):
            current = root / relative
            bound = source / relative
            if (
                not is_regular_file_beneath(root, relative)
                or not is_regular_file_beneath(source, relative)
                or current.read_bytes() != bound.read_bytes()
            ):
                fail(f"released Security binding differs from its pre-consumption base: {relative}")
    try:
        binding = CONTRACT.load_security_binding(source, version, checked_at=checked_at)
    except CONTRACT.ContractError as exc:
        raise ClassificationError(str(exc)) from exc
    if binding is None:
        fail("claimed Security release binding is unavailable")
    evidence_id = binding["evidence_id"]
    if expected_evidence_id and evidence_id != expected_evidence_id:
        fail("Security release evidenceId does not match the event binding")
    return Classification(True, evidence_id, version)


def changed_preparation_version(root: Path, base_sha: str, head_sha: str) -> str:
    for label, value in (("base SHA", base_sha), ("head SHA", head_sha)):
        if SHA.fullmatch(value) is None:
            fail(f"{label} is invalid")
    result = subprocess.run(  # noqa: S603
        [
            git_binary(),
            "diff",
            "--name-only",
            "--no-renames",
            base_sha,
            head_sha,
            "--",
            "changelogs/release-preparation.json",
        ],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    paths = [line for line in result.stdout.splitlines() if line]
    if not paths:
        return ""
    if paths != ["changelogs/release-preparation.json"]:
        fail("release preparation change is ambiguous")
    try:
        receipt_path = root / "changelogs/release-preparation.json"
        receipt = CONTRACT.load_json_file(
            receipt_path,
            "release preparation receipt",
        )
    except CONTRACT.ContractError as exc:
        raise ClassificationError(str(exc)) from exc
    if receipt_path.read_bytes() != CONTRACT.canonical_document_bytes(receipt):
        fail("release preparation receipt is not canonical JSON")
    version = receipt.get("next_version")
    if not isinstance(version, str) or SEMVER.fullmatch(version) is None:
        fail("release preparation receipt has no stable next version")
    return version


def changed_security_versions(root: Path, base_sha: str, head_sha: str) -> list[str]:
    for label, value in (("base SHA", base_sha), ("head SHA", head_sha)):
        if SHA.fullmatch(value) is None:
            fail(f"{label} is invalid")
    result = subprocess.run(  # noqa: S603
        [
            git_binary(),
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
    requested_binding_root = getattr(args, "binding_root", None)
    binding_root = requested_binding_root
    if args.event_kind == "version":
        if not args.version:
            if args.evidence_id:
                fail("Security evidenceId requires an exact version")
            return Classification(False)
        return classify_version(
            root,
            args.version,
            args.evidence_id,
            checked_at,
            binding_root,
        )

    if args.event_kind == "pull_request":
        if args.base_ref != "main":
            return Classification(False)
        release = RELEASE_BRANCH.fullmatch(args.head_ref)
        if release is not None:
            return classify_version(
                root,
                release.group(1),
                args.evidence_id,
                checked_at,
                binding_root,
            )
        security = SECURITY_BRANCH.fullmatch(args.head_ref)
        if security is None:
            return Classification(False)
        versions = changed_security_versions(root, args.base_sha, args.head_sha)
        if len(versions) != 1:
            fail("Security release branch must change exactly one metadata file")
        # The intake PR creates the binding; its signed App receipt verifies the candidate diff.
        return classify_version(
            root,
            versions[0],
            security.group(1),
            checked_at,
            None,
        )

    if args.event_kind == "push":
        if args.ref != "refs/heads/main":
            return Classification(False)
        versions = changed_security_versions(root, args.base_sha, args.head_sha)
        if versions:
            return classify_version(
                root,
                versions[0],
                args.evidence_id,
                checked_at,
                binding_root,
            )
        prepared_version = changed_preparation_version(root, args.base_sha, args.head_sha)
        if prepared_version:
            return classify_version(
                root,
                prepared_version,
                args.evidence_id,
                checked_at,
                binding_root,
            )
        prepared = PREPARE_TITLE.search(args.commit_message)
        if prepared is not None:
            return classify_version(
                root,
                prepared.group(1),
                args.evidence_id,
                checked_at,
                binding_root,
            )
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
    parser.add_argument("--binding-root", type=Path)
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT", ""))
    args = parser.parse_args()
    checked_at = timestamp(args.checked_at, "--checked-at") if args.checked_at else datetime.now(UTC)
    try:
        result = classify(args, Path.cwd(), checked_at)
    except (ClassificationError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    write_output(result, args.github_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
