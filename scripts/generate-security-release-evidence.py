"""Generate or verify deterministic MLX-90 producer evidence.

Security classification fields are read only from reviewed metadata committed at
the exact release SHA. Runtime arguments identify the already verified release
materials; they cannot supply Security IDs, consumers, validity, or profiles.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PRODUCER = "lightning-it/ansible-collection-supplementary"
CONSUMER = "lightning-it/container-ee-wunder-ansible-ubi9"
COLLECTION = "lit.supplementary"

SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
EVIDENCE_ID = re.compile(r"^[A-Z0-9][A-Z0-9._-]{2,127}$")
SECURITY_ID = re.compile(
    r"^(?:CVE-[0-9]{4}-[0-9]{4,}|"
    r"GHSA-[23456789cfghjmpqrvwx]{4}(?:-[23456789cfghjmpqrvwx]{4}){2}|"
    r"LIT-SEC-[A-Z0-9._-]+)$"
)
PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9._/-]+$")
CANONICAL_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")

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


def fail(message: str) -> None:
    raise ValueError(message)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def has_symlink_component(path: Path) -> bool:
    # Inspect the lexical path rather than resolving it so a symlink cannot
    # disappear from the path being checked. The only accepted platform alias
    # is macOS /var -> /private/var; every other component must not be a
    # symlink.
    absolute = path if path.is_absolute() else Path.cwd() / path
    if ".." in absolute.parts:
        return True
    anchor = Path(absolute.anchor)
    current = anchor
    for component in absolute.parts[1:]:
        current /= component
        if current.is_symlink():
            if current != Path("/var"):
                return True
            try:
                if current.resolve(strict=True) != Path("/private/var"):
                    return True
            except OSError:
                return True
    return False


def require_regular_file(path: Path, label: str) -> None:
    if has_symlink_component(path) or not path.is_file():
        fail(f"{label} must be a regular non-symlink file: {path}")


def load_json(path: Path, label: str) -> dict[str, Any]:
    require_regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def require_exact(value: dict[str, Any], keys: set[str], label: str) -> None:
    missing = keys - value.keys()
    unknown = value.keys() - keys
    if missing:
        fail(f"{label} is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        fail(f"{label} has unknown fields: {', '.join(sorted(unknown))}")


def require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        fail(f"{label} must be a non-empty trimmed string")
    return value


def timestamp(value: object, label: str) -> datetime:
    text = require_string(value, label)
    if CANONICAL_TIME.fullmatch(text) is None:
        fail(f"{label} must be a canonical UTC RFC3339 timestamp")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid timestamp") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def load_profiles(path: Path, profile_id: str) -> None:
    registry = load_json(path, "security release profile registry")
    require_exact(registry, {"schemaVersion", "profiles"}, "security release profile registry")
    if registry["schemaVersion"] != 1 or not isinstance(registry["profiles"], dict):
        fail("security release profile registry is unsupported")
    profile = registry["profiles"].get(profile_id)
    if not isinstance(profile, dict):
        fail("acceptance profile is not in the fixed producer allowlist")
    require_exact(profile, {"releaseEligible", "description"}, f"acceptance profile {profile_id}")
    if profile["releaseEligible"] is not True:
        fail("acceptance profile is explicitly non-releaseable")
    require_string(profile["description"], f"acceptance profile {profile_id}.description")


def load_metadata(path: Path, profiles: Path, checked_at: datetime) -> dict[str, Any]:
    metadata = load_json(path, "security release metadata")
    require_exact(metadata, METADATA_KEYS, "security release metadata")
    if metadata["schemaVersion"] != 1:
        fail("security release metadata schemaVersion must be 1")

    evidence_id = require_string(metadata["evidenceId"], "evidenceId")
    if EVIDENCE_ID.fullmatch(evidence_id) is None:
        fail("evidenceId is invalid")
    identifiers = metadata["securityIdentifiers"]
    if (
        not isinstance(identifiers, list)
        or not identifiers
        or any(not isinstance(item, str) or SECURITY_ID.fullmatch(item) is None for item in identifiers)
        or len(identifiers) != len(set(identifiers))
    ):
        fail("securityIdentifiers must be a non-empty unique list of canonical Security IDs")
    affected = require_string(metadata["affectedVersion"], "affectedVersion")
    fixed = require_string(metadata["fixedVersion"], "fixedVersion")
    if SEMVER.fullmatch(affected) is None:
        fail("affectedVersion must be a stable semantic version")
    if SEMVER.fullmatch(fixed) is None:
        fail("fixedVersion must be a stable semantic version")
    if affected == fixed:
        fail("affectedVersion must differ from fixedVersion")
    if path.name != f"{fixed}.json" or path.parent.name != "security-releases" or path.parent.parent.name != ".lit":
        fail("security metadata path must be .lit/security-releases/<fixedVersion>.json")

    consumers = metadata["consumers"]
    if consumers != [CONSUMER]:
        fail(f"consumers must contain exactly the approved repository {CONSUMER}")
    profile_id = require_string(metadata["acceptanceProfile"], "acceptanceProfile")
    if PROFILE_ID.fullmatch(profile_id) is None:
        fail("acceptanceProfile is invalid")
    load_profiles(profiles, profile_id)

    validity = metadata["validity"]
    if not isinstance(validity, dict):
        fail("validity must be an object")
    require_exact(validity, VALIDITY_KEYS, "validity")
    created = timestamp(metadata["createdAt"], "createdAt")
    not_before = timestamp(validity["notBefore"], "validity.notBefore")
    expires_at = timestamp(validity["expiresAt"], "validity.expiresAt")
    if validity["revoked"] is not False:
        fail("security release metadata is revoked")
    if expires_at <= not_before:
        fail("security release validity interval is empty")
    if created < not_before or created >= expires_at:
        fail("createdAt is outside the security release validity interval")
    if checked_at < not_before or checked_at >= expires_at:
        fail("security release metadata is not currently valid")
    return metadata


def release_asset_url(version: str, name: str) -> str:
    return f"https://github.com/{PRODUCER}/releases/download/v{version}/{name}"


def file_ref(path: Path, version: str) -> dict[str, str]:
    return {"url": release_asset_url(version, path.name), "digest": sha256(path)}


def build_evidence(args: argparse.Namespace) -> dict[str, Any]:
    if SHA.fullmatch(args.source_sha) is None:
        fail("source SHA must be a full lowercase 40-character SHA")
    checked_at = timestamp(args.checked_at, "--checked-at") if args.checked_at else datetime.now(UTC)
    metadata = load_metadata(args.metadata, args.profiles, checked_at)
    version = metadata["fixedVersion"]

    expected_names = {
        "artifact": f"lit-supplementary-{version}.tar.gz",
        "signature": f"lit-supplementary-{version}.tar.gz.sigstore.json",
        "sbom": "sbom.cdx.json",
        "provenance": "provenance.json",
    }
    for label, expected_name in expected_names.items():
        path = getattr(args, label)
        require_regular_file(path, label)
        if path.name != expected_name:
            fail(f"{label} must be named {expected_name}")

    return {
        "apiVersion": "lit.security-release/v1",
        "kind": "SecurityReleaseEvidence",
        "metadata": {
            "id": metadata["evidenceId"],
            "createdAt": metadata["createdAt"],
        },
        "security": {
            "identifiers": sorted(metadata["securityIdentifiers"]),
            "affectedVersion": metadata["affectedVersion"],
            "fixedVersion": version,
        },
        "producer": {
            "repository": PRODUCER,
            "sourceSha": args.source_sha,
            "workflowRepository": PRODUCER,
            "workflowRef": args.source_sha,
        },
        "artifact": {
            "collection": COLLECTION,
            "version": version,
            "digest": sha256(args.artifact),
            "releaseUrl": f"https://github.com/{PRODUCER}/releases/tag/v{version}",
            "signature": file_ref(args.signature, version),
            "sbom": file_ref(args.sbom, version),
            "provenance": file_ref(args.provenance, version),
        },
        "consumers": [CONSUMER],
        "acceptance": {
            "profile": metadata["acceptanceProfile"],
            "expectedCollection": COLLECTION,
            "expectedVersion": version,
        },
        "validity": {
            "notBefore": metadata["validity"]["notBefore"],
            "expiresAt": metadata["validity"]["expiresAt"],
            "revoked": False,
        },
        "status": "approved",
    }


def serialize(evidence: dict[str, Any]) -> str:
    return json.dumps(evidence, indent=2, sort_keys=True) + "\n"


def write_exclusive(path: Path, value: str) -> None:
    if has_symlink_component(path):
        fail(f"evidence output must not contain symlink components: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if has_symlink_component(path):
        fail(f"evidence output must not contain symlink components: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o644)
    except FileExistsError as exc:
        raise ValueError(f"refusing to replace existing evidence output: {path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def add_material_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--signature", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--checked-at", help="canonical UTC test override; defaults to current UTC")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="create a new evidence file without replacement")
    add_material_arguments(generate)
    generate.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="recompute and verify an existing canonical evidence file")
    add_material_arguments(verify)
    verify.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()

    try:
        evidence = build_evidence(args)
        canonical = serialize(evidence)
        if args.command == "generate":
            write_exclusive(args.output, canonical)
            print(f"Generated approved security release evidence {evidence['metadata']['id']}.")
        else:
            require_regular_file(args.evidence, "security release evidence")
            if args.evidence.read_text(encoding="utf-8") != canonical:
                fail("security release evidence differs from authoritative metadata or verified release materials")
            print(f"Verified approved security release evidence {evidence['metadata']['id']}.")
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
