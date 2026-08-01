"""Select independently scoped quality profiles from a reviewed Git change set.

MLX-70 separates unprivileged Fast-Lane selection from protected Heavy and
Application-Acceptance selection. The latter values are metadata for the
central validation controller; this selector must never infer them from Tiny.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import TypedDict

import yaml

ZERO_SHA = "0" * 40
SHA = re.compile(r"^[0-9a-f]{40}$")
PROFILES = {"tiny", "heavy", "application_acceptance"}
DEPENDENCY_INVENTORY = "meta/source-dependencies.yml"


class FamilyPolicy(TypedDict):
    profiles: list[str]
    path_prefixes: list[str]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-ref", default="")
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--execution-mode", default="")
    parser.add_argument("--registry", default="meta/quality-impact.yml")
    parser.add_argument("--changed-file", action="append", default=[])
    # Test-only seam: production obtains the exact base inventory from Git.
    parser.add_argument("--base-dependency-inventory", default="")
    return parser


def _normalized_paths(paths: list[str]) -> list[str]:
    normalized: set[str] = set()
    for raw_path in paths:
        path = PurePosixPath(raw_path.strip())
        rendered = path.as_posix()
        if not rendered or rendered == "." or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe changed path: {raw_path!r}")
        normalized.add(rendered)
    return sorted(normalized)


def _git_changed_files(base_sha: str, head_sha: str) -> list[str]:
    if not SHA.fullmatch(head_sha):
        raise ValueError("head SHA must be a full lowercase Git object ID")
    if base_sha == ZERO_SHA:
        return []
    if not SHA.fullmatch(base_sha):
        raise ValueError("base SHA must be a full lowercase Git object ID")
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACDMRTUXB", f"{base_sha}...{head_sha}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return _normalized_paths(result.stdout.splitlines())


def _registry(path: str) -> tuple[dict[str, FamilyPolicy], list[str]]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("quality impact registry must use schema version 2")
    families = payload.get("families")
    safe_prefixes = payload.get("safe_fast_lane_path_prefixes")
    if not isinstance(families, dict) or not families:
        raise ValueError("quality impact registry must declare at least one family")
    if not isinstance(safe_prefixes, list) or not all(isinstance(item, str) for item in safe_prefixes):
        raise ValueError("quality impact registry must declare safe Fast-Lane path prefixes")
    for prefix in safe_prefixes:
        path = PurePosixPath(prefix)
        if (
            prefix != prefix.strip()
            or not prefix
            or prefix == "."
            or path.is_absolute()
            or ".." in path.parts
            or "\0" in prefix
        ):
            raise ValueError(f"unsafe safe Fast-Lane path prefix: {prefix!r}")
    normalized: dict[str, FamilyPolicy] = {}
    for name, policy in families.items():
        if not isinstance(name, str) or not isinstance(policy, dict):
            raise ValueError("quality impact family entries must be mappings")
        profiles = policy.get("profiles")
        prefixes = policy.get("path_prefixes")
        if not isinstance(profiles, list) or not profiles or set(profiles) - PROFILES:
            raise ValueError(f"quality impact family {name!r} has unsupported profiles")
        if "application_acceptance" in profiles and "heavy" not in profiles:
            raise ValueError(f"quality impact family {name!r} requires heavy when it declares application_acceptance")
        if not isinstance(prefixes, list) or not prefixes or not all(isinstance(item, str) for item in prefixes):
            raise ValueError(f"quality impact family {name!r} requires path prefixes")
        normalized[name] = {"profiles": profiles, "path_prefixes": prefixes}
    return normalized, safe_prefixes


def _matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix)


def _inventory_entries(raw: str) -> dict[str, tuple[object, list[str]]]:
    """Return declared dependency identities and their affected source locations."""
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("source dependency inventory is malformed")
    entries: dict[str, tuple[object, list[str]]] = {}
    for section, identity_key in (
        ("container_images", "reference"),
        ("derived_images", "reference"),
        ("external_products", "name"),
    ):
        values = payload.get(section)
        if not isinstance(values, list):
            raise ValueError(f"source dependency inventory {section} is malformed")
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get(identity_key), str):
                raise ValueError(f"source dependency inventory {section} entry is malformed")
            identity = str(item[identity_key]).split("@", maxsplit=1)[0]
            key = f"{section}:{identity}"
            locations = item.get("locations")
            if (
                key in entries
                or not isinstance(locations, list)
                or not all(isinstance(location, str) for location in locations)
            ):
                raise ValueError(f"source dependency inventory {section} has duplicate or malformed entries")
            entries[key] = (item, _normalized_paths(locations))
    # Collection declarations have no source location. Their changes are
    # deliberately unclassified, so only Tiny fails closed for a PR.
    collections = payload.get("collections")
    if not isinstance(collections, list):
        raise ValueError("source dependency inventory collections are malformed")
    for item in collections:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError("source dependency inventory collection entry is malformed")
        key = f"collections:{item['name']}"
        if key in entries:
            raise ValueError("source dependency inventory has duplicate collection entries")
        entries[key] = (item, [])
    return entries


def _base_inventory(args: argparse.Namespace) -> str:
    fixture = getattr(args, "base_dependency_inventory", "")
    if fixture:
        return Path(str(fixture)).read_text(encoding="utf-8")
    if not SHA.fullmatch(args.base_sha):
        raise ValueError("source dependency base SHA is unavailable")
    result = subprocess.run(
        ["git", "show", f"{args.base_sha}:{DEPENDENCY_INVENTORY}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _dependency_impact(
    args: argparse.Namespace, families: dict[str, FamilyPolicy]
) -> tuple[set[str], list[str], list[str], bool, bool]:
    """Classify changed dependency entries by their declared source locations."""
    try:
        before = _inventory_entries(_base_inventory(args))
        after = _inventory_entries(Path(DEPENDENCY_INVENTORY).read_text(encoding="utf-8"))
    except (OSError, subprocess.CalledProcessError, ValueError, yaml.YAMLError):
        return set(), [], [], True, True
    profiles: set[str] = set()
    affected: list[str] = []
    keys: list[str] = []
    requires_fast_lane = False
    for key in sorted(set(before) | set(after)):
        previous = before.get(key)
        current = after.get(key)
        if previous == current:
            continue
        keys.append(key)
        previous_locations = previous[1] if previous is not None else []
        current_locations = current[1] if current is not None else []
        locations = sorted(set(previous_locations) | set(current_locations))
        if not locations:
            requires_fast_lane = True
            continue
        affected.extend(locations)
        entry_profiles: set[str] = set()
        for location in locations:
            for policy in families.values():
                if any(_matches(location, prefix) for prefix in policy["path_prefixes"]):
                    entry_profiles.update(policy["profiles"])
        if not entry_profiles:
            # A declared dependency location outside a central family is still
            # source impact. Validate it in the unprivileged Fast Lane only.
            requires_fast_lane = True
        profiles.update(entry_profiles)
    return profiles, sorted(set(affected)), keys, False, requires_fast_lane


def select(args: argparse.Namespace) -> dict[str, object]:
    families, safe_fast_lane_prefixes = _registry(args.registry)
    full_matrix = (
        args.event_name == "workflow_dispatch"
        or (
            args.event_name == "push" and (args.head_ref == "refs/heads/main" or args.head_ref.startswith("refs/tags/"))
        )
        or (
            args.event_name == "pull_request"
            and args.base_ref == "main"
            and (args.head_ref == "develop" or args.head_ref.startswith("release/v"))
        )
    )
    indeterminate_push = args.event_name == "push" and args.base_sha == ZERO_SHA
    changed_files = _normalized_paths(args.changed_file)
    if not changed_files and not full_matrix and not indeterminate_push:
        changed_files = _git_changed_files(args.base_sha, args.head_sha)

    direct_files = [path for path in changed_files if path != DEPENDENCY_INVENTORY]
    affected_by_family = {
        name: [path for path in direct_files if any(_matches(path, prefix) for prefix in policy["path_prefixes"])]
        for name, policy in families.items()
    }
    selected_profiles = {
        profile for name, paths in affected_by_family.items() if paths for profile in families[name]["profiles"]
    }
    dependency_files: list[str] = []
    dependency_keys: list[str] = []
    dependency_unknown = False
    dependency_requires_fast_lane = False
    if DEPENDENCY_INVENTORY in changed_files and not full_matrix and not indeterminate_push:
        (
            dependency_profiles,
            dependency_files,
            dependency_keys,
            dependency_unknown,
            dependency_requires_fast_lane,
        ) = _dependency_impact(args, families)
        selected_profiles.update(dependency_profiles)

    unknown_files = [
        path
        for path in direct_files
        if not any(path in files for files in affected_by_family.values())
        and not any(_matches(path, prefix) for prefix in safe_fast_lane_prefixes)
    ]
    unknown_impact = bool(unknown_files) or dependency_unknown
    if full_matrix or indeterminate_push:
        selected_profiles = set(PROFILES)
    elif unknown_impact or dependency_requires_fast_lane:
        # Unknown source remains safe on an unprivileged runner; it must not
        # create a privileged Heavy or application-acceptance PR execution.
        selected_profiles.add("tiny")

    profiles = {profile: profile in selected_profiles for profile in sorted(PROFILES)}
    affected_files = sorted({path for paths in affected_by_family.values() for path in paths} | set(dependency_files))
    if full_matrix:
        reason = "complete protected validation event"
    elif indeterminate_push:
        reason = "push base is unavailable; fail closed to complete validation"
    elif unknown_impact:
        reason = "unclassified change; fail closed to the unprivileged Tiny Fast Lane"
    elif affected_files:
        reason = "declared quality family or dependency location changed"
    else:
        reason = "no registered quality family or dependency location changed"

    return {
        "schema_version": 2,
        "scope": "independent-quality-profiles",
        "full_matrix": full_matrix or indeterminate_push,
        "unknown_impact": unknown_impact,
        # Compatibility output for external consumers. New workflow guards
        # use the independent profile values below.
        "keycloak_required": all(profiles.values()),
        "profiles": profiles,
        "runtime_evidence_required": profiles["heavy"] or profiles["application_acceptance"],
        "families": {name: bool(paths) for name, paths in affected_by_family.items()},
        "changed_files": changed_files,
        "affected_files": affected_files,
        "dependency_keys": dependency_keys,
        "unknown_files": unknown_files,
        "reason": reason,
    }


def main() -> int:
    args = _parser().parse_args()
    print(json.dumps(select(args), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
