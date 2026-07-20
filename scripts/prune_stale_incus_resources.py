"""Remove unused Incus resources owned by superseded runs of this repository."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from functools import lru_cache
from typing import Any

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
NETWORK_RE = re.compile(r"^lit[0-9a-f]{12}$")
OWNER_KEY = "user.lit-molecule-owner"
REPOSITORY_KEY = "user.lit-molecule-repository"
RUN_ID_KEY = "user.lit-molecule-run-id"


@lru_cache(maxsize=1)
def incus_executable() -> str:
    executable = shutil.which("incus")
    if executable is None:
        raise FileNotFoundError("incus is not available on PATH")
    return executable


def incus(*arguments: str, capture: bool = True) -> str:
    result = subprocess.run(  # noqa: S603 - argv is validated and never invokes a shell.
        [incus_executable(), *arguments],
        check=True,
        capture_output=capture,
        text=True,
    )
    return result.stdout or ""


def exact_owner(config: dict[str, Any], repository: str, current_run_id: str) -> bool:
    run_id = str(config.get(RUN_ID_KEY, ""))
    return (
        config.get(REPOSITORY_KEY) == repository
        and bool(config.get(OWNER_KEY))
        and RUN_ID_RE.fullmatch(run_id) is not None
        and run_id != current_run_id
    )


def revalidate(kind: str, name: str, repository: str, current_run_id: str) -> bool:
    try:
        values = {key: incus(kind, "get", name, key).strip() for key in (REPOSITORY_KEY, RUN_ID_KEY, OWNER_KEY)}
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return exact_owner(values, repository, current_run_id)


def delete_if_present(name: str, *delete_arguments: str, list_kind: str) -> None:
    list_arguments_by_kind = {
        "instance": ("list", "--format", "json"),
        "network": ("network", "list", "--format", "json"),
    }
    if list_kind not in list_arguments_by_kind:
        raise ValueError(f"unsupported Incus resource kind: {list_kind}")

    try:
        incus(*delete_arguments, capture=False)
    except subprocess.CalledProcessError:
        list_arguments = list_arguments_by_kind[list_kind]
        current = json.loads(incus(*list_arguments))
        if any(str(item.get("name", "")) == name for item in current):
            raise


def prune(repository: str, current_run_id: str) -> None:
    instances = json.loads(incus("list", "--format", "json"))
    for instance in instances:
        name = str(instance.get("name", ""))
        config = instance.get("config", {})
        if not name or not isinstance(config, dict):
            continue
        if exact_owner(config, repository, current_run_id) and revalidate("config", name, repository, current_run_id):
            delete_if_present(
                name,
                "delete",
                "--force",
                name,
                list_kind="instance",
            )

    networks = json.loads(incus("network", "list", "--format", "json"))
    for network in networks:
        name = str(network.get("name", ""))
        config = network.get("config", {})
        used_by = network.get("used_by", [])
        if NETWORK_RE.fullmatch(name) is None or not isinstance(config, dict) or used_by:
            continue
        if exact_owner(config, repository, current_run_id) and revalidate("network", name, repository, current_run_id):
            refreshed = json.loads(incus("network", "list", "--format", "json"))
            current = next((item for item in refreshed if item.get("name") == name), None)
            if (
                current is not None
                and not current.get("used_by", [])
                and exact_owner(current.get("config", {}), repository, current_run_id)
            ):
                delete_if_present(
                    name,
                    "network",
                    "delete",
                    name,
                    list_kind="network",
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--current-run-id", required=True)
    args = parser.parse_args()
    if REPOSITORY_RE.fullmatch(args.repository) is None:
        parser.error("repository must be an owner/name slug")
    if RUN_ID_RE.fullmatch(args.current_run_id) is None:
        parser.error("current run ID must be a positive integer")
    prune(args.repository, args.current_run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
