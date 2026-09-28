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
PROMOTION_VERIFIER_NAME = "Verify aggregated develop-to-main promotion evidence"
RESERVATION_NAME = "Protected current-revision verifier"
RELEASE_APP_LOGIN = "lightning-it-release-automation[bot]"
RELEASE_APP_ID = 307565056
PROMOTION_TITLE = "chore(release): promote develop to main"
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
POSITIVE_INTEGER_PATTERN = re.compile(r"^[1-9][0-9]*$")
TARGET_JOB_URL_PATTERN = re.compile(
    r"^https://github\.com/lightning-it/\.github/actions/runs/"
    r"(?P<run_id>[1-9][0-9]*)/job/(?P<job_id>[1-9][0-9]*)$"
)
RESERVATION_PATTERN = re.compile(
    r"^rep60-required-workflow:v3:(?P<run_id>[1-9][0-9]*):"
    r"(?P<pr_number>[1-9][0-9]*):(?P<base>[0-9a-f]{40}):"
    r"(?P<head>[0-9a-f]{40})$"
)
PRODUCER_ACTIONS = frozenset(
    {"opened", "synchronize", "reopened", "ready_for_review", "edited"}
)
NONTERMINAL_RUN_STATUSES = frozenset(
    {"pending", "queued", "requested", "waiting", "in_progress"}
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


def is_aggregated_promotion(pr: Mapping[str, Any]) -> bool:
    """Return whether immutable identity places the PR in promotion scope."""

    base = require_mapping(pr.get("base"), "pull request base")
    head = require_mapping(pr.get("head"), "pull request head")
    author = require_mapping(pr.get("user"), "pull request author")
    return (
        base.get("ref") == "main"
        and head.get("ref") == "develop"
        and author.get("login") == RELEASE_APP_LOGIN
        and author.get("id") == RELEASE_APP_ID
        and author.get("type") == "Bot"
    )


def validate_aggregated_promotion_shape(pr: Mapping[str, Any]) -> None:
    """Fail closed when a promotion-scoped PR has mutable-shape drift."""

    require_equal(pr.get("title"), PROMOTION_TITLE, "promotion pull request title")


def exact_promotion_run_association(
    run: Mapping[str, Any],
    pr_number: int,
    event_base: str,
    event_head: str,
) -> bool:
    """Recognize only the exact native run association for this promotion."""

    pulls = run.get("pull_requests")
    if not isinstance(pulls, list) or len(pulls) != 1:
        return False
    association = pulls[0]
    if not isinstance(association, dict):
        return False
    base = association.get("base")
    head = association.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        return False
    base_repo = base.get("repo")
    head_repo = head.get("repo")
    if not isinstance(base_repo, dict) or not isinstance(head_repo, dict):
        return False
    return (
        association.get("number") == pr_number
        and base.get("ref") == "main"
        and base.get("sha") == event_base
        and base_repo.get("name") == ".github"
        and base_repo.get("url")
        == f"https://api.github.com/repos/{TARGET_REPOSITORY}"
        and head.get("ref") == "develop"
        and head.get("sha") == event_head
        and head_repo.get("name") == ".github"
        and head_repo.get("url")
        == f"https://api.github.com/repos/{TARGET_REPOSITORY}"
    )


def matching_aggregated_promotion_checks(
    client: GitHubClient,
    pr_number: int,
    event_base: str,
    event_head: str,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], int]]:
    """Return native promotion results bound to the exact PR revision."""

    encoded_name = urllib.parse.quote(TARGET_VERIFIER_NAME, safe="")
    payload = require_mapping(
        client.get(
            f"repos/{TARGET_REPOSITORY}/commits/{event_head}/check-runs"
            f"?check_name={encoded_name}&filter=all&per_page=100"
        ),
        "aggregated promotion check inventory",
    )
    checks = require_list(payload.get("check_runs"), "aggregated promotion checks")
    total_count = payload.get("total_count")
    if not isinstance(total_count, int) or total_count != len(checks) or total_count > 100:
        raise VerificationError("aggregated promotion check inventory is incomplete")

    matches: list[tuple[Mapping[str, Any], Mapping[str, Any], int]] = []
    seen_runs: set[int] = set()
    for raw_check in checks:
        check = require_mapping(raw_check, "aggregated promotion check")
        if check.get("name") != TARGET_VERIFIER_NAME:
            continue
        if check.get("head_sha") != event_head:
            continue
        details_match = TARGET_JOB_URL_PATTERN.fullmatch(
            str(check.get("details_url", ""))
        )
        if details_match is None:
            raise VerificationError(
                "aggregated promotion check details URL is not exactly bound"
            )
        run_id = int(details_match.group("run_id"))
        job_id = int(details_match.group("job_id"))
        run = require_mapping(
            client.get(f"repos/{TARGET_REPOSITORY}/actions/runs/{run_id}"),
            "aggregated promotion run",
        )
        if run_id in seen_runs:
            raise VerificationError("aggregated promotion evidence is ambiguous")
        seen_runs.add(run_id)
        matches.append((check, run, job_id))
    matches.sort(key=lambda evidence: int(evidence[1].get("id", 0)))
    return matches


def wait_for_aggregated_promotion(
    client: GitHubClient,
    pr_number: int,
    event_base: str,
    event_head: str,
    *,
    attempts: int,
    sleep: Callable[[float], None],
) -> tuple[Mapping[str, Any], Mapping[str, Any], int]:
    """Wait only for the newest exact native promotion result."""

    for attempt in range(1, attempts + 1):
        matches = matching_aggregated_promotion_checks(
            client, pr_number, event_base, event_head
        )
        if matches:
            evidence = matches[-1]
            check, run, _job_id = evidence
            if not exact_promotion_run_association(
                run, pr_number, event_base, event_head
            ):
                raise VerificationError(
                    "latest aggregated promotion association is not exactly bound"
                )
            check_status = check.get("status")
            run_status = run.get("status")
            if check_status == "completed" and run_status == "completed":
                if (
                    check.get("conclusion") != "success"
                    or run.get("conclusion") != "success"
                ):
                    if attempt == attempts:
                        raise VerificationError(
                            "latest aggregated promotion evidence failed"
                        )
                else:
                    return evidence
            elif check_status == "completed" and check.get("conclusion") != "success":
                if attempt == attempts:
                    raise VerificationError(
                        "latest aggregated promotion evidence failed"
                    )
            elif run_status == "completed" and run.get("conclusion") != "success":
                if attempt == attempts:
                    raise VerificationError(
                        "latest aggregated promotion evidence failed"
                    )
            if check_status != "completed" and check_status not in NONTERMINAL_RUN_STATUSES:
                raise VerificationError(
                    "aggregated promotion evidence status is invalid"
                )
            if run_status != "completed" and run_status not in NONTERMINAL_RUN_STATUSES:
                raise VerificationError(
                    "aggregated promotion evidence status is invalid"
                )
        if attempt < attempts:
            sleep(10)
    raise VerificationError("aggregated promotion evidence did not become successful")


def validate_aggregated_promotion(
    client: GitHubClient,
    evidence: tuple[Mapping[str, Any], Mapping[str, Any], int],
    pr: Mapping[str, Any],
    pr_number: int,
    event_base: str,
    event_head: str,
    server_url: str,
) -> None:
    """Validate the native aggregate, its producing run, and final job."""

    check, run, job_id = evidence
    check_id = check.get("id")
    if not isinstance(check_id, int) or check_id <= 0 or check_id != job_id:
        raise VerificationError("aggregated promotion check ID is invalid")
    require_equal(check.get("name"), TARGET_VERIFIER_NAME, "promotion check name")
    require_equal(check.get("head_sha"), event_head, "promotion check head")
    require_equal(check.get("status"), "completed", "promotion check status")
    require_equal(check.get("conclusion"), "success", "promotion check conclusion")
    app = require_mapping(check.get("app"), "promotion check App")
    require_equal(app.get("id"), 15368, "promotion check App ID")
    require_equal(app.get("slug"), "github-actions", "promotion check App")

    run_id = run.get("id")
    if not isinstance(run_id, int) or run_id <= 0:
        raise VerificationError("aggregated promotion run ID is invalid")
    require_equal(
        check.get("details_url"),
        f"{server_url}/{TARGET_REPOSITORY}/actions/runs/{run_id}/job/{job_id}",
        "promotion check details URL",
    )
    require_equal(run.get("event"), "pull_request_target", "promotion run event")
    require_equal(run.get("path"), TARGET_VERIFIER_PATH, "promotion run path")
    require_equal(run.get("status"), "completed", "promotion run status")
    require_equal(run.get("conclusion"), "success", "promotion run conclusion")
    require_equal(run.get("head_sha"), event_head, "promotion run head")
    require_equal(run.get("head_branch"), "develop", "promotion run head branch")
    require_equal(run.get("run_attempt"), 1, "promotion run attempt")
    author = require_mapping(pr.get("user"), "pull request author").get("login")
    require_equal(
        require_mapping(run.get("actor"), "promotion actor").get("login"),
        author,
        "promotion actor",
    )
    require_equal(
        require_mapping(
            run.get("triggering_actor"), "promotion triggering actor"
        ).get("login"),
        author,
        "promotion triggering actor",
    )
    allowed_titles = {
        f"Protected current revision PR #{pr_number} {action} {event_head}"
        for action in PRODUCER_ACTIONS
    }
    if run.get("display_title") not in allowed_titles:
        raise VerificationError("promotion run title is not exactly bound")
    require_equal(
        run.get("html_url"),
        f"{server_url}/{TARGET_REPOSITORY}/actions/runs/{run_id}",
        "promotion run URL",
    )
    if not exact_promotion_run_association(run, pr_number, event_base, event_head):
        raise VerificationError("promotion run association drifted")

    workflow_id = run.get("workflow_id")
    if not isinstance(workflow_id, int) or workflow_id <= 0:
        raise VerificationError("promotion workflow ID is invalid")
    workflow_paths = {
        f"repos/{TARGET_REPOSITORY}/actions/workflows/{workflow_id}",
        f"repos/{TARGET_REPOSITORY}/actions/required_workflows/{workflow_id}",
    }
    workflow_url = str(run.get("workflow_url", ""))
    matching_workflow_paths = {
        path
        for path in workflow_paths
        if workflow_url == f"{client.api_url}/{path}"
    }
    if len(matching_workflow_paths) != 1:
        raise VerificationError("promotion workflow URL is not exactly bound")
    workflow_path = matching_workflow_paths.pop()
    workflow = require_mapping(
        client.get(workflow_path),
        "promotion workflow",
    )
    require_equal(workflow.get("id"), workflow_id, "promotion workflow ID")
    require_equal(workflow.get("path"), TARGET_VERIFIER_PATH, "promotion workflow path")
    require_equal(workflow.get("state"), "active", "promotion workflow state")

    jobs_payload = require_mapping(
        client.get(
            f"repos/{TARGET_REPOSITORY}/actions/runs/{run_id}"
            "/attempts/1/jobs?per_page=100"
        ),
        "promotion jobs",
    )
    jobs = require_list(jobs_payload.get("jobs"), "promotion jobs")
    total_count = jobs_payload.get("total_count")
    if not isinstance(total_count, int) or total_count != len(jobs) or total_count > 100:
        raise VerificationError("promotion job inventory is incomplete")
    final_jobs = [
        require_mapping(job, "promotion job")
        for job in jobs
        if isinstance(job, dict) and job.get("id") == job_id
    ]
    if len(final_jobs) != 1:
        raise VerificationError("promotion final job is missing or ambiguous")
    final_job = final_jobs[0]
    require_equal(final_job.get("name"), TARGET_VERIFIER_NAME, "promotion job name")
    require_equal(final_job.get("head_sha"), event_head, "promotion job head")
    require_equal(final_job.get("run_attempt"), 1, "promotion job attempt")
    require_equal(final_job.get("status"), "completed", "promotion job status")
    require_equal(final_job.get("conclusion"), "success", "promotion job conclusion")

    # The repository-local producer emits this internal aggregate before its
    # final required result. Binding both jobs prevents the final check from
    # masking a skipped or failed promotion-evidence validation.
    aggregate_jobs = [
        require_mapping(job, "promotion aggregate job")
        for job in jobs
        if isinstance(job, dict) and job.get("name") == PROMOTION_VERIFIER_NAME
    ]
    if len(aggregate_jobs) != 1:
        raise VerificationError("promotion aggregate job is missing or ambiguous")
    aggregate_job = aggregate_jobs[0]
    require_equal(aggregate_job.get("head_sha"), event_head, "aggregate job head")
    require_equal(aggregate_job.get("run_attempt"), 1, "aggregate job attempt")
    require_equal(aggregate_job.get("status"), "completed", "aggregate job status")
    require_equal(
        aggregate_job.get("conclusion"), "success", "aggregate job conclusion"
    )


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


def wait_for_completed_producer(
    client: GitHubClient,
    producer_run_id: int,
    *,
    attempts: int,
    sleep: Callable[[float], None],
) -> Mapping[str, Any]:
    path = f"repos/{TARGET_REPOSITORY}/actions/runs/{producer_run_id}"
    for attempt in range(1, attempts + 1):
        producer = require_mapping(client.get(path), "protected verifier run")
        require_equal(producer.get("id"), producer_run_id, "protected verifier run ID")
        status = producer.get("status")
        if status == "completed":
            return producer
        if not isinstance(status, str) or status not in NONTERMINAL_RUN_STATUSES:
            raise VerificationError(f"verifier run status is invalid: {status!r}")
        if attempt < attempts:
            sleep(2)
    raise VerificationError("protected verifier run did not complete")


def validate_reservation(
    client: GitHubClient,
    check: Mapping[str, Any],
    pr: Mapping[str, Any],
    pr_number: int,
    event_base: str,
    event_head: str,
    server_url: str,
    *,
    attempts: int,
    sleep: Callable[[float], None],
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
    # GitHub can expose the final successful reservation check a few moments
    # before the producing workflow run itself transitions from ``in_progress``
    # to ``completed``. Poll only the already-bound run ID; an earlier workflow
    # state or alternate evidence is not accepted after that final check exists.
    producer = wait_for_completed_producer(
        client,
        producer_run_id,
        attempts=attempts,
        sleep=sleep,
    )
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
    if is_aggregated_promotion(pr):
        validate_aggregated_promotion_shape(pr)
        evidence = wait_for_aggregated_promotion(
            client,
            pr_number,
            event_base,
            event_head,
            attempts=attempts,
            sleep=sleep,
        )
        validate_aggregated_promotion(
            client,
            evidence,
            pr,
            pr_number,
            event_base,
            event_head,
            server_url,
        )
        # Re-read every mutable binding and ensure the selected native result
        # remains the newest exact evidence at the final mutation boundary.
        validate_source(client, workflow_ref, workflow_sha)
        final_pr = validate_live_pr(client, pr_number, event_base, event_head)
        if not is_aggregated_promotion(final_pr):
            raise VerificationError("protected promotion shape drifted")
        validate_aggregated_promotion_shape(final_pr)
        final_matches = matching_aggregated_promotion_checks(
            client, pr_number, event_base, event_head
        )
        if not final_matches or final_matches[-1] != evidence:
            raise VerificationError("aggregated promotion evidence drifted after validation")
        validate_aggregated_promotion(
            client,
            final_matches[-1],
            final_pr,
            pr_number,
            event_base,
            event_head,
            server_url,
        )
        return

    check = wait_for_reservation(
        client,
        pr_number,
        event_base,
        event_head,
        attempts=attempts,
        sleep=sleep,
    )
    validate_reservation(
        client,
        check,
        pr,
        pr_number,
        event_base,
        event_head,
        server_url,
        attempts=attempts,
        sleep=sleep,
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
