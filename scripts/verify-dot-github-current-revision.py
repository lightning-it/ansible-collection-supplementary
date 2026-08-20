#!/usr/bin/env python3
"""Cross-repository verifier for the protected lightning-it/.github gate."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

SOURCE_REPOSITORY = "lightning-it/ansible-collection-supplementary"
SOURCE_WORKFLOW_PATH = (
    ".github/workflows/dot-github-current-revision-required.yml"
)
SOURCE_WORKFLOW_REF = f"{SOURCE_REPOSITORY}/{SOURCE_WORKFLOW_PATH}@refs/heads/main"
TARGET_REPOSITORY = "lightning-it/.github"
TARGET_VERIFIER_PATH = (
    ".github/workflows/supplementary-current-revision-required.yml"
)
TARGET_VERIFIER_NAME = "Required current-revision workflow"
RESERVATION_NAME = "Protected current-revision verifier"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")
RESERVATION_PATTERN = re.compile(
    r"^rep60-required-workflow:v3:(?P<run_id>[1-9][0-9]*):"
    r"(?P<pr_number>[1-9][0-9]*):(?P<base>[0-9a-f]{40}):"
    r"(?P<head>[0-9a-f]{40})$"
)
PRODUCER_ACTIONS = frozenset(
    {"opened", "synchronize", "reopened", "ready_for_review", "edited"}
)


class VerificationError(RuntimeError):
    """Raised when protected evidence is missing, stale, or ambiguous."""


class GitHubClient:
    """Minimal read-only GitHub REST client."""

    def __init__(self, token: str, api_url: str) -> None:
        if not token:
            raise VerificationError("GH_TOKEN is required")
        self._token = token
        self._api_url = api_url.rstrip("/")

    @property
    def api_url(self) -> str:
        return self._api_url

    def get(self, path: str) -> Any:
        request = urllib.request.Request(
            f"{self._api_url}/{path.lstrip('/')}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise VerificationError(
                f"GitHub API read failed: {path}: HTTP {exc.code} {exc.reason}"
            ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise VerificationError(f"GitHub API read failed: {path}") from exc


def require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise VerificationError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise VerificationError(f"{label} must be an array")
    return value


def require_sha(value: str, label: str) -> str:
    if not SHA_PATTERN.fullmatch(value):
        raise VerificationError(f"{label} must be a full lowercase SHA")
    return value


def require_positive_integer(value: str, label: str) -> int:
    if not POSITIVE_INTEGER_PATTERN.fullmatch(value):
        raise VerificationError(f"{label} must be a positive integer")
    return int(value)


def require_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise VerificationError(f"{label} is not exactly bound")


def validate_source(
    client: GitHubClient,
    workflow_ref: str,
    workflow_sha: str,
) -> None:
    require_equal(workflow_ref, SOURCE_WORKFLOW_REF, "workflow ref")
    require_sha(workflow_sha, "workflow SHA")
    repository = require_mapping(
        client.get(f"repos/{SOURCE_REPOSITORY}"), "source repository"
    )
    require_equal(repository.get("full_name"), SOURCE_REPOSITORY, "source repository")
    require_equal(repository.get("visibility"), "public", "source visibility")
    require_equal(repository.get("archived"), False, "source archive state")
    require_equal(repository.get("disabled"), False, "source disabled state")

    branch = require_mapping(
        client.get(f"repos/{SOURCE_REPOSITORY}/branches/main"),
        "source main branch",
    )
    require_equal(branch.get("name"), "main", "source branch")
    require_equal(branch.get("protected"), True, "source branch protection")
    source_head = require_sha(
        str(require_mapping(branch.get("commit"), "source commit").get("sha", "")),
        "source main head",
    )
    comparison = require_mapping(
        client.get(
            f"repos/{SOURCE_REPOSITORY}/compare/{workflow_sha}...{source_head}"
        ),
        "source ancestry comparison",
    )
    require_equal(
        require_mapping(comparison.get("base_commit"), "source base commit").get(
            "sha"
        ),
        workflow_sha,
        "source comparison base",
    )
    require_equal(
        require_mapping(
            comparison.get("merge_base_commit"), "source merge base"
        ).get("sha"),
        workflow_sha,
        "source comparison merge base",
    )
    status = comparison.get("status")
    ahead_by = comparison.get("ahead_by")
    behind_by = comparison.get("behind_by")
    if not (
        (status == "identical" and source_head == workflow_sha and ahead_by == 0)
        or (
            status == "ahead"
            and source_head != workflow_sha
            and isinstance(ahead_by, int)
            and ahead_by > 0
        )
    ) or behind_by != 0:
        raise VerificationError("workflow SHA is not trusted source-main ancestry")

    for path in (SOURCE_WORKFLOW_PATH, "scripts/verify-dot-github-current-revision.py"):
        content = require_mapping(
            client.get(f"repos/{SOURCE_REPOSITORY}/contents/{path}?ref={workflow_sha}"),
            f"source file {path}",
        )
        require_equal(content.get("type"), "file", f"source file type {path}")
        if not SHA_PATTERN.fullmatch(str(content.get("sha", ""))):
            raise VerificationError(f"source file {path} has no immutable blob")


def validate_live_pr(
    client: GitHubClient,
    pr_number: int,
    event_base: str,
    event_head: str,
) -> Mapping[str, Any]:
    repository = require_mapping(
        client.get(f"repos/{TARGET_REPOSITORY}"), "target repository"
    )
    require_equal(repository.get("full_name"), TARGET_REPOSITORY, "target repository")
    require_equal(repository.get("default_branch"), "develop", "target default branch")
    require_equal(repository.get("archived"), False, "target archive state")
    require_equal(repository.get("disabled"), False, "target disabled state")
    pr = require_mapping(
        client.get(f"repos/{TARGET_REPOSITORY}/pulls/{pr_number}"), "pull request"
    )
    require_equal(pr.get("state"), "open", "pull request state")
    require_equal(pr.get("draft"), False, "pull request draft state")
    base = require_mapping(pr.get("base"), "pull request base")
    head = require_mapping(pr.get("head"), "pull request head")
    require_equal(base.get("sha"), event_base, "live base SHA")
    require_equal(head.get("sha"), event_head, "live head SHA")
    require_equal(
        require_mapping(base.get("repo"), "base repository").get("full_name"),
        TARGET_REPOSITORY,
        "base repository",
    )
    require_equal(
        require_mapping(head.get("repo"), "head repository").get("full_name"),
        TARGET_REPOSITORY,
        "head repository",
    )
    if base.get("ref") not in {"main", "develop"}:
        raise VerificationError("pull request base branch is not protected scope")
    author = require_mapping(pr.get("user"), "pull request author").get("login")
    if not isinstance(author, str) or not author:
        raise VerificationError("pull request author is missing")
    return pr


def matching_reservations(
    client: GitHubClient, pr_number: int, event_base: str, event_head: str
) -> list[Mapping[str, Any]]:
    encoded_name = urllib.parse.quote(RESERVATION_NAME, safe="")
    payload = require_mapping(
        client.get(
            f"repos/{TARGET_REPOSITORY}/commits/{event_head}/check-runs"
            f"?check_name={encoded_name}"
            "&filter=all&per_page=100"
        ),
        "protected verifier check inventory",
    )
    checks = require_list(payload.get("check_runs"), "protected verifier checks")
    total_count = payload.get("total_count")
    if not isinstance(total_count, int) or total_count != len(checks) or total_count > 100:
        raise VerificationError("protected verifier check inventory is incomplete")
    result: list[Mapping[str, Any]] = []
    for raw_check in checks:
        check = require_mapping(raw_check, "protected verifier check")
        if check.get("name") != RESERVATION_NAME:
            continue
        match = RESERVATION_PATTERN.fullmatch(str(check.get("external_id", "")))
        if (
            match is not None
            and int(match.group("pr_number")) == pr_number
            and match.group("base") == event_base
            and match.group("head") == event_head
        ):
            result.append(check)
    return result


def wait_for_reservation(
    client: GitHubClient,
    pr_number: int,
    event_base: str,
    event_head: str,
    *,
    attempts: int,
    sleep: Callable[[float], None],
) -> Mapping[str, Any]:
    for attempt in range(1, attempts + 1):
        matches = matching_reservations(client, pr_number, event_base, event_head)
        if len(matches) > 1:
            raise VerificationError("protected verifier evidence is ambiguous")
        if len(matches) == 1:
            check = matches[0]
            if check.get("status") == "completed" and check.get("conclusion") == "success":
                return check
        if attempt < attempts:
            sleep(10)
    raise VerificationError("protected verifier evidence did not become successful")


def validate_reservation(
    client: GitHubClient,
    check: Mapping[str, Any],
    pr: Mapping[str, Any],
    pr_number: int,
    event_base: str,
    event_head: str,
    server_url: str,
) -> None:
    check_id = check.get("id")
    if not isinstance(check_id, int) or check_id <= 0:
        raise VerificationError("protected verifier check ID is invalid")
    require_equal(check.get("head_sha"), event_head, "protected verifier head")
    app = require_mapping(check.get("app"), "protected verifier App")
    require_equal(app.get("id"), 15368, "protected verifier App ID")
    require_equal(app.get("slug"), "github-actions", "protected verifier App")
    require_equal(
        check.get("details_url"),
        f"{server_url}/{TARGET_REPOSITORY}/runs/{check_id}",
        "protected verifier details URL",
    )
    match = RESERVATION_PATTERN.fullmatch(str(check.get("external_id", "")))
    if match is None:
        raise VerificationError("protected verifier external ID is malformed")
    require_equal(int(match.group("pr_number")), pr_number, "evidence PR number")
    require_equal(match.group("base"), event_base, "evidence base")
    require_equal(match.group("head"), event_head, "evidence head")
    producer_run_id = int(match.group("run_id"))
    producer = require_mapping(
        client.get(f"repos/{TARGET_REPOSITORY}/actions/runs/{producer_run_id}"),
        "protected verifier run",
    )
    require_equal(producer.get("id"), producer_run_id, "protected verifier run ID")
    require_equal(producer.get("event"), "pull_request_target", "verifier event")
    require_equal(producer.get("path"), TARGET_VERIFIER_PATH, "verifier path")
    require_equal(producer.get("status"), "completed", "verifier run status")
    require_equal(producer.get("conclusion"), "success", "verifier run conclusion")
    # This binds the Actions Runs REST field, not the runner's GITHUB_SHA.
    # Protected pull_request_target run 32388453605 for lightning-it/.github
    # PR #248 reports REST head_sha=041878621fa8e3c1d8f2c90f055038ef46eb7927,
    # the exact PR head, while its REST pull_requests array is empty. Binding
    # that observable API value avoids substituting undocumented event state.
    require_equal(producer.get("head_sha"), event_head, "verifier run head")
    head_ref = require_mapping(pr.get("head"), "pull request head").get("ref")
    require_equal(producer.get("head_branch"), head_ref, "verifier run head branch")
    author = require_mapping(pr.get("user"), "pull request author").get("login")
    require_equal(
        require_mapping(producer.get("actor"), "verifier actor").get("login"),
        author,
        "verifier actor",
    )
    run_attempt = producer.get("run_attempt")
    if run_attempt not in {1, 2}:
        raise VerificationError("verifier run attempt is outside the bounded contract")
    triggering_actor = require_mapping(
        producer.get("triggering_actor"), "verifier triggering actor"
    ).get("login")
    expected_triggering_actor = author if run_attempt == 1 else "github-actions[bot]"
    require_equal(
        triggering_actor,
        expected_triggering_actor,
        "verifier triggering actor",
    )
    display_title = producer.get("display_title")
    allowed_titles = {
        f"Protected current revision PR #{pr_number} {action} {event_head}"
        for action in PRODUCER_ACTIONS
    }
    if display_title not in allowed_titles:
        raise VerificationError("verifier run title is not exactly bound")
    require_equal(
        producer.get("html_url"),
        f"{server_url}/{TARGET_REPOSITORY}/actions/runs/{producer_run_id}",
        "verifier run URL",
    )
    workflow_id = producer.get("workflow_id")
    if not isinstance(workflow_id, int) or workflow_id <= 0:
        raise VerificationError("verifier workflow ID is invalid")
    require_equal(
        producer.get("workflow_url"),
        f"{client.api_url}/repos/{TARGET_REPOSITORY}/actions/workflows/{workflow_id}",
        "verifier workflow URL",
    )
    workflow = require_mapping(
        client.get(f"repos/{TARGET_REPOSITORY}/actions/workflows/{workflow_id}"),
        "verifier workflow",
    )
    require_equal(workflow.get("id"), workflow_id, "verifier workflow ID")
    require_equal(workflow.get("path"), TARGET_VERIFIER_PATH, "verifier workflow path")
    require_equal(workflow.get("state"), "active", "verifier workflow state")

    attempt = int(run_attempt)
    jobs_payload = require_mapping(
        client.get(
            f"repos/{TARGET_REPOSITORY}/actions/runs/{producer_run_id}"
            f"/attempts/{attempt}/jobs?per_page=100"
        ),
        "verifier jobs",
    )
    jobs = require_list(jobs_payload.get("jobs"), "verifier jobs")
    total_count = jobs_payload.get("total_count")
    if not isinstance(total_count, int) or total_count != len(jobs) or total_count > 100:
        raise VerificationError("verifier job inventory is incomplete")
    matching_jobs = [
        require_mapping(job, "verifier job")
        for job in jobs
        if isinstance(job, dict) and job.get("name") == TARGET_VERIFIER_NAME
    ]
    if len(matching_jobs) != 1:
        raise VerificationError("verifier job is missing or ambiguous")
    job = matching_jobs[0]
    require_equal(job.get("status"), "completed", "verifier job status")
    require_equal(job.get("conclusion"), "success", "verifier job conclusion")


def verify(
    client: GitHubClient,
    environment: Mapping[str, str],
    *,
    attempts: int = 60,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    repository = environment.get("REPOSITORY", "")
    require_equal(repository, TARGET_REPOSITORY, "target repository environment")
    event_action = environment.get("EVENT_ACTION", "")
    if event_action not in PRODUCER_ACTIONS:
        raise VerificationError("unsupported pull request activity")
    event_base = require_sha(environment.get("EVENT_BASE", ""), "event base")
    event_head = require_sha(environment.get("EVENT_HEAD", ""), "event head")
    if event_base == event_head:
        raise VerificationError("base and head must differ")
    pr_number = require_positive_integer(
        environment.get("PR_NUMBER", ""), "pull request number"
    )
    server_url = environment.get("GITHUB_SERVER_URL", "https://github.com").rstrip(
        "/"
    )
    workflow_ref = environment.get("WORKFLOW_REF", "")
    workflow_sha = environment.get("WORKFLOW_SHA", "")

    validate_source(client, workflow_ref, workflow_sha)
    pr = validate_live_pr(client, pr_number, event_base, event_head)
    check = wait_for_reservation(
        client,
        pr_number,
        event_base,
        event_head,
        attempts=attempts,
        sleep=sleep,
    )
    validate_reservation(
        client, check, pr, pr_number, event_base, event_head, server_url
    )
    # Re-read every mutable binding after evidence verification.
    validate_source(client, workflow_ref, workflow_sha)
    validate_live_pr(client, pr_number, event_base, event_head)
    final_matches = matching_reservations(
        client, pr_number, event_base, event_head
    )
    if len(final_matches) != 1 or final_matches[0] != check:
        raise VerificationError("protected verifier evidence drifted after validation")


def main() -> int:
    try:
        client = GitHubClient(
            os.environ.get("GH_TOKEN", ""),
            os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        )
        verify(client, os.environ)
    except VerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Protected cross-repository current-revision evidence verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
