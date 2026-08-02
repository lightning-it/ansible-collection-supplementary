"""Fail-closed validator for the centrally managed quality-policy contract."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re
import sys
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - CI installs PyYAML.
    raise SystemExit("PyYAML is required: python3 -m pip install PyYAML") from exc


SCHEMA_VERSION = 1
PROFILE_NAMES = (
    "Static",
    "Build",
    "Unit",
    "Contract",
    "Tiny",
    "Heavy",
    "Application Acceptance",
)
FAST_PROFILES = PROFILE_NAMES[:5]
CENTRAL_PROFILES = PROFILE_NAMES[5:]
REQUIRED_ADRS = {
    "https://wiki.cloud.l-it.io/wiki/spaces/LIT/pages/2886566105",
    "https://wiki.cloud.l-it.io/wiki/spaces/LIT/pages/2886926524",
    "https://wiki.cloud.l-it.io/wiki/spaces/LIT/pages/2893119515",
}
PROFILE_FIELDS = {"owner", "executor", "triggers", "blocking", "evidence"}
EVIDENCE_FIELDS = {"kind", "candidate_bound", "retention_days"}
EXCEPTION_FIELDS = {
    "control_id",
    "reason",
    "owner",
    "approver",
    "adr",
    "compensating_controls",
    "start",
    "expires",
    "review",
}
CONTROL_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")


def as_mapping(value: Any, path: str, errors: list[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"{path} must be a mapping")
        return None
    return value


def exact_keys(value: dict[str, Any], expected: set[str], path: str, errors: list[str]) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        errors.append(f"{path} is missing required keys: {', '.join(missing)}")
    if unknown:
        errors.append(f"{path} contains unsupported keys: {', '.join(unknown)}")


def string(value: Any, path: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path} must be a non-empty string")
        return None
    return value


def boolean(value: Any, path: str, errors: list[str]) -> bool | None:
    if not isinstance(value, bool):
        errors.append(f"{path} must be a boolean")
        return None
    return value


def string_list(value: Any, path: str, errors: list[str]) -> list[str] | None:
    if not isinstance(value, list) or not value:
        errors.append(f"{path} must be a non-empty list")
        return None
    if any(not isinstance(item, str) or not item.strip() for item in value):
        errors.append(f"{path} must contain only non-empty strings")
        return None
    if len(value) != len(set(value)):
        errors.append(f"{path} must not contain duplicate values")
    return value


def validate_profile(name: str, profile: Any, errors: list[str]) -> None:
    path = f"profiles.{name}"
    value = as_mapping(profile, path, errors)
    if value is None:
        return
    exact_keys(value, PROFILE_FIELDS, path, errors)
    owner = string(value.get("owner"), f"{path}.owner", errors)
    executor = string(value.get("executor"), f"{path}.executor", errors)
    triggers = string_list(value.get("triggers"), f"{path}.triggers", errors)
    blocking = as_mapping(value.get("blocking"), f"{path}.blocking", errors)
    evidence = as_mapping(value.get("evidence"), f"{path}.evidence", errors)

    if owner not in {"source-repository", "modulix-validation"}:
        errors.append(f"{path}.owner must be source-repository or modulix-validation")
    if executor not in {"source-repository", "modulix-validation"}:
        errors.append(f"{path}.executor must be source-repository or modulix-validation")
    if triggers is not None and not set(triggers) <= {"pull_request", "nightly", "manual"}:
        errors.append(f"{path}.triggers contains an unsupported trigger")

    if blocking is not None:
        exact_keys(blocking, {"develop", "main"}, f"{path}.blocking", errors)
        for branch in ("develop", "main"):
            boolean(blocking.get(branch), f"{path}.blocking.{branch}", errors)

    if evidence is not None:
        exact_keys(evidence, EVIDENCE_FIELDS, f"{path}.evidence", errors)
        kind = string(evidence.get("kind"), f"{path}.evidence.kind", errors)
        candidate_bound = boolean(
            evidence.get("candidate_bound"), f"{path}.evidence.candidate_bound", errors
        )
        retention_days = evidence.get("retention_days")
        if (
            isinstance(retention_days, bool)
            or not isinstance(retention_days, int)
            or retention_days < 1
        ):
            errors.append(f"{path}.evidence.retention_days must be an integer >= 1")
        if kind not in {"source-check", "central-validation"}:
            errors.append(f"{path}.evidence.kind must be source-check or central-validation")

        if name in FAST_PROFILES and (kind != "source-check" or candidate_bound is not False):
            errors.append(f"{path} must retain independent source-check evidence")
        if name in CENTRAL_PROFILES and (kind != "central-validation" or candidate_bound is not True):
            errors.append(f"{path} must retain exact candidate-bound central evidence")

    if name in FAST_PROFILES:
        if owner != "source-repository" or executor != "source-repository":
            errors.append(f"{path} must be owned and executed by source-repository")
        if triggers is not None and triggers != ["pull_request"]:
            errors.append(f"{path}.triggers must be exactly [pull_request]")
        if blocking is not None and blocking != {"develop": True, "main": True}:
            errors.append(f"{path}.blocking must block develop and main")
    else:
        if owner != "modulix-validation" or executor != "modulix-validation":
            errors.append(f"{path} must be owned and executed by modulix-validation")
        if triggers is not None and triggers != ["nightly", "manual"]:
            errors.append(f"{path}.triggers must be exactly [nightly, manual]; pull_request is forbidden")
        if blocking is not None and blocking != {"develop": False, "main": False}:
            errors.append(f"{path}.blocking must not directly block branches; Release Evidence does")


def validate_aggregate(branch: str, aggregate: Any, errors: list[str]) -> None:
    path = f"policy.branch_aggregates.{branch}"
    value = as_mapping(aggregate, path, errors)
    if value is None:
        return
    exact_keys(value, {"name", "profiles", "evidence_verifier"}, path, errors)
    name = string(value.get("name"), f"{path}.name", errors)
    profiles = string_list(value.get("profiles"), f"{path}.profiles", errors)
    verifier = boolean(value.get("evidence_verifier"), f"{path}.evidence_verifier", errors)
    if name not in {"Collection / Fast", "Collection / Release Evidence"}:
        errors.append(f"{path}.name is not a supported aggregate")
    if profiles is not None and not set(profiles) <= set(PROFILE_NAMES):
        errors.append(f"{path}.profiles references an unsupported profile")
    if name == "Collection / Fast":
        if profiles != list(FAST_PROFILES) or verifier is not False:
            errors.append(f"{path} must aggregate all Fast profiles without an evidence verifier")
    if name == "Collection / Release Evidence":
        if profiles != list(CENTRAL_PROFILES) or verifier is not True:
            errors.append(f"{path} must verify Heavy and Application Acceptance evidence")


def validate_exceptions(value: Any, errors: list[str], today: date | None) -> None:
    if not isinstance(value, list):
        errors.append("exceptions must be a list")
        return
    for index, exception in enumerate(value):
        path = f"exceptions[{index}]"
        item = as_mapping(exception, path, errors)
        if item is None:
            continue
        exact_keys(item, EXCEPTION_FIELDS, path, errors)
        control_id = string(item.get("control_id"), f"{path}.control_id", errors)
        if control_id is not None and not CONTROL_ID.fullmatch(control_id):
            errors.append(f"{path}.control_id must match {CONTROL_ID.pattern}")
        for field in ("reason", "owner", "approver"):
            string(item.get(field), f"{path}.{field}", errors)
        adr = string(item.get("adr"), f"{path}.adr", errors)
        if adr is not None and not adr.startswith("https://"):
            errors.append(f"{path}.adr must be an https URL")
        string_list(item.get("compensating_controls"), f"{path}.compensating_controls", errors)
        parsed_dates: dict[str, date] = {}
        for field in ("start", "review", "expires"):
            item_value = string(item.get(field), f"{path}.{field}", errors)
            if item_value is None:
                continue
            try:
                parsed_dates[field] = date.fromisoformat(item_value)
            except ValueError:
                errors.append(f"{path}.{field} must be an ISO-8601 date")
        if len(parsed_dates) == 3 and not (
            parsed_dates["start"] <= parsed_dates["review"] <= parsed_dates["expires"]
        ):
            errors.append(f"{path} must satisfy start <= review <= expires")
        if today is not None:
            review = parsed_dates.get("review")
            expires = parsed_dates.get("expires")
            if review is not None and review < today:
                errors.append(f"{path}.review is overdue as of {today.isoformat()}")
            if expires is not None and expires < today:
                errors.append(f"{path}.expires is expired as of {today.isoformat()}")


def validate_policy(data: Any, *, today: date | None = None) -> list[str]:
    """Return every contract violation without accepting unknown policy shape."""
    errors: list[str] = []
    root = as_mapping(data, "root", errors)
    if root is None:
        return errors
    exact_keys(
        root,
        {"schema_version", "lifecycle", "archetype", "policy", "profiles", "exceptions"},
        "root",
        errors,
    )
    if root.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    lifecycle = string(root.get("lifecycle"), "lifecycle", errors)
    if lifecycle != "active":
        errors.append("lifecycle must be active; inactive repositories are outside this contract")
    archetype = string(root.get("archetype"), "archetype", errors)
    if archetype != "ansible-collection":
        errors.append("archetype must be ansible-collection")

    policy = as_mapping(root.get("policy"), "policy", errors)
    if policy is not None:
        exact_keys(policy, {"max_age_hours", "related_adrs", "branch_aggregates"}, "policy", errors)
        max_age_hours = policy.get("max_age_hours")
        if (
            isinstance(max_age_hours, bool)
            or not isinstance(max_age_hours, int)
            or not 1 <= max_age_hours <= 36
        ):
            errors.append("policy.max_age_hours must be an integer from 1 through 36")
        adrs = string_list(policy.get("related_adrs"), "policy.related_adrs", errors)
        if adrs is not None:
            missing_adrs = sorted(REQUIRED_ADRS - set(adrs))
            if missing_adrs:
                errors.append("policy.related_adrs is missing: " + ", ".join(missing_adrs))
            if any(not adr.startswith("https://") for adr in adrs):
                errors.append("policy.related_adrs must contain only https URLs")
        aggregates = as_mapping(policy.get("branch_aggregates"), "policy.branch_aggregates", errors)
        if aggregates is not None:
            exact_keys(aggregates, {"develop", "main"}, "policy.branch_aggregates", errors)
            for branch in ("develop", "main"):
                entries = aggregates.get(branch)
                if not isinstance(entries, list):
                    errors.append(f"policy.branch_aggregates.{branch} must be a list")
                    continue
                for entry in entries:
                    validate_aggregate(branch, entry, errors)
                expected_names = ["Collection / Fast"] if branch == "develop" else ["Collection / Fast", "Collection / Release Evidence"]
                names = [entry.get("name") for entry in entries if isinstance(entry, dict)]
                if names != expected_names:
                    errors.append(f"policy.branch_aggregates.{branch} must be exactly {expected_names}")

    profiles = as_mapping(root.get("profiles"), "profiles", errors)
    if profiles is not None:
        exact_keys(profiles, set(PROFILE_NAMES), "profiles", errors)
        for name in PROFILE_NAMES:
            validate_profile(name, profiles.get(name), errors)
    validate_exceptions(root.get("exceptions"), errors, today)
    return errors


def load_policy(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read valid YAML from {path}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path, help="Path to quality-policy.yml")
    args = parser.parse_args()
    try:
        errors = validate_policy(load_policy(args.policy), today=date.today())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"quality policy is valid: {args.policy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
