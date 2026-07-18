#!/usr/bin/env python3
"""Select protected quality profiles from the reviewed Git change set."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from pathlib import PurePosixPath
from typing import TypedDict

import yaml


ZERO_SHA = "0" * 40
SHA = re.compile(r"^[0-9a-f]{40}$")

PROFILES = {"tiny", "heavy", "application_acceptance"}


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


def _registry(path: str) -> dict[str, FamilyPolicy]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("quality impact registry must use schema version 1")
    families = payload.get("families")
    if not isinstance(families, dict) or not families:
        raise ValueError("quality impact registry must declare at least one family")
    normalized: dict[str, FamilyPolicy] = {}
    for name, policy in families.items():
        if not isinstance(name, str) or not isinstance(policy, dict):
            raise ValueError("quality impact family entries must be mappings")
        profiles = policy.get("profiles")
        prefixes = policy.get("path_prefixes")
        if not isinstance(profiles, list) or set(profiles) - PROFILES:
            raise ValueError(f"quality impact family {name!r} has unsupported profiles")
        if not isinstance(prefixes, list) or not prefixes or not all(isinstance(item, str) for item in prefixes):
            raise ValueError(f"quality impact family {name!r} requires path prefixes")
        normalized[name] = {"profiles": profiles, "path_prefixes": prefixes}
    return normalized


def select(args: argparse.Namespace) -> dict[str, object]:
    registry = _registry(args.registry)
    full_matrix = (
        args.event_name == "workflow_dispatch"
        or (
            args.event_name == "push"
            and (args.head_ref == "refs/heads/main" or args.head_ref.startswith("refs/tags/"))
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

    affected_by_family = {
        name: [
            path
            for path in changed_files
            if any(path == prefix or path.startswith(prefix) for prefix in policy["path_prefixes"])
        ]
        for name, policy in registry.items()
    }
    family_required = {
        name: full_matrix or indeterminate_push or bool(paths)
        for name, paths in affected_by_family.items()
    }
    keycloak_required = family_required.get("keycloak", False)
    affected_files = sorted({path for paths in affected_by_family.values() for path in paths})
    if full_matrix:
        reason = "complete protected validation event"
    elif indeterminate_push:
        reason = "push base is unavailable; fail closed to complete validation"
    elif affected_files:
        reason = "Keycloak quality family or dependency changed"
    else:
        reason = "no Keycloak quality family paths changed"

    return {
        "schema_version": 1,
        "scope": "keycloak-only",
        "full_matrix": full_matrix or indeterminate_push,
        "keycloak_required": keycloak_required,
        "families": family_required,
        "profiles": {
            "tiny": keycloak_required,
            "heavy": keycloak_required,
            "application_acceptance": keycloak_required,
        },
        "changed_files": changed_files,
        "affected_files": affected_files,
        "reason": reason,
    }


def main() -> int:
    args = _parser().parse_args()
    print(json.dumps(select(args), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
