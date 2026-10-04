"""Validate exact GitHub concurrency queues before actionlint's narrow schema ignore.

Actionlint 1.7.12 predates GitHub's ``concurrency.queue: max`` syntax. This
validator permits only queue locations and literal values bound by the protected
repository manifest; all other queue uses fail before actionlint runs.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode

WORKFLOW = re.compile(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml")
JOB = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def parse_locations(policy: dict) -> dict[tuple[str, tuple[str, ...]], str]:
    if (
        set(policy) != {"version", "locations"}
        or type(policy["version"]) is not int
        or policy["version"] != 1
    ):
        raise ValueError("invalid queue policy schema or version")
    if not isinstance(policy["locations"], dict) or not policy["locations"]:
        raise ValueError("queue policy locations must be a nonempty object")
    result: dict[tuple[str, tuple[str, ...]], str] = {}
    for location, group in policy["locations"].items():
        if not isinstance(location, str) or location.count("#") != 1:
            raise ValueError("invalid queue location")
        filename, dotted_path = location.split("#")
        if not WORKFLOW.fullmatch(filename):
            raise ValueError(f"invalid queue workflow path: {filename}")
        parts = tuple(dotted_path.split("."))
        if parts != ("concurrency",) and not (
            len(parts) == 3
            and parts[0] == "jobs"
            and JOB.fullmatch(parts[1])
            and parts[2] == "concurrency"
        ):
            raise ValueError(f"invalid queue mapping path: {dotted_path}")
        if (
            not isinstance(group, str)
            or not 1 <= len(group) <= 256
            or any(ord(char) < 32 or ord(char) == 127 for char in group)
        ):
            raise ValueError(f"invalid queue group: {location}")
        result[(filename, parts)] = group
    return result


def mapping_fields(node: MappingNode, path: Path) -> dict[str, Node]:
    fields: dict[str, Node] = {}
    for key_node, value_node in node.value:
        if not isinstance(key_node, ScalarNode) or key_node.value == "<<":
            raise ValueError(f"invalid workflow mapping key: {path}")
        key = key_node.value
        if key in fields:
            raise ValueError(f"duplicate workflow mapping key {key}: {path}")
        fields[key] = value_node
    return fields


def concurrency_mappings(path: Path) -> dict[tuple[str, ...], dict[str, Node]]:
    try:
        root = yaml.compose(path.read_text(encoding="utf-8"), Loader=yaml.SafeLoader)
    except (yaml.YAMLError, UnicodeError) as error:
        raise ValueError(f"invalid workflow YAML: {path}") from error
    if not isinstance(root, MappingNode):
        raise TypeError(f"workflow root must be a mapping: {path}")
    top = mapping_fields(root, path)
    mappings: dict[tuple[str, ...], dict[str, Node]] = {}
    workflow_concurrency = top.get("concurrency")
    if isinstance(workflow_concurrency, MappingNode):
        mappings[("concurrency",)] = mapping_fields(workflow_concurrency, path)
    jobs = top.get("jobs")
    if isinstance(jobs, MappingNode):
        for job, job_node in mapping_fields(jobs, path).items():
            if not isinstance(job_node, MappingNode):
                continue
            concurrency = mapping_fields(job_node, path).get("concurrency")
            if isinstance(concurrency, MappingNode):
                mappings[("jobs", job, "concurrency")] = mapping_fields(
                    concurrency, path
                )
    return mappings


def validate(root: Path) -> None:
    policy_path = root / ".github/workflow-queue-policy.json"
    workflow_dir = root / ".github/workflows"
    if (
        policy_path.is_symlink()
        or policy_path.parent.is_symlink()
        or not policy_path.is_file()
        or workflow_dir.is_symlink()
        or workflow_dir.parent.is_symlink()
        or not workflow_dir.is_dir()
    ):
        raise ValueError("queue policy and workflow directory must be regular")
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as error:
        raise ValueError("queue policy must be valid UTF-8 JSON with unique keys") from error
    if not isinstance(policy, dict):
        raise TypeError("queue policy must be an object")
    expected = parse_locations(policy)
    actual: set[tuple[str, tuple[str, ...]]] = set()
    for workflow in sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml"))):
        if workflow.is_symlink() or not workflow.is_file():
            raise ValueError(f"workflow must be a regular file: {workflow.name}")
        relative = workflow.relative_to(root).as_posix()
        for path, fields in concurrency_mappings(workflow).items():
            if "queue" not in fields:
                continue
            location = (relative, path)
            actual.add(location)
            group = expected.get(location)
            if group is None:
                raise ValueError(f"undeclared queue: {relative}#{'.'.join(path)}")
            values = {
                key: value.value if isinstance(value, ScalarNode) else None
                for key, value in fields.items()
            }
            if values != {
                "group": group,
                "queue": "max",
                "cancel-in-progress": "false",
            }:
                raise ValueError(f"queue mapping differs from policy: {relative}#{'.'.join(path)}")
    if actual != set(expected):
        raise ValueError("queue policy contains missing or stale workflow locations")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    validate(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
