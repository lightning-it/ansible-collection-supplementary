"""Canonical data contract for the MLX-90 Security release chain.

This module contains only deterministic validation and serialization helpers.
Network calls and GitHub mutations deliberately stay in the calling workflows.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

PRODUCER_REPOSITORY = "lightning-it/ansible-collection-supplementary"
PRODUCER_REPOSITORY_ID = "1103407173"
CONSUMER_REPOSITORY = "lightning-it/container-ee-wunder-ansible-ubi9"
RELEASE_APP_SLUG = "lightning-it-release-automation"
RELEASE_APP_INSTALLATION_ID = "148019054"
RELEASE_APP_LOGIN = f"{RELEASE_APP_SLUG}[bot]"
RELEASE_APP_ACCOUNT_ID = "307565056"
RELEASE_APP_EMAIL = f"{RELEASE_APP_ACCOUNT_ID}+{RELEASE_APP_LOGIN}@users.noreply.github.com"
RELEASE_APP_SELECTED_REPOSITORIES = [
    "lightning-it/ansible-collection-supplementary",
    "lightning-it/container-ee-wunder-ansible-ubi9",
    "lightning-it/github-management-lit",
    "lightning-it/modulix-validation",
    "lightning-it/shared-assets-lit",
]
RELEASE_APP_PERMISSIONS = {
    "actions": "write",
    "checks": "read",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "write",
}
RELEASE_APP_IDENTITY = {
    "slug": RELEASE_APP_SLUG,
    "installationId": RELEASE_APP_INSTALLATION_ID,
    "login": RELEASE_APP_LOGIN,
    "accountId": RELEASE_APP_ACCOUNT_ID,
    "type": "Bot",
    "selectedRepositories": RELEASE_APP_SELECTED_REPOSITORIES,
    "permissions": RELEASE_APP_PERMISSIONS,
}

# One-time fail-closed recovery for the immutable 3.2.4 Security marker that
# reached protected main before the release App could mint its intake receipt.
# The ordinary zero-touch contract remains unchanged; only this exact historic
# source range and marker binding may use the recovery event.
RECOVERY_EVENT = "mlx90-security-release-recovery"
RECOVERY_APPROVED_MAIN_SHA = "990be99032ac3e6f407adbe6a8d3acccf8f6804b"
RECOVERY_CANDIDATE_BASE_SHA = "cde8e5544d8d787448ff456d51e08deb71c03880"
RECOVERY_CANDIDATE_HEAD_SHA = "3e1423dc19465d1233196905ef3f48fd6c04f2f1"
RECOVERY_CANDIDATE_DIFF_SHA256 = "sha256:bd72aa7a6a382ff1537e3223e65552af5ffa24588c09a5596f8e9130ba6a6f23"
RECOVERY_METADATA_SHA256 = "sha256:66d523781eaa82c496d6c8774f5af1e95bb2991f9d604fc1e29db837bb0dd38f"
RECOVERY_EVIDENCE_ID = "MLX90-KEYCLOAK-26.7.1-3.2.4"
RECOVERY_FIXED_VERSION = "3.2.4"
RECOVERY_ACCEPTANCE_PROFILE = "lit.supplementary/keycloak-26.7.1-security-v1"
RECOVERY_ISSUED_AT = "2026-08-08T22:48:24Z"
RECOVERY_EXPIRES_AT = "2026-09-07T22:48:24Z"
RECOVERY_FRAGMENT_PATH = "changelogs/fragments/keycloak-26.7.1-security.yml"
RECOVERY_FRAGMENT_SHA256 = "sha256:bfc051c66d0a8c016fd32bbe3a9f8b2882896a78e9dc121eb8837f3725a318f8"
RECOVERY_CONTROL_PATHS = frozenset(
    {
        ".github/workflows/security-release-dispatch.yml",
        ".github/workflows/security-release-intake.yml",
        "changelogs/fragments/security-intake-3.2.4-recovery.yml",
        "scripts/security-release-dispatch.py",
        "scripts/security-release-intake.py",
        "scripts/security_release_contract.py",
        "scripts/lit-push-ready.py",
        "tests/unit/test_push_ready_engine.py",
        "tests/unit/test_security_release_contract.py",
        "tests/unit/test_security_release_request_dispatch.py",
    }
)

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
CANONICAL_TIME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
METADATA_PATH = re.compile(r"^\.lit/security-releases/([0-9]+\.[0-9]+\.[0-9]+)\.json$")
INTAKE_PATH = re.compile(r"^\.lit/security-release-intakes/([0-9]+\.[0-9]+\.[0-9]+)\.json$")

INTAKE_REQUEST_SCHEMA_VERSION = 2
INTAKE_RECEIPT_SCHEMA_VERSION = 2
INTAKE_RESULT_SCHEMA_VERSION = 2
MAX_JSON_BYTES = 1024 * 1024
MAX_SECURITY_FRAGMENT_BYTES = 1024 * 1024
PROFILE_KEYS = {"description", "releaseEligible"}

REQUEST_KEYS = {
    "schemaVersion",
    "event",
    "repository",
    "repositoryId",
    "baseSha",
    "candidateRef",
    "candidateBaseSha",
    "candidateHeadSha",
    "candidateDiffSha256",
    "evidenceId",
    "fixedVersion",
    "acceptanceProfile",
    "metadataSha256",
    "chainId",
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
VERIFIED_KEYS = {
    "schemaVersion",
    "chainId",
    "branch",
    "baseSha",
    "candidateBaseSha",
    "candidateHeadSha",
    "candidateDiffSha256",
    "evidenceId",
    "fixedVersion",
    "metadataPath",
    "metadataSha256",
    "acceptanceProfile",
    "changelogFragmentPath",
    "changelogFragmentSha256",
    "changedPaths",
    "humanActions",
}
INTAKE_RECEIPT_KEYS = {
    "schemaVersion",
    "chainId",
    "request",
    "verified",
    "automation",
    "controller",
}
CONTROLLER_KEYS = {
    "path",
    "ref",
    "sourceSha",
    "runId",
    "runAttempt",
    "event",
    "gitRef",
    "actor",
    "triggeringActor",
}
CHAIN_BINDING_KEYS = {
    "repository",
    "repositoryId",
    "baseSha",
    "candidateHeadSha",
    "candidateDiffSha256",
    "evidenceId",
    "fixedVersion",
    "acceptanceProfile",
}


class ContractError(ValueError):
    """Raised when an MLX-90 contract cannot be proven exact."""


def fail(message: str) -> NoReturn:
    raise ContractError(message)


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    if len(raw) > MAX_JSON_BYTES:
        fail(f"{label} exceeds {MAX_JSON_BYTES} bytes")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=lambda value: fail(f"invalid JSON constant: {value}"),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def is_exact_int(value: object) -> bool:
    """Accept integers while rejecting bool, which is an int subclass."""
    return isinstance(value, int) and not isinstance(value, bool)


def read_bounded_regular_file(root: Path, relative_path: Path, label: str, limit: int) -> bytes:
    """Read a bounded regular file through non-symlink descendants of ``root``."""
    nofollow_flag = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if not is_exact_int(nofollow_flag) or not is_exact_int(directory_flag) or os.open not in os.supports_dir_fd:
        fail(f"{label} cannot prove non-symlink reads on this platform")
    parts = relative_path.parts
    if relative_path.is_absolute() or not parts or any(part in {"", ".", ".."} for part in parts):
        fail(f"{label} path must be a canonical relative path beneath the trusted root")
    file_flags = os.O_RDONLY | nofollow_flag
    directory_flags = file_flags | directory_flag
    if hasattr(os, "O_CLOEXEC"):
        file_flags |= os.O_CLOEXEC
        directory_flags |= os.O_CLOEXEC
    try:
        with ExitStack() as descriptors:
            current_directory = os.open(root, directory_flags)
            descriptors.callback(os.close, current_directory)
            for component in parts[:-1]:
                current_directory = os.open(
                    component,
                    directory_flags,
                    dir_fd=current_directory,
                )
                descriptors.callback(os.close, current_directory)
            descriptor = os.open(parts[-1], file_flags, dir_fd=current_directory)
            descriptors.callback(os.close, descriptor)
            file_stat = os.fstat(descriptor)
            if not stat.S_ISREG(file_stat.st_mode):
                fail(f"{label} must be a regular non-symlink file")
            if file_stat.st_size > limit:
                fail(f"{label} exceeds {limit} bytes")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                raw = stream.read(limit + 1)
    except OSError as exc:
        raise ContractError(f"{label} must be a regular non-symlink file") from exc
    if len(raw) > limit:
        fail(f"{label} exceeds {limit} bytes")
    return raw


def load_json_file(root: Path, relative_path: Path, label: str) -> dict[str, Any]:
    return load_json_bytes(
        read_bounded_regular_file(root, relative_path, label, MAX_JSON_BYTES),
        label,
    )


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
        raise ContractError(f"{label} is not a valid timestamp") from exc


def canonical_json_bytes(value: object) -> bytes:
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"value is not canonical JSON: {exc}") from exc
    return rendered.encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_sha256(value: object) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def canonical_document_bytes(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def chain_binding(
    *,
    repository: str,
    repository_id: str,
    base_sha: str,
    candidate_head_sha: str,
    candidate_diff_sha256: str,
    evidence_id: str,
    fixed_version: str,
    acceptance_profile: str,
) -> dict[str, str]:
    binding = {
        "repository": repository,
        "repositoryId": repository_id,
        "baseSha": base_sha,
        "candidateHeadSha": candidate_head_sha,
        "candidateDiffSha256": candidate_diff_sha256,
        "evidenceId": evidence_id,
        "fixedVersion": fixed_version,
        "acceptanceProfile": acceptance_profile,
    }
    exact_keys(binding, CHAIN_BINDING_KEYS, "Security chain binding")
    if repository != PRODUCER_REPOSITORY or repository_id != PRODUCER_REPOSITORY_ID:
        fail("Security chain repository identity is unauthorized")
    if SHA.fullmatch(base_sha) is None or SHA.fullmatch(candidate_head_sha) is None:
        fail("Security chain commit identity is invalid")
    if DIGEST.fullmatch(candidate_diff_sha256) is None:
        fail("Security chain candidate digest is invalid")
    if EVIDENCE_ID.fullmatch(evidence_id) is None:
        fail("Security chain evidenceId is invalid")
    if SEMVER.fullmatch(fixed_version) is None:
        fail("Security chain fixedVersion is invalid")
    if PROFILE.fullmatch(acceptance_profile) is None:
        fail("Security chain acceptanceProfile is invalid")
    return binding


def compute_chain_id(
    *,
    repository: str,
    repository_id: str,
    base_sha: str,
    candidate_head_sha: str,
    candidate_diff_sha256: str,
    evidence_id: str,
    fixed_version: str,
    acceptance_profile: str,
) -> str:
    return canonical_sha256(
        chain_binding(
            repository=repository,
            repository_id=repository_id,
            base_sha=base_sha,
            candidate_head_sha=candidate_head_sha,
            candidate_diff_sha256=candidate_diff_sha256,
            evidence_id=evidence_id,
            fixed_version=fixed_version,
            acceptance_profile=acceptance_profile,
        )
    )


def is_recovery_request(request: dict[str, Any]) -> bool:
    """Return whether ``request`` selects the single approved recovery event."""

    return request.get("event") == RECOVERY_EVENT


def validate_request(request: dict[str, Any], repository: str, now: datetime) -> dict[str, Any]:
    exact_keys(request, REQUEST_KEYS, "Security intake request")
    if not is_exact_int(request["schemaVersion"]) or request["schemaVersion"] != INTAKE_REQUEST_SCHEMA_VERSION:
        fail(f"Security intake schemaVersion must be {INTAKE_REQUEST_SCHEMA_VERSION}")
    if repository != PRODUCER_REPOSITORY or request["repository"] != repository:
        fail("Security intake repository does not match the exact producer repository")
    if request["repositoryId"] != PRODUCER_REPOSITORY_ID:
        fail("Security intake repositoryId does not match the exact producer repository")
    recovery = is_recovery_request(request)
    if request["event"] not in {"mlx90-security-release", RECOVERY_EVENT}:
        fail("Security intake event is unsupported")
    if not is_exact_int(request["humanActions"]) or request["humanActions"] != 0:
        fail("Security Zero-Touch intake must declare humanActions=0")

    for field in ("baseSha", "candidateBaseSha", "candidateHeadSha"):
        value = require_string(request[field], field)
        if SHA.fullmatch(value) is None:
            fail(f"{field} must be a full lowercase commit SHA")
    if request["candidateBaseSha"] == request["candidateHeadSha"]:
        fail("candidate source range must not be empty")
    if not recovery and request["candidateBaseSha"] != request["baseSha"]:
        fail("candidate source range must start at the authorized protected-main SHA")
    digest = require_string(request["candidateDiffSha256"], "candidateDiffSha256")
    if DIGEST.fullmatch(digest) is None:
        fail("candidateDiffSha256 must be a canonical SHA-256 digest")
    metadata_digest = require_string(request["metadataSha256"], "metadataSha256")
    if DIGEST.fullmatch(metadata_digest) is None:
        fail("metadataSha256 must be a canonical SHA-256 digest")
    evidence_id = require_string(request["evidenceId"], "evidenceId")
    if EVIDENCE_ID.fullmatch(evidence_id) is None:
        fail("evidenceId is invalid")
    version = require_string(request["fixedVersion"], "fixedVersion")
    if SEMVER.fullmatch(version) is None:
        fail("fixedVersion must be stable SemVer")
    profile = require_string(request["acceptanceProfile"], "acceptanceProfile")
    if PROFILE.fullmatch(profile) is None:
        fail("acceptanceProfile is invalid")
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

    if recovery:
        exact_recovery_binding = {
            "candidateBaseSha": RECOVERY_CANDIDATE_BASE_SHA,
            "candidateHeadSha": RECOVERY_CANDIDATE_HEAD_SHA,
            "candidateDiffSha256": RECOVERY_CANDIDATE_DIFF_SHA256,
            "evidenceId": RECOVERY_EVIDENCE_ID,
            "fixedVersion": RECOVERY_FIXED_VERSION,
            "acceptanceProfile": RECOVERY_ACCEPTANCE_PROFILE,
            "metadataSha256": RECOVERY_METADATA_SHA256,
            "issuedAt": RECOVERY_ISSUED_AT,
            "expiresAt": RECOVERY_EXPIRES_AT,
        }
        if any(request[field] != expected for field, expected in exact_recovery_binding.items()):
            fail("Security recovery request differs from the one-time approved binding")

    expected_chain_id = compute_chain_id(
        repository=repository,
        repository_id=PRODUCER_REPOSITORY_ID,
        base_sha=request["baseSha"],
        candidate_head_sha=request["candidateHeadSha"],
        candidate_diff_sha256=digest,
        evidence_id=evidence_id,
        fixed_version=version,
        acceptance_profile=profile,
    )
    if request["chainId"] != expected_chain_id:
        fail("Security intake chainId does not match its canonical binding")
    return request


def validate_metadata_payload(
    metadata: dict[str, Any],
    *,
    expected_evidence_id: str,
    expected_version: str,
    expected_profile: str,
    checked_at: datetime,
) -> dict[str, Any]:
    exact_keys(metadata, METADATA_KEYS, "Security release metadata")
    if not is_exact_int(metadata["schemaVersion"]) or metadata["schemaVersion"] != 1:
        fail("Security release metadata schemaVersion must be 1")
    if metadata["evidenceId"] != expected_evidence_id:
        fail("Security metadata evidenceId does not match the intake")
    if metadata["fixedVersion"] != expected_version:
        fail("Security metadata fixedVersion does not match the intake")
    if metadata["acceptanceProfile"] != expected_profile:
        fail("Security metadata acceptanceProfile does not match the intake")
    identifiers = metadata["securityIdentifiers"]
    if (
        not isinstance(identifiers, list)
        or not identifiers
        or any(not isinstance(item, str) or SECURITY_ID.fullmatch(item) is None for item in identifiers)
        or len(identifiers) != len(set(identifiers))
    ):
        fail("Security metadata identifiers are invalid")
    affected_version = require_string(metadata["affectedVersion"], "affectedVersion")
    if SEMVER.fullmatch(affected_version) is None or affected_version == expected_version:
        fail("Security metadata affectedVersion is invalid")
    if metadata["consumers"] != [CONSUMER_REPOSITORY]:
        fail("Security metadata consumer allowlist must contain only the exact MLX-90 consumer")
    validity = metadata["validity"]
    if validity.__class__ is not dict:
        fail("Security metadata validity must be an object")
    exact_keys(validity, VALIDITY_KEYS, "Security release validity")
    if validity["revoked"] is not False:
        fail("Security release metadata is revoked")
    created = timestamp(metadata["createdAt"], "createdAt")
    not_before = timestamp(validity["notBefore"], "validity.notBefore")
    expires = timestamp(validity["expiresAt"], "validity.expiresAt")
    if created < not_before or created >= expires:
        fail("Security metadata createdAt is outside its validity interval")
    if checked_at < not_before or checked_at >= expires:
        fail("Security release metadata is not currently valid")
    return metadata


def validate_request_metadata_binding(request: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Bind the request validity envelope to the reviewed metadata exactly."""

    if request["issuedAt"] != metadata["createdAt"]:
        fail("Security intake issuedAt differs from metadata createdAt")
    validity = metadata["validity"]
    if request["expiresAt"] != validity["expiresAt"]:
        fail("Security intake expiresAt differs from metadata validity.expiresAt")


def validate_profile_registry(registry: dict[str, Any], profile_id: str) -> dict[str, Any]:
    """Validate the exact protected-main profile registry and selected profile."""

    exact_keys(registry, {"schemaVersion", "profiles"}, "acceptance-profile registry")
    if not is_exact_int(registry["schemaVersion"]) or registry["schemaVersion"] != 1:
        fail("acceptance-profile registry is unsupported")
    profiles = registry["profiles"]
    if not isinstance(profiles, dict) or not profiles:
        fail("acceptance-profile registry profiles must be a non-empty object")
    for name, profile in profiles.items():
        if not isinstance(name, str) or PROFILE.fullmatch(name) is None:
            fail("acceptance-profile registry contains an invalid profile id")
        if not isinstance(profile, dict):
            fail(f"acceptance profile {name} must be an object")
        exact_keys(profile, PROFILE_KEYS, f"acceptance profile {name}")
        require_string(profile["description"], f"acceptance profile {name} description")
        if not isinstance(profile["releaseEligible"], bool):
            fail(f"acceptance profile {name} releaseEligible must be boolean")
    selected = profiles.get(profile_id)
    if not isinstance(selected, dict) or selected["releaseEligible"] is not True:
        fail("acceptance profile was not pre-approved on protected main")
    return selected


def canonical_security_fragment_bytes(entries: list[str]) -> bytes:
    """Serialize security fixes as deterministic repository-standard YAML."""
    if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
        fail("security_fixes entries must be a list containing 1..64 items")
    validated_entries = [require_string(entry, "security_fixes entry") for entry in entries]
    lines = ["---", "security_fixes:"]
    lines.extend(f"  - {json.dumps(entry, ensure_ascii=True)}" for entry in validated_entries)
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    if len(raw) > MAX_SECURITY_FRAGMENT_BYTES:
        fail(f"security_fixes fragment exceeds {MAX_SECURITY_FRAGMENT_BYTES} bytes")
    return raw


def validate_security_fragment(raw: bytes, label: str) -> dict[str, list[str]]:
    if len(raw) > MAX_SECURITY_FRAGMENT_BYTES:
        fail(f"{label} exceeds {MAX_SECURITY_FRAGMENT_BYTES} bytes")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ContractError(f"{label} is not valid UTF-8 YAML: {exc}") from exc
    if len(lines) < 3 or lines[:2] != ["---", "security_fixes:"]:
        fail(f"{label} must use canonical repository security_fixes YAML")
    entries: list[str] = []
    for line in lines[2:]:
        if not line.startswith("  - "):
            fail(f"{label} must use canonical repository security_fixes YAML")
        try:
            entry = json.loads(line[4:], parse_constant=lambda value: fail(f"{label} has invalid scalar: {value}"))
        except json.JSONDecodeError as exc:
            raise ContractError(f"{label} contains an invalid quoted YAML scalar: {exc}") from exc
        if not isinstance(entry, str):
            fail(f"{label} security_fixes entries must be strings")
        entries.append(require_string(entry, f"{label} security_fixes entry"))
    if not entries or len(entries) > 64:
        fail(f"{label} must contain 1..64 non-empty trimmed security_fixes entries")
    if raw != canonical_security_fragment_bytes(entries):
        fail(f"{label} must be canonical repository YAML with one trailing newline")
    return {"security_fixes": entries}


def validate_immutable_marker_changes(changes: list[tuple[str, str]], fixed_version: str) -> None:
    expected_metadata = f".lit/security-releases/{fixed_version}.json"
    metadata_changes = [item for item in changes if item[1].startswith(".lit/security-releases/")]
    intake_changes = [item for item in changes if item[1].startswith(".lit/security-release-intakes/")]
    if metadata_changes != [("A", expected_metadata)]:
        fail("candidate must add exactly one immutable Security metadata file and preserve every existing marker")
    if intake_changes:
        fail("candidate must not create, modify, or delete App-owned Security intake receipts")
    if any(path == ".lit/security-release-profiles.json" for _status, path in changes):
        fail("candidate must not modify the protected-main Security profile registry")


def validate_intake_result(request: dict[str, Any], verified: dict[str, Any]) -> dict[str, Any]:
    exact_keys(verified, VERIFIED_KEYS, "verified Security intake")
    if not is_exact_int(verified["schemaVersion"]) or verified["schemaVersion"] != INTAKE_RESULT_SCHEMA_VERSION:
        fail(f"verified Security intake schemaVersion must be {INTAKE_RESULT_SCHEMA_VERSION}")
    if not is_exact_int(verified["humanActions"]) or verified["humanActions"] != 0:
        fail("verified Security intake must declare humanActions=0")
    expected = {
        "chainId": request["chainId"],
        "branch": f"security-release/{request['evidenceId']}",
        "baseSha": request["baseSha"],
        "candidateBaseSha": request["candidateBaseSha"],
        "candidateHeadSha": request["candidateHeadSha"],
        "candidateDiffSha256": request["candidateDiffSha256"],
        "evidenceId": request["evidenceId"],
        "fixedVersion": request["fixedVersion"],
        "metadataPath": f".lit/security-releases/{request['fixedVersion']}.json",
        "metadataSha256": request["metadataSha256"],
        "acceptanceProfile": request["acceptanceProfile"],
        "humanActions": 0,
    }
    for field, value in expected.items():
        if verified[field] != value:
            fail(f"verified Security intake {field} differs from its request")
    fragment_path = verified["changelogFragmentPath"]
    if not isinstance(fragment_path, str) or re.fullmatch(r"changelogs/fragments/[^/]+\.ya?ml", fragment_path) is None:
        fail("verified Security intake changelog fragment path is invalid")
    if DIGEST.fullmatch(str(verified["changelogFragmentSha256"])) is None:
        fail("verified Security intake changelog fragment digest is invalid")
    changed_paths = verified["changedPaths"]
    if (
        not isinstance(changed_paths, list)
        or not changed_paths
        or any(not isinstance(path, str) or not path for path in changed_paths)
        or changed_paths != sorted(set(changed_paths))
        or expected["metadataPath"] not in changed_paths
        or fragment_path not in changed_paths
    ):
        fail("verified Security intake changedPaths are incomplete, duplicate, or unsorted")
    return verified


def build_intake_receipt(
    request: dict[str, Any],
    verified: dict[str, Any],
    *,
    checked_at: datetime,
    workflow_run_id: str,
    workflow_attempt: str,
    workflow_ref: str,
    workflow_event: str,
    workflow_actor: str,
    workflow_triggering_actor: str,
    observed_automation: dict[str, Any],
) -> dict[str, Any]:
    validate_request(request, PRODUCER_REPOSITORY, checked_at)
    validate_intake_result(request, verified)
    if observed_automation != RELEASE_APP_IDENTITY:
        fail("observed release automation identity is unauthorized")
    automation = dict(observed_automation)
    automation["selectedRepositories"] = list(observed_automation["selectedRepositories"])
    automation["permissions"] = dict(observed_automation["permissions"])
    receipt = {
        "schemaVersion": INTAKE_RECEIPT_SCHEMA_VERSION,
        "chainId": request["chainId"],
        "request": request,
        "verified": verified,
        "automation": automation,
        "controller": {
            "path": ".github/workflows/security-release-intake.yml",
            "ref": workflow_ref,
            "sourceSha": request["baseSha"],
            "runId": workflow_run_id,
            "runAttempt": workflow_attempt,
            "event": workflow_event,
            "gitRef": "refs/heads/main",
            "actor": workflow_actor,
            "triggeringActor": workflow_triggering_actor,
        },
    }
    verify_intake_receipt(receipt, checked_at=checked_at)
    return receipt


def verify_intake_receipt(
    receipt: dict[str, Any],
    *,
    checked_at: datetime,
) -> dict[str, Any]:
    exact_keys(receipt, INTAKE_RECEIPT_KEYS, "Security intake receipt")
    if not is_exact_int(receipt["schemaVersion"]) or receipt["schemaVersion"] != INTAKE_RECEIPT_SCHEMA_VERSION:
        fail(f"Security intake receipt schemaVersion must be {INTAKE_RECEIPT_SCHEMA_VERSION}")
    request = receipt["request"]
    verified = receipt["verified"]
    if not isinstance(request, dict) or not isinstance(verified, dict):
        fail("Security intake receipt request and verified values must be objects")
    validate_request(request, PRODUCER_REPOSITORY, checked_at)
    validate_intake_result(request, verified)
    if receipt["chainId"] != request["chainId"]:
        fail("Security intake receipt chainId differs from its request")
    if receipt["automation"] != RELEASE_APP_IDENTITY:
        fail("Security intake receipt automation identity is unauthorized")
    controller = receipt["controller"]
    if not isinstance(controller, dict):
        fail("Security intake receipt controller must be an object")
    exact_keys(controller, CONTROLLER_KEYS, "Security intake receipt controller")
    expected_ref = f"{PRODUCER_REPOSITORY}/.github/workflows/security-release-intake.yml@refs/heads/main"
    if (
        controller["path"] != ".github/workflows/security-release-intake.yml"
        or controller["ref"] != expected_ref
        or controller["sourceSha"] != request["baseSha"]
        or controller["event"] != "workflow_dispatch"
        or controller["gitRef"] != "refs/heads/main"
        or controller["actor"] != RELEASE_APP_LOGIN
        or controller["triggeringActor"] != RELEASE_APP_LOGIN
        or not isinstance(controller["runId"], str)
        or re.fullmatch(r"[1-9][0-9]*", controller["runId"]) is None
        or not isinstance(controller["runAttempt"], str)
        or re.fullmatch(r"[1-9][0-9]*", controller["runAttempt"]) is None
    ):
        fail("Security intake receipt controller identity is unauthorized")
    return receipt


def load_security_binding(
    root: Path,
    version: str,
    *,
    checked_at: datetime,
) -> dict[str, Any] | None:
    if SEMVER.fullmatch(version) is None:
        fail("Security binding version must be stable SemVer")
    metadata_path = root / ".lit" / "security-releases" / f"{version}.json"
    intake_path = root / ".lit" / "security-release-intakes" / f"{version}.json"
    metadata_exists = metadata_path.exists() or metadata_path.is_symlink()
    intake_exists = intake_path.exists() or intake_path.is_symlink()
    if not metadata_exists and not intake_exists:
        return None
    if metadata_exists != intake_exists:
        fail("partial Security marker: metadata and App-owned intake receipt must exist together")

    metadata_raw = read_bounded_regular_file(
        root,
        metadata_path.relative_to(root),
        "Security metadata",
        MAX_JSON_BYTES,
    )
    if not metadata_raw:
        fail("Security metadata must be a non-empty regular non-symlink file")
    metadata = load_json_bytes(metadata_raw, "Security release metadata")
    intake_raw = read_bounded_regular_file(
        root,
        intake_path.relative_to(root),
        "Security intake receipt",
        MAX_JSON_BYTES,
    )
    receipt = load_json_bytes(intake_raw, "Security intake receipt")
    if intake_raw != canonical_document_bytes(receipt):
        fail("Security intake receipt is not canonical JSON")
    verify_intake_receipt(receipt, checked_at=checked_at)
    request = receipt["request"]
    verified = receipt["verified"]
    if request["fixedVersion"] != version:
        fail("Security intake receipt fixedVersion differs from its path")
    metadata_digest = sha256_bytes(metadata_raw)
    if request["metadataSha256"] != metadata_digest or verified["metadataSha256"] != metadata_digest:
        fail("Security metadata digest differs from the immutable intake binding")
    validate_metadata_payload(
        metadata,
        expected_evidence_id=request["evidenceId"],
        expected_version=version,
        expected_profile=request["acceptanceProfile"],
        checked_at=checked_at,
    )
    validate_request_metadata_binding(request, metadata)
    fragment_path_text = verified["changelogFragmentPath"]
    fragment_path = root / fragment_path_text
    fragment_raw = read_bounded_regular_file(
        root,
        fragment_path.relative_to(root),
        "Security changelog fragment",
        MAX_SECURITY_FRAGMENT_BYTES,
    )
    fragment_digest = sha256_bytes(fragment_raw)
    if is_recovery_request(request):
        if (
            version != RECOVERY_FIXED_VERSION
            or fragment_path_text != RECOVERY_FRAGMENT_PATH
            or fragment_digest != RECOVERY_FRAGMENT_SHA256
        ):
            fail("Security recovery changelog fragment differs from the one-time approved binding")
    else:
        validate_security_fragment(fragment_raw, "Security changelog fragment")
    if verified["changelogFragmentSha256"] != fragment_digest:
        fail("Security changelog fragment digest differs from the immutable intake binding")
    profiles = load_json_file(
        root,
        Path(".lit/security-release-profiles.json"),
        "protected-main acceptance-profile registry",
    )
    validate_profile_registry(profiles, request["acceptanceProfile"])
    return {
        "chain_id": request["chainId"],
        "evidence_id": request["evidenceId"],
        "fixed_version": version,
        "acceptance_profile": request["acceptanceProfile"],
        "candidate_diff_sha256": request["candidateDiffSha256"],
        "metadata_path": metadata_path.relative_to(root).as_posix(),
        "metadata_sha256": metadata_digest,
        "intake_receipt_path": intake_path.relative_to(root).as_posix(),
        "intake_receipt_sha256": sha256_bytes(intake_raw),
        "changelog_fragment_path": fragment_path_text,
        "changelog_fragment_sha256": fragment_digest,
        "human_actions": 0,
    }


def _security_marker_versions(root: Path, relative_directory: str) -> set[tuple[int, int, int]]:
    directory = root / relative_directory
    if not directory.exists() and not directory.is_symlink():
        return set()
    if directory.is_symlink() or not directory.is_dir():
        fail(f"Security marker namespace {relative_directory} must be a regular directory")
    versions: set[tuple[int, int, int]] = set()
    for path in directory.iterdir():
        if path.name == ".gitkeep":
            continue
        match = re.fullmatch(
            r"((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\.json",
            path.name,
        )
        if match is None:
            fail(f"Security marker namespace contains an invalid entry: {relative_directory}/{path.name}")
        if path.is_symlink() or not path.is_file():
            fail(f"Security marker must be a regular non-symlink file: {relative_directory}/{path.name}")
        major, minor, patch = match.group(1).split(".")
        versions.add((int(major), int(minor), int(patch)))
    return versions


def load_release_security_binding(
    root: Path,
    current_version: str,
    target_version: str,
    *,
    checked_at: datetime,
) -> dict[str, Any] | None:
    """Select an exact pending Security binding without normal-mode fallback."""

    if SEMVER.fullmatch(current_version) is None or SEMVER.fullmatch(target_version) is None:
        fail("release Security marker versions must be stable SemVer")
    current = tuple(int(part) for part in current_version.split("."))
    target = tuple(int(part) for part in target_version.split("."))
    if target <= current:
        fail("release Security marker target must be newer than the current version")
    metadata_versions = _security_marker_versions(root, ".lit/security-releases")
    intake_versions = _security_marker_versions(root, ".lit/security-release-intakes")
    pending = {version for version in metadata_versions | intake_versions if version > current}
    if pending and pending != {target}:
        rendered = [".".join(map(str, version)) for version in sorted(pending)]
        fail("pending Security marker does not match the selected release target: " + ", ".join(rendered))
    if target not in pending:
        return None
    return load_security_binding(root, target_version, checked_at=checked_at)
