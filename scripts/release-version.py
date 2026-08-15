"""Resolve a stable collection release version from reviewed changelog impact."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import security_release_contract as CONTRACT  # noqa: E402

SEMVER_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
IMPACT_CATEGORIES = {
    "major": {"breaking_changes", "major_changes", "removed_features"},
    "minor": {"deprecated_features", "minor_changes"},
    "patch": {"bugfixes", "security_fixes"},
}
NEUTRAL_CATEGORIES = {"known_issues", "release_summary", "trivial"}
KNOWN_CATEGORIES = set().union(*IMPACT_CATEGORIES.values(), NEUTRAL_CATEGORIES)
MAX_FRAGMENT_BYTES = 1024 * 1024
RELEASE_PREPARATION_SCHEMA_VERSION = 2
RELEASE_PREPARER = {
    "login": CONTRACT.RELEASE_APP_LOGIN,
    "account_id": CONTRACT.RELEASE_APP_ACCOUNT_ID,
    "email": CONTRACT.RELEASE_APP_EMAIL,
}
SECURITY_RECEIPT_KEYS = {
    "evidence_id",
    "metadata_path",
    "metadata_sha256",
    "intake_receipt_path",
    "intake_receipt_sha256",
    "candidate_diff_sha256",
    "human_actions",
}


class VersionError(ValueError):
    """Raised when release impact or version identity is unsafe."""


class UniqueKeyLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise VersionError(f"duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_unique_json(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise VersionError("release preparation receipt must be a regular non-symlink file")
        raw = path.read_bytes()
        payload = CONTRACT.load_json_bytes(raw, "release preparation receipt")
        if raw != CONTRACT.canonical_document_bytes(payload):
            raise VersionError("release preparation receipt is not canonical JSON")
    except (OSError, CONTRACT.ContractError) as error:
        raise VersionError(f"cannot parse release preparation receipt: {error}") from error
    return payload


def _security_binding(
    root: Path,
    current_version: str,
    target_version: str,
    checked_at: datetime,
) -> dict[str, Any] | None:
    try:
        return CONTRACT.load_release_security_binding(
            root,
            current_version,
            target_version,
            checked_at=checked_at,
        )
    except (OSError, CONTRACT.ContractError) as error:
        raise VersionError(str(error)) from error


def parse_stable_version(value: object, *, label: str) -> tuple[int, int, int]:
    rendered = str(value or "").strip()
    match = SEMVER_RE.fullmatch(rendered)
    if match is None:
        raise VersionError(f"{label} must be stable semantic versioning (MAJOR.MINOR.PATCH): {rendered!r}")
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def _load_yaml(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise VersionError(f"unsafe changelog fragment: {path}")
    if path.stat().st_size > MAX_FRAGMENT_BYTES:
        raise VersionError(f"oversized changelog fragment: {path}")
    try:
        payload = (
            yaml.load(
                path.read_text(encoding="utf-8"),
                Loader=UniqueKeyLoader,  # noqa: S506 -- subclasses yaml.SafeLoader.
            )
            or {}
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise VersionError(f"cannot parse changelog fragment {path}: {error}") from error
    if not isinstance(payload, dict):
        raise VersionError(f"changelog fragment must be a mapping: {path}")
    return payload


def _derive_impact_from_paths(paths: list[Path]) -> tuple[str, list[str]]:
    """Derive reviewed impact from an already bounded fragment set."""

    if len(paths) > 256:
        raise VersionError("more than 256 changelog fragments require an explicit split release")
    if not paths:
        raise VersionError("no reviewed changelog fragments exist")
    observed: set[str] = set()
    for path in paths:
        payload = _load_yaml(path)
        unknown = sorted(str(key) for key in payload if key not in KNOWN_CATEGORIES)
        if unknown:
            raise VersionError(f"unknown changelog impact categories in {path}: {', '.join(unknown)}")
        if not payload:
            raise VersionError(f"empty changelog fragment: {path}")
        for category, entries in payload.items():
            if (
                not isinstance(entries, list)
                or not entries
                or any(not isinstance(entry, str) or not entry.strip() for entry in entries)
            ):
                raise VersionError(f"changelog category {category} must contain nonempty text entries: {path}")
            if category not in NEUTRAL_CATEGORIES:
                observed.add(str(category))
    for impact in ("major", "minor", "patch"):
        if observed & IMPACT_CATEGORIES[impact]:
            return impact, [path.name for path in paths]
    raise VersionError("changelog fragments have no explicit semantic-version impact category")


def derive_impact(fragments_root: Path) -> tuple[str, list[str]]:
    if not fragments_root.is_dir() or fragments_root.is_symlink():
        raise VersionError(f"unsafe changelog fragment directory: {fragments_root}")
    candidates = sorted(path for path in fragments_root.iterdir() if path.suffix.lower() in {".yml", ".yaml"})
    unsafe = [path for path in candidates if path.is_symlink() or not path.is_file()]
    if unsafe:
        raise VersionError(f"unsafe changelog fragment: {unsafe[0]}")
    return _derive_impact_from_paths(candidates)


def _fragment_digests(fragments_root: Path, names: list[str]) -> list[dict[str, str]]:
    return [
        {
            "path": name,
            "sha256": hashlib.sha256((fragments_root / name).read_bytes()).hexdigest(),
        }
        for name in names
    ]


def next_version(current: tuple[int, int, int], impact: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if impact == "major":
        return major + 1, 0, 0
    if impact == "minor":
        return major, minor + 1, 0
    if impact == "patch":
        return major, minor, patch + 1
    raise VersionError(f"unsupported release impact: {impact}")


def resolve_version(
    galaxy_path: Path,
    fragments_root: Path,
    requested: str = "",
    *,
    security_target: str = "",
    root: Path | None = None,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    if galaxy_path.is_symlink() or not galaxy_path.is_file() or galaxy_path.stat().st_size > MAX_FRAGMENT_BYTES:
        raise VersionError(f"unsafe collection metadata: {galaxy_path}")
    try:
        galaxy = (
            yaml.load(
                galaxy_path.read_text(encoding="utf-8"),
                Loader=UniqueKeyLoader,  # noqa: S506 -- subclasses yaml.SafeLoader.
            )
            or {}
        )
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise VersionError(f"cannot parse collection metadata: {error}") from error
    if not isinstance(galaxy, dict):
        raise VersionError("galaxy.yml must be a mapping")
    current = parse_stable_version(galaxy.get("version"), label="galaxy.yml version")
    current_version = ".".join(map(str, current))
    if requested and security_target:
        raise VersionError("normal requested version and Security target are mutually exclusive")
    if security_target:
        selected_security_version = ".".join(
            map(str, parse_stable_version(security_target, label="Security target version"))
        )
        root = (root or galaxy_path.parent).resolve()
        checked_at = checked_at or datetime.now(UTC)
        try:
            binding = CONTRACT.load_release_security_binding(
                root,
                current_version,
                selected_security_version,
                checked_at=checked_at,
            )
        except (OSError, CONTRACT.ContractError) as error:
            raise VersionError(str(error)) from error
        if binding is None:
            raise VersionError("Security target has no complete immutable intake binding")
        bound_fragment = root / str(binding["changelog_fragment_path"])
        try:
            fragments_directory = fragments_root.resolve(strict=True)
            bound_parent = bound_fragment.parent.resolve(strict=True)
        except OSError as error:
            raise VersionError(f"cannot resolve Security changelog fragment: {error}") from error
        if bound_parent != fragments_directory:
            raise VersionError("Security changelog fragment is outside the configured fragment directory")
        if bound_fragment.suffix.lower() not in {".yml", ".yaml"}:
            raise VersionError("Security changelog fragment must use a .yml or .yaml extension")
        impact, fragments = _derive_impact_from_paths([bound_fragment])
        if impact != "patch":
            raise VersionError("Security release fragment must resolve to patch impact")
    else:
        impact, fragments = derive_impact(fragments_root)
    expected = next_version(current, impact)
    if security_target:
        selected = parse_stable_version(security_target, label="Security target version")
        if selected != expected:
            raise VersionError(
                f"Security target {security_target} does not equal the reviewed patch release "
                f"{'.'.join(map(str, expected))}"
            )
    elif requested:
        selected = parse_stable_version(requested, label="requested version")
        if selected != expected:
            raise VersionError(
                f"requested version {requested} does not equal the reviewed {impact} release "
                f"{'.'.join(map(str, expected))}"
            )
    else:
        selected = expected
    return {
        "schema_version": 1,
        "current_version": ".".join(map(str, current)),
        "impact": impact,
        "version": ".".join(map(str, selected)),
        "fragments": fragments,
        "fragment_sha256": _fragment_digests(fragments_root, fragments),
    }


def build_preparation_receipt(
    resolution: dict[str, Any],
    *,
    repository: str,
    repository_id: str,
    base_sha: str,
    workflow_run_id: str,
    workflow_attempt: str,
    workflow_ref: str,
    workflow_event: str,
    workflow_actor: str,
    root: Path | None = None,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    """Bind reviewed fragment inputs to the protected release-preparation run."""

    root = (root or Path.cwd()).resolve()
    checked_at = checked_at or datetime.now(UTC)
    version = str(resolution.get("version", ""))
    current_version = str(resolution.get("current_version", ""))
    security_binding = _security_binding(root, current_version, version, checked_at)
    release_mode = "security" if security_binding is not None else "normal"
    chain_id = security_binding["chain_id"] if security_binding is not None else None
    security = None
    if security_binding is not None:
        security = {
            "evidence_id": security_binding["evidence_id"],
            "metadata_path": security_binding["metadata_path"],
            "metadata_sha256": security_binding["metadata_sha256"],
            "intake_receipt_path": security_binding["intake_receipt_path"],
            "intake_receipt_sha256": security_binding["intake_receipt_sha256"],
            "candidate_diff_sha256": security_binding["candidate_diff_sha256"],
            "human_actions": security_binding["human_actions"],
        }
    payload: dict[str, Any] = {
        "schema_version": RELEASE_PREPARATION_SCHEMA_VERSION,
        "repository": repository,
        "repository_id": repository_id,
        "base_sha": base_sha,
        "release_mode": release_mode,
        "chain_id": chain_id,
        "security": security,
        "current_version": resolution.get("current_version"),
        "impact": resolution.get("impact"),
        "next_version": resolution.get("version"),
        "fragments": resolution.get("fragment_sha256"),
        "preparer": RELEASE_PREPARER,
        "workflow": {
            "path": ".github/workflows/release-prepare.yml",
            "ref": workflow_ref,
            "source_sha": base_sha,
            "run_id": workflow_run_id,
            "run_attempt": workflow_attempt,
            "event": workflow_event,
            "git_ref": "refs/heads/main",
            "actor": workflow_actor,
        },
    }
    verify_preparation_receipt(
        payload,
        expected_repository=repository,
        expected_repository_id=repository_id,
        expected_base_sha=base_sha,
        expected_version=version,
        root=root,
        checked_at=checked_at,
    )
    return payload


def verify_preparation_receipt(
    receipt: dict[str, Any],
    *,
    expected_repository: str,
    expected_repository_id: str,
    expected_base_sha: str,
    expected_version: str,
    root: Path | None = None,
    checked_at: datetime | None = None,
) -> None:
    """Fail closed unless a preparation receipt is structurally and semantically exact."""

    required = {
        "schema_version",
        "repository",
        "repository_id",
        "base_sha",
        "release_mode",
        "chain_id",
        "security",
        "current_version",
        "impact",
        "next_version",
        "fragments",
        "preparer",
        "workflow",
    }
    if set(receipt) != required:
        raise VersionError("release preparation receipt has missing or unknown fields")
    schema_version = receipt.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != RELEASE_PREPARATION_SCHEMA_VERSION
    ):
        raise VersionError("release preparation receipt schema is unsupported")
    if receipt.get("repository") != expected_repository or not re.fullmatch(
        r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", expected_repository
    ):
        raise VersionError("release preparation receipt repository differs")
    if receipt.get("repository_id") != expected_repository_id or not expected_repository_id.isdigit():
        raise VersionError("release preparation receipt repository id differs")
    if receipt.get("base_sha") != expected_base_sha or re.fullmatch(r"[0-9a-f]{40}", expected_base_sha) is None:
        raise VersionError("release preparation receipt base SHA differs")

    current = parse_stable_version(receipt.get("current_version"), label="receipt current version")
    impact = str(receipt.get("impact", ""))
    calculated = ".".join(map(str, next_version(current, impact)))
    next_value = str(receipt.get("next_version", ""))
    parse_stable_version(next_value, label="receipt next version")
    if next_value != calculated or next_value != expected_version:
        raise VersionError("release preparation receipt next version is not fragment-derived")

    root = (root or Path.cwd()).resolve()
    checked_at = checked_at or datetime.now(UTC)
    security_binding = _security_binding(root, receipt["current_version"], expected_version, checked_at)
    expected_mode = "security" if security_binding is not None else "normal"
    if receipt.get("release_mode") != expected_mode:
        raise VersionError("release preparation receipt mode differs from immutable Security markers")
    if security_binding is None:
        if receipt.get("chain_id") is not None or receipt.get("security") is not None:
            raise VersionError("normal release preparation receipt contains partial Security markers")
    else:
        expected_security = {
            "evidence_id": security_binding["evidence_id"],
            "metadata_path": security_binding["metadata_path"],
            "metadata_sha256": security_binding["metadata_sha256"],
            "intake_receipt_path": security_binding["intake_receipt_path"],
            "intake_receipt_sha256": security_binding["intake_receipt_sha256"],
            "candidate_diff_sha256": security_binding["candidate_diff_sha256"],
            "human_actions": 0,
        }
        security = receipt.get("security")
        if not isinstance(security, dict) or set(security) != SECURITY_RECEIPT_KEYS:
            raise VersionError("Security release preparation receipt binding is malformed")
        human_actions = security.get("human_actions")
        if not isinstance(human_actions, int) or isinstance(human_actions, bool):
            raise VersionError("Security release preparation human_actions must be an integer")
        if security != expected_security or receipt.get("chain_id") != security_binding["chain_id"]:
            raise VersionError("Security release preparation receipt differs from the immutable intake binding")
        if (
            expected_repository != CONTRACT.PRODUCER_REPOSITORY
            or expected_repository_id != CONTRACT.PRODUCER_REPOSITORY_ID
        ):
            raise VersionError("Security release preparation repository identity is unauthorized")

    fragments = receipt.get("fragments")
    if not isinstance(fragments, list) or not fragments or len(fragments) > 256:
        raise VersionError("release preparation receipt has no reviewed fragment digests")
    names: list[str] = []
    for fragment in fragments:
        if not isinstance(fragment, dict) or set(fragment) != {"path", "sha256"}:
            raise VersionError("release preparation receipt has a malformed fragment digest")
        name = fragment.get("path")
        digest = fragment.get("sha256")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or Path(name).suffix.lower() not in {".yml", ".yaml"}
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise VersionError("release preparation receipt has an unsafe fragment digest")
        names.append(name)
    if names != sorted(set(names)):
        raise VersionError("release preparation receipt fragment digests are duplicate or unsorted")
    if security_binding is not None:
        expected_fragment = Path(security_binding["changelog_fragment_path"]).name
        expected_digest = security_binding["changelog_fragment_sha256"].removeprefix("sha256:")
        bound_fragments = {fragment["path"]: fragment["sha256"] for fragment in fragments}
        if bound_fragments.get(expected_fragment) != expected_digest:
            raise VersionError(
                "Security release preparation fragments do not contain the immutable intake fragment digest"
            )
    if receipt.get("preparer") != RELEASE_PREPARER:
        raise VersionError("release preparation receipt preparer is unauthorized")

    workflow = receipt.get("workflow")
    workflow_keys = {
        "path",
        "ref",
        "source_sha",
        "run_id",
        "run_attempt",
        "event",
        "git_ref",
        "actor",
    }
    if not isinstance(workflow, dict) or set(workflow) != workflow_keys:
        raise VersionError("release preparation receipt workflow identity is malformed")
    expected_workflow_ref = f"{expected_repository}/.github/workflows/release-prepare.yml@refs/heads/main"
    if (
        workflow.get("path") != ".github/workflows/release-prepare.yml"
        or workflow.get("ref") != expected_workflow_ref
        or workflow.get("source_sha") != expected_base_sha
        or workflow.get("git_ref") != "refs/heads/main"
        or workflow.get("event") not in {"push", "workflow_dispatch"}
        or not isinstance(workflow.get("actor"), str)
        or not workflow.get("actor")
        or not isinstance(workflow.get("run_id"), str)
        or re.fullmatch(r"[1-9][0-9]*", workflow["run_id"]) is None
        or not isinstance(workflow.get("run_attempt"), str)
        or re.fullmatch(r"[1-9][0-9]*", workflow["run_attempt"]) is None
    ):
        raise VersionError("release preparation receipt does not identify an authorized workflow run")
    if expected_mode == "security" and (
        workflow.get("event") != "push" or workflow.get("actor") != CONTRACT.RELEASE_APP_LOGIN
    ):
        raise VersionError("Security release preparation must be an App-authored protected-main push")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--galaxy", type=Path, default=Path("galaxy.yml"))
    parser.add_argument("--fragments", type=Path, default=Path("changelogs/fragments"))
    parser.add_argument("--requested-version", default="")
    parser.add_argument("--security-target-version", default="")
    parser.add_argument("--write-preparation-receipt", type=Path)
    parser.add_argument("--verify-preparation-receipt", type=Path)
    parser.add_argument("--repository", default="")
    parser.add_argument("--repository-id", default="")
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--workflow-attempt", default="")
    parser.add_argument("--workflow-ref", default="")
    parser.add_argument("--workflow-event", default="")
    parser.add_argument("--workflow-actor", default="")
    parser.add_argument("--expected-version", default="")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--checked-at", default="")
    args = parser.parse_args()
    try:
        checked_at = CONTRACT.timestamp(args.checked_at, "--checked-at") if args.checked_at else datetime.now(UTC)
        if args.verify_preparation_receipt:
            if args.write_preparation_receipt:
                raise VersionError("receipt creation and verification are mutually exclusive")
            receipt = _load_unique_json(args.verify_preparation_receipt)
            verify_preparation_receipt(
                receipt,
                expected_repository=args.repository,
                expected_repository_id=args.repository_id,
                expected_base_sha=args.base_sha,
                expected_version=args.expected_version,
                root=args.root,
                checked_at=checked_at,
            )
            print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
            return 0
        payload = resolve_version(
            args.galaxy,
            args.fragments,
            args.requested_version,
            security_target=args.security_target_version,
            root=args.root,
            checked_at=checked_at,
        )
        if args.write_preparation_receipt:
            receipt = build_preparation_receipt(
                payload,
                repository=args.repository,
                repository_id=args.repository_id,
                base_sha=args.base_sha,
                workflow_run_id=args.workflow_run_id,
                workflow_attempt=args.workflow_attempt,
                workflow_ref=args.workflow_ref,
                workflow_event=args.workflow_event,
                workflow_actor=args.workflow_actor,
                root=args.root,
                checked_at=checked_at,
            )
            args.write_preparation_receipt.parent.mkdir(parents=True, exist_ok=True)
            args.write_preparation_receipt.write_bytes(CONTRACT.canonical_document_bytes(receipt))
    except (VersionError, CONTRACT.ContractError) as error:
        parser.error(str(error))
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
