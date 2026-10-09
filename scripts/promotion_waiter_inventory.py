"""Fail-closed, read-only inventory of one promotion workflow's waiting runs.

This is an inventory boundary, not a cancellation or admission authority. GitHub
run metadata does not by itself bind a candidate, pull request, operation record,
or safe terminal disposition.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PAGE_SIZE = 100
# GitHub's filtered workflow-run inventory can stop at 1,000 results. Treat a
# boundary-sized result as incomplete rather than guessing whether more exist.
MAX_PROVABLE_TOTAL = 999
SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class IncompleteInventory(ValueError):
    """The API response does not prove a complete, stable run inventory."""


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IncompleteInventory(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _read_page(repository: str, workflow_id: int, page: int) -> dict[str, Any]:
    endpoint = (
        f"repos/{repository}/actions/workflows/{workflow_id}/runs?status=waiting&per_page={PAGE_SIZE}&page={page}"
    )
    gh_binary = shutil.which("gh")
    if gh_binary is None:
        raise IncompleteInventory("GitHub CLI is unavailable")
    # Fixed CLI and verb, validated repository and integer ID, no shell.
    completed = subprocess.run(  # noqa: S603
        [gh_binary, "api", endpoint],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    try:
        value = json.loads(completed.stdout, object_pairs_hook=_unique_json_pairs)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise IncompleteInventory("invalid API JSON") from exc
    if not isinstance(value, dict):
        raise IncompleteInventory("invalid page shape")
    return value


def collect_waiting_runs(fetch_page: Callable[[int], dict[str, Any]], workflow_id: int) -> dict[str, Any]:
    if type(workflow_id) is not int or workflow_id <= 0:
        raise ValueError("workflow_id must be a positive integer")

    first_page = fetch_page(1)
    total = first_page.get("total_count")
    if type(total) is not int or not 0 <= total <= MAX_PROVABLE_TOTAL:
        raise IncompleteInventory("unprovable total_count")
    page_count = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    pages = [first_page] + [fetch_page(page) for page in range(2, page_count + 1)]
    seen: set[int] = set()
    runs: list[dict[str, Any]] = []
    page_ids: list[list[int]] = []

    for number, page in enumerate(pages, 1):
        if page.get("total_count") != total:
            raise IncompleteInventory("total_count changed between pages")
        batch = page.get("workflow_runs")
        expected = min(PAGE_SIZE, max(0, total - (number - 1) * PAGE_SIZE))
        if not isinstance(batch, list) or len(batch) != expected:
            raise IncompleteInventory("missing or oversized result page")
        current_ids: list[int] = []
        for run in batch:
            if not isinstance(run, dict):
                raise IncompleteInventory("invalid run shape")
            run_id = run.get("id")
            if type(run_id) is not int or run_id <= 0 or run_id in seen:
                raise IncompleteInventory("invalid or duplicate run ID")
            if run.get("workflow_id") != workflow_id or run.get("status") != "waiting":
                raise IncompleteInventory("foreign workflow or non-waiting run")
            head_sha = run.get("head_sha")
            if not isinstance(head_sha, str) or not SHA.fullmatch(head_sha):
                raise IncompleteInventory("invalid head SHA")
            actor = run.get("actor")
            if not isinstance(actor, dict) or not isinstance(actor.get("login"), str):
                raise IncompleteInventory("missing actor")
            for field in ("event", "head_branch", "created_at", "updated_at"):
                if not isinstance(run.get(field), str) or not run[field]:
                    raise IncompleteInventory(f"missing {field}")
            prs = run.get("pull_requests")
            if not isinstance(prs, list):
                raise IncompleteInventory("missing PR association inventory")
            pr_numbers = []
            for pr in prs:
                if not isinstance(pr, dict) or type(pr.get("number")) is not int:
                    raise IncompleteInventory("invalid PR association")
                pr_numbers.append(pr["number"])
            seen.add(run_id)
            current_ids.append(run_id)
            runs.append(
                {
                    "id": run_id,
                    "status": "waiting",
                    "event": run["event"],
                    "head_branch": run["head_branch"],
                    "head_sha": head_sha,
                    "created_at": run["created_at"],
                    "updated_at": run["updated_at"],
                    "run_attempt": run.get("run_attempt"),
                    "actor": actor["login"],
                    "pull_request_numbers": pr_numbers,
                    "disposition": "unclassified",
                }
            )
        page_ids.append(current_ids)

    if len(runs) != total:
        raise IncompleteInventory("result count does not match total")
    # A concurrent insertion/removal can move runs between pages without
    # changing total_count. Check every page again before trusting the snapshot.
    for number, expected_ids in enumerate(page_ids, 1):
        again = fetch_page(number)
        again_runs = again.get("workflow_runs")
        if (
            again.get("total_count") != total
            or not isinstance(again_runs, list)
            or len(again_runs) != len(expected_ids)
            or any(not isinstance(run, dict) for run in again_runs)
            or [run.get("id") for run in again_runs] != expected_ids
        ):
            raise IncompleteInventory("result page changed during inventory")

    return {
        "workflow_id": workflow_id,
        "total_count": total,
        "page_count": page_count,
        "runs": runs,
        "caveat": "Read-only inventory; no run is classified safe to cancel.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-id", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if not REPOSITORY.fullmatch(arguments.repository):
        parser.error("invalid repository")
    inventory = collect_waiting_runs(
        lambda page: _read_page(arguments.repository, arguments.workflow_id, page),
        arguments.workflow_id,
    )
    inventory["repository"] = arguments.repository
    inventory["observed_at"] = datetime.now(UTC).isoformat()
    serialized = json.dumps(inventory, sort_keys=True, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=arguments.output.parent, delete=False
    ) as temporary:
        try:
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
            os.replace(temporary.name, arguments.output)
        finally:
            if os.path.exists(temporary.name):
                os.unlink(temporary.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
