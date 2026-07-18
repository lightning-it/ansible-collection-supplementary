#!/usr/bin/env python3
"""Select protected quality profiles from the reviewed Git change set."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import PurePosixPath


ZERO_SHA = "0" * 40
SHA = re.compile(r"^[0-9a-f]{40}$")

# First rollout: the registry interface is generic, but only the Keycloak
# quality family is registered. Other collection roles remain on basic/static
# gates until their real Tiny/Heavy/Acceptance scenarios are ready.
KEYCLOAK_PATH_PREFIXES = (
    ".github/actions/run-quality-profile/",
    ".github/workflows/collection-ci.yml",
    ".lit/repository.yml",
    "containerfiles/ldap/",
    "docs/testing/evidence-manifest.schema.json",
    "docs/testing/generated/role-coverage-matrix.json",
    "meta/role-coverage.yml",
    "meta/source-dependencies.yml",
    "molecule/keycloak-",
    "molecule/shared/incus/",
    "molecule/shared/keycloak/",
    "roles/keycloak_",
    "roles/postgres_backup_restore/",
    "roles/postgres_deploy/",
    "roles/samba/",
    "roles/samba_",
    "scripts/quality_evidence.py",
    "scripts/select-quality-impact.py",
    "scripts/source_dependencies.py",
    "scripts/validate-role-coverage.py",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--base-sha", default="")
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--base-ref", default="")
    parser.add_argument("--head-ref", default="")
    parser.add_argument("--execution-mode", default="")
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


def _keycloak_affected(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix) for prefix in KEYCLOAK_PATH_PREFIXES)


def select(args: argparse.Namespace) -> dict[str, object]:
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

    affected_files = [path for path in changed_files if _keycloak_affected(path)]
    keycloak_required = full_matrix or indeterminate_push or bool(affected_files)
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
