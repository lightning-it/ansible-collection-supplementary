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
# Bound the per-run read independently of the filtered workflow-run API cap.
MAX_JOBS_PER_RUN = 999
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


def _is_json_int(value: Any) -> bool:
    """Reject booleans, which Python otherwise treats as integers."""
    return isinstance(value, int) and not isinstance(value, bool)


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


def _read_job_page(repository: str, run_id: int, page: int) -> dict[str, Any]:
    endpoint = f"repos/{repository}/actions/runs/{run_id}/jobs?per_page={PAGE_SIZE}&page={page}"
    gh_binary = shutil.which("gh")
    if gh_binary is None:
        raise IncompleteInventory("GitHub CLI is unavailable")
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
        raise IncompleteInventory("invalid jobs API JSON") from exc
    if not isinstance(value, dict):
        raise IncompleteInventory("invalid jobs page shape")
    return value


def collect_waiting_runs(fetch_page: Callable[[int], dict[str, Any]], workflow_id: int) -> dict[str, Any]:
    if not _is_json_int(workflow_id) or workflow_id <= 0:
        raise ValueError("workflow_id must be a positive integer")

    first_page = fetch_page(1)
    total = first_page.get("total_count")
    if not _is_json_int(total) or not 0 <= total <= MAX_PROVABLE_TOTAL:
        raise IncompleteInventory("unprovable total_count")
    page_count = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    pages = [first_page] + [fetch_page(page) for page in range(2, page_count + 1)]
    seen: set[int] = set()
    runs: list[dict[str, Any]] = []

    for number, page in enumerate(pages, 1):
        if page.get("total_count") != total:
            raise IncompleteInventory("total_count changed between pages")
        batch = page.get("workflow_runs")
        expected = min(PAGE_SIZE, max(0, total - (number - 1) * PAGE_SIZE))
        if not isinstance(batch, list) or len(batch) != expected:
            raise IncompleteInventory("missing or oversized result page")
        for run in batch:
            if not isinstance(run, dict):
                raise IncompleteInventory("invalid run shape")
            run_id = run.get("id")
            if not _is_json_int(run_id) or run_id <= 0 or run_id in seen:
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
                if not isinstance(pr, dict) or not _is_json_int(pr.get("number")):
                    raise IncompleteInventory("invalid PR association")
                pr_numbers.append(pr["number"])
            attempt = run.get("run_attempt")
            if not _is_json_int(attempt) or attempt <= 0:
                raise IncompleteInventory("invalid run attempt")
            seen.add(run_id)
            runs.append(
                {
                    "id": run_id,
                    "status": "waiting",
                    "event": run["event"],
                    "head_branch": run["head_branch"],
                    "head_sha": head_sha,
                    "created_at": run["created_at"],
                    "updated_at": run["updated_at"],
                    "run_attempt": attempt,
                    "actor": actor["login"],
                    "pull_request_numbers": pr_numbers,
                    "disposition": "unclassified",
                }
            )

    if len(runs) != total:
        raise IncompleteInventory("result count does not match total")
    # A concurrent insertion/removal can move runs between pages without
    # changing total_count. Check every page again before trusting the snapshot.
    for number, expected_page in enumerate(pages, 1):
        again = fetch_page(number)
        if again != expected_page:
            raise IncompleteInventory("result page changed during inventory")

    return {
        "workflow_id": workflow_id,
        "total_count": total,
        "page_count": page_count,
        "runs": runs,
        "caveat": "Read-only inventory; no run is classified safe to cancel.",
    }


def collect_waiting_jobs(
    run_inventory: dict[str, Any],
    fetch_page: Callable[[int, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bind complete native job pages to each run without inferring disposition."""
    runs = run_inventory.get("runs")
    if (
        not isinstance(runs, list)
        or not _is_json_int(run_inventory.get("total_count"))
        or run_inventory["total_count"] != len(runs)
    ):
        raise IncompleteInventory("invalid parent run inventory")
    seen_jobs: set[int] = set()
    result: list[dict[str, Any]] = []
    for run in runs:
        if not isinstance(run, dict):
            raise IncompleteInventory("invalid parent run")
        run_id = run.get("id")
        attempt = run.get("run_attempt")
        head_sha = run.get("head_sha")
        if (
            not _is_json_int(run_id)
            or run_id <= 0
            or not _is_json_int(attempt)
            or attempt <= 0
            or not isinstance(head_sha, str)
            or not SHA.fullmatch(head_sha)
        ):
            raise IncompleteInventory("invalid parent run identity")
        first_page = fetch_page(run_id, 1)
        total = first_page.get("total_count")
        if not _is_json_int(total) or not 1 <= total <= MAX_JOBS_PER_RUN:
            raise IncompleteInventory("unprovable job count")
        page_count = (total + PAGE_SIZE - 1) // PAGE_SIZE
        pages = [first_page] + [fetch_page(run_id, page) for page in range(2, page_count + 1)]
        page_jobs: list[list[dict[str, Any]]] = []
        jobs: list[dict[str, Any]] = []
        for number, page in enumerate(pages, 1):
            if page.get("total_count") != total:
                raise IncompleteInventory("job count changed between pages")
            batch = page.get("jobs")
            expected = min(PAGE_SIZE, total - (number - 1) * PAGE_SIZE)
            if not isinstance(batch, list) or len(batch) != expected:
                raise IncompleteInventory("missing or oversized jobs page")
            for job in batch:
                if not isinstance(job, dict):
                    raise IncompleteInventory("invalid job shape")
                job_id = job.get("id")
                if not _is_json_int(job_id) or job_id <= 0 or job_id in seen_jobs:
                    raise IncompleteInventory("invalid or duplicate job ID")
                if not _is_json_int(job.get("run_id")) or not _is_json_int(job.get("run_attempt")):
                    raise IncompleteInventory("invalid job run identity")
                if job.get("run_id") != run_id or job.get("run_attempt") != attempt or job.get("head_sha") != head_sha:
                    raise IncompleteInventory("job belongs to another run or revision")
                if not isinstance(job.get("name"), str) or not job["name"]:
                    raise IncompleteInventory("missing job name")
                if not isinstance(job.get("status"), str) or job["status"] not in {
                    "waiting",
                    "requested",
                    "queued",
                    "pending",
                    "in_progress",
                    "completed",
                }:
                    raise IncompleteInventory("invalid job status")
                if job.get("conclusion") is not None and not isinstance(job["conclusion"], str):
                    raise IncompleteInventory("invalid job conclusion")
                steps = job.get("steps")
                if not isinstance(steps, list):
                    raise IncompleteInventory("missing job steps inventory")
                seen_jobs.add(job_id)
                jobs.append(
                    {
                        "id": job_id,
                        "name": job["name"],
                        "status": job["status"],
                        "conclusion": job["conclusion"],
                        "step_count": len(steps),
                    }
                )
            page_jobs.append(batch)
        for number, expected_jobs in enumerate(page_jobs, 1):
            again = fetch_page(run_id, number)
            again_jobs = again.get("jobs")
            if again.get("total_count") != total or not isinstance(again_jobs, list) or again_jobs != expected_jobs:
                raise IncompleteInventory("jobs page changed during inventory")
        result.append({"run_id": run_id, "total_jobs": total, "jobs": jobs})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-id", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-jobs", action="store_true")
    arguments = parser.parse_args()
    if not REPOSITORY.fullmatch(arguments.repository):
        parser.error("invalid repository")
    inventory = collect_waiting_runs(
        lambda page: _read_page(arguments.repository, arguments.workflow_id, page),
        arguments.workflow_id,
    )
    if arguments.include_jobs:
        jobs = collect_waiting_jobs(
            inventory,
            lambda run_id, page: _read_job_page(arguments.repository, run_id, page),
        )
        if (
            collect_waiting_runs(
                lambda page: _read_page(arguments.repository, arguments.workflow_id, page),
                arguments.workflow_id,
            )
            != inventory
        ):
            raise IncompleteInventory("parent run inventory changed during jobs inventory")
        inventory["job_inventory"] = jobs
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
