"""Cross-repository verifier for the protected lightning-it/.github gate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime
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
PROMOTION_VERIFIER_MIGRATION_ALIAS = (
    "Authorize exact Supplementary catch-up v5 successor"
)
PROMOTION_VERIFIER_NAMES = frozenset(
    {PROMOTION_VERIFIER_NAME, PROMOTION_VERIFIER_MIGRATION_ALIAS}
)
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
    {"opened", "synchronize", "reopened", "ready_for_review", "edited", "labeled", "unlabeled"}
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

    def metadata_revision(self, number: int) -> Any:
        """Read only the existing protected lastEditedAt contract; never a mutation."""
        query = 'query($number:Int!){repository(owner:"lightning-it",name:".github"){pullRequest(number:$number){number lastEditedAt}}}'
        request = urllib.request.Request(
            f"{self._api_url}/graphql",
            data=json.dumps({"query": query, "variables": {"number": number}}).encode(),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise VerificationError("pull request metadata revision read failed") from exc
        if not isinstance(payload, dict) or payload.get("errors"):
            raise VerificationError("pull request metadata revision is unavailable")
        record = require_mapping(
            require_mapping(
                require_mapping(payload.get("data"), "metadata data").get("repository"), "metadata repository"
            ).get("pullRequest"),
            "metadata pull request",
        )
        require_equal(record.get("number"), number, "metadata pull request number")
        revision = record.get("lastEditedAt")
        if revision is not None:
            require_timestamp(revision, "metadata revision")
        return revision


def require_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        raise VerificationError(f"{label} must be an exact UTC timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerificationError(f"{label} is invalid") from exc


def labels_digest(labels: Any) -> str:
    names = []
    for item in require_list(labels, "pull request labels"):
        name = require_mapping(item, "pull request label").get("name")
        if not isinstance(name, str):
            raise VerificationError("pull request label name must be a string")
        names.append(name)
    if len(names) != len(set(names)):
        raise VerificationError("pull request labels are ambiguous")
    return hashlib.sha256(json.dumps(sorted(names), ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def validate_event_producer(run: Mapping[str, Any], binding: Mapping[str, Any], number: int, head: str) -> None:
    require_equal(
        require_mapping(run.get("actor"), "event producer actor").get("login"),
        binding["sender"],
        "event producer sender",
    )
    require_equal(
        run.get("display_title"),
        f"Protected current revision PR #{number} {binding['action']} {head}",
        "event producer action",
    )
    if require_timestamp(run.get("created_at"), "event producer creation") < require_timestamp(
        binding["updated_at"], "event metadata revision"
    ):
        raise VerificationError("event producer predates the bound metadata revision")


def validate_neutral_metadata(
    client: GitHubClient,
    reservation: Mapping[str, Any],
    pr: Mapping[str, Any],
    number: int,
    base: str,
    head: str,
    server: str,
) -> Mapping[str, Any]:
    """Bind the actual existing schema4 publisher, never a new sender format."""
    payload = require_mapping(
        client.get(
            f"repos/{TARGET_REPOSITORY}/commits/{head}/check-runs?check_name=Current%20revision%20review&filter=all&per_page=100"
        ),
        "neutral inventory",
    )
    checks = require_list(payload.get("check_runs"), "neutral checks")
    # Exact JSON integers reject bool and subclasses; retain this schema fence.
    # pylint: disable-next=unidiomatic-typecheck
    if type(payload.get("total_count")) is not int or payload["total_count"] != len(checks) or len(checks) > 100:
        raise VerificationError("neutral inventory is incomplete")
    matches = [check for check in checks if isinstance(check, dict) and check.get("name") == "Current revision review"]
    if len(matches) != 1:
        raise VerificationError("neutral publisher is missing or ambiguous")
    check = matches[0]
    for field, value in (("head_sha", head), ("status", "completed"), ("conclusion", "success")):
        require_equal(check.get(field), value, f"neutral {field}")
    app = require_mapping(check.get("app"), "neutral App")
    require_equal(app.get("id"), 15368, "neutral App ID")
    require_equal(app.get("slug"), "github-actions", "neutral App slug")
    cid = check.get("id")
    if type(cid) is not int or cid <= 0:  # pylint: disable=unidiomatic-typecheck
        raise VerificationError("neutral check ID is invalid")
    require_equal(check.get("details_url"), f"{server}/{TARGET_REPOSITORY}/runs/{cid}", "neutral URL")
    output = require_mapping(check.get("output"), "neutral output")
    try:
        summary = require_mapping(json.loads(output.get("summary", "")), "neutral summary")
    except (ValueError, TypeError) as exc:
        raise VerificationError("neutral summary is invalid") from exc
    for field, value in (
        ("schema", 4),
        ("pull_request_number", number),
        ("base_sha", base),
        ("head_sha", head),
    ):
        require_equal(summary.get(field), value, f"neutral {field}")
    common_keys = {
        "schema", "base_sha", "head_sha", "controller_sha", "pull_request_number",
        "producer_run_id", "review_path", "run_url",
    }
    # Core's ordinary-human publisher has eight fields. Only its separate
    # Renovate branch adds mutable metadata; live event fences bind both reads.
    kind = "copilot"
    title = "Current revision review passed"
    if set(summary) != common_keys:
        require_equal(
            set(summary),
            common_keys | {
                "controller_ref", "head_repository", "pull_request_last_edited_at",
                "pull_request_labels_sha256", "review_id",
            },
            "neutral Renovate schema4 fields",
        )
        for field, value in (
            ("head_repository", pr["head"]["repo"]["full_name"]),
            ("pull_request_last_edited_at", pr["_metadata_revision"]),
            ("pull_request_labels_sha256", labels_digest(pr.get("labels"))),
            ("review_id", None),
            ("review_path", "deterministic policy-bound Renovate exemption"),
        ):
            require_equal(summary.get(field), value, f"neutral {field}")
        if summary.get("controller_ref") not in {"main", "develop"}:
            raise VerificationError("neutral Renovate controller ref is invalid")
        kind = "renovate"
        title = "Current revision Renovate exemption passed"
    require_equal(output.get("title"), title, "neutral title")
    controller = summary.get("controller_sha")
    if not isinstance(controller, str):
        raise VerificationError("neutral controller SHA is invalid")
    require_sha(controller, "neutral controller SHA")
    if not isinstance(summary.get("review_path"), str) or not summary["review_path"]:
        raise VerificationError("neutral review path is invalid")
    producer = summary.get("producer_run_id")
    if type(producer) is not int or producer <= 0:  # pylint: disable=unidiomatic-typecheck
        raise VerificationError("neutral producer ID is invalid")
    run_url = f"{server}/{TARGET_REPOSITORY}/actions/runs/{producer}"
    require_equal(summary.get("run_url"), run_url, "neutral producer URL")
    require_equal(
        check.get("external_id"),
        f"mlx90-current-revision:{kind}:v6:{number}:{producer}:{base}:{head}",
        "neutral producer identity",
    )
    require_equal(
        require_mapping(reservation.get("output"), "reservation output").get("summary"),
        f"PR #{number}; base {base}; head {head}; producer {run_url}.",
        "reservation neutral producer association",
    )
    return check


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


def event_pr_binding(environment: Mapping[str, str]) -> Mapping[str, Any]:
    """Freeze identity from the protected pull_request_target event, never fork code."""
    fields = {
        "head_repository": "EVENT_HEAD_REPOSITORY",
        "head_owner": "EVENT_HEAD_REPOSITORY_OWNER",
        "head_ref": "EVENT_HEAD_REF",
        "base_ref": "EVENT_BASE_REF",
        "author": "EVENT_AUTHOR",
        "author_type": "EVENT_AUTHOR_TYPE",
        "sender": "EVENT_SENDER",
    }
    binding = {}
    for key, name in fields.items():
        value = environment.get(name)
        if not isinstance(value, str) or not value or any(char.isspace() for char in value):
            raise VerificationError(f"{name} must be a nonempty event string")
        binding[key] = value
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", binding["head_repository"]):
        raise VerificationError("event head repository is malformed")
    require_equal(binding["head_repository"].split("/")[0], binding["head_owner"], "event head owner")
    if binding["base_ref"] not in {"develop", "main"}:
        raise VerificationError("event base branch is outside protected scope")
    if binding["author_type"] not in {"User", "Bot"}:
        raise VerificationError("event author type is invalid")
    if binding["head_repository"] != TARGET_REPOSITORY and binding["author_type"] != "User":
        raise VerificationError("automation must remain same-repository")
    binding["action"] = environment.get("EVENT_ACTION", "")
    binding["updated_at"] = environment.get("EVENT_UPDATED_AT", "")
    require_timestamp(binding["updated_at"], "event metadata revision")
    for field in ("title", "body"):
        try:
            value = json.loads(environment.get(f"EVENT_{field.upper()}_JSON", ""))
        except (ValueError, TypeError) as exc:
            raise VerificationError(f"event {field} is invalid") from exc
        if not isinstance(value, str) and not (field == "body" and value is None):
            raise VerificationError(f"event {field} is invalid")
        binding[field] = value
    try:
        binding["labels_sha256"] = labels_digest(json.loads(environment.get("EVENT_LABELS_JSON", "")))
    except (ValueError, TypeError) as exc:
        raise VerificationError("event labels are invalid") from exc
    return binding


def validate_live_pr(
    client: GitHubClient,
    pr_number: int,
    event_base: str,
    event_head: str,
    binding: Mapping[str, Any],
) -> Mapping[str, Any]:
    repository = require_mapping(client.get(f"repos/{TARGET_REPOSITORY}"), "target repository")
    require_equal(repository.get("full_name"), TARGET_REPOSITORY, "target repository")
    require_equal(repository.get("default_branch"), "develop", "target default branch")
    require_equal(repository.get("archived"), False, "target archive state")
    require_equal(repository.get("disabled"), False, "target disabled state")
    pr = require_mapping(client.get(f"repos/{TARGET_REPOSITORY}/pulls/{pr_number}"), "pull request")
    require_equal(pr.get("number"), pr_number, "pull request number")
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
        binding["head_repository"],
        "head repository",
    )
    head_repository = require_mapping(head.get("repo"), "head repository")
    require_equal(
        require_mapping(head_repository.get("owner"), "head owner").get("login"),
        binding["head_owner"],
        "head repository owner",
    )
    require_equal(base.get("ref"), binding["base_ref"], "live base ref")
    require_equal(head.get("ref"), binding["head_ref"], "live head ref")
    author = require_mapping(pr.get("user"), "pull request author")
    require_equal(author.get("login"), binding["author"], "live author")
    require_equal(author.get("type"), binding["author_type"], "live author type")
    require_equal(pr.get("title"), binding["title"], "live title")
    require_equal(pr.get("body"), binding["body"], "live body")
    require_equal(labels_digest(pr.get("labels")), binding["labels_sha256"], "live labels digest")
    pr = dict(pr)
    pr["_metadata_revision"] = client.metadata_revision(pr_number)
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
    sender = require_mapping(run.get("actor"), "promotion actor").get("login")
    if not isinstance(sender, str) or not sender or any(char.isspace() for char in sender):
        raise VerificationError("promotion sender is invalid")
    require_equal(
        require_mapping(
            run.get("triggering_actor"), "promotion triggering actor"
        ).get("login"),
        sender,
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
        if isinstance(job, dict)
        and isinstance(job.get("name"), str)
        and job.get("name") in PROMOTION_VERIFIER_NAMES
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
) -> Mapping[str, Any]:
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
    head_repository = require_mapping(require_mapping(pr.get("head"), "pull request head").get("repo"), "head repository")
    require_equal(require_mapping(producer.get("repository"), "verifier repository").get("full_name"),
                  TARGET_REPOSITORY, "verifier repository")
    producer_head_repository = require_mapping(producer.get("head_repository"), "verifier head repository")
    require_equal(producer_head_repository.get("full_name"), head_repository.get("full_name"),
                  "verifier head repository")
    require_equal(require_mapping(producer_head_repository.get("owner"), "verifier head owner").get("login"),
                  require_mapping(head_repository.get("owner"), "head owner").get("login"), "verifier head owner")
    associated = require_list(producer.get("pull_requests"), "verifier pull requests")
    # Empty associations remain legitimate for genuine pull_request_target runs;
    # the native run/head/owner, event title and protected reservation still bind them.
    if associated:
        if len(associated) != 1:
            raise VerificationError("verifier pull request association is ambiguous")
        recorded = require_mapping(associated[0], "verifier pull request")
        require_equal(recorded.get("number"), pr_number, "verifier pull request number")
        require_equal(recorded.get("url"), f"{client.api_url}/repos/{TARGET_REPOSITORY}/pulls/{pr_number}",
                      "verifier pull request URL")
        for side, repository_name in (("base", TARGET_REPOSITORY), ("head", head_repository["full_name"])):
            native = require_mapping(recorded.get(side), f"verifier {side}")
            live = require_mapping(pr.get(side), f"live {side}")
            require_equal(native.get("sha"), live.get("sha"), f"verifier {side} SHA")
            require_equal(native.get("ref"), live.get("ref"), f"verifier {side} ref")
            require_equal(require_mapping(native.get("repo"), f"verifier {side} repository").get("url"),
                          f"{client.api_url}/repos/{repository_name}", f"verifier {side} repository URL")

    sender = require_mapping(producer.get("actor"), "verifier actor").get("login")
    if not isinstance(sender, str) or not sender or any(char.isspace() for char in sender):
        raise VerificationError("verifier sender is invalid")
    run_attempt = producer.get("run_attempt")
    if run_attempt not in {1, 2}:
        raise VerificationError("verifier run attempt is outside the bounded contract")
    triggering_actor = require_mapping(
        producer.get("triggering_actor"), "verifier triggering actor"
    ).get("login")
    expected_triggering_actor = sender if run_attempt == 1 else "github-actions[bot]"
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

    return producer


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

    binding = event_pr_binding(environment)
    validate_source(client, workflow_ref, workflow_sha)
    pr = validate_live_pr(client, pr_number, event_base, event_head, binding)
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
        validate_event_producer(evidence[1], binding, pr_number, event_head)
        # Re-read every mutable binding and ensure the selected native result
        # remains the newest exact evidence at the final mutation boundary.
        validate_source(client, workflow_ref, workflow_sha)
        final_pr = validate_live_pr(client, pr_number, event_base, event_head, binding)
        require_equal(final_pr["_metadata_revision"], pr["_metadata_revision"], "final metadata revision")
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
    native_run = validate_reservation(
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
    validate_event_producer(native_run, binding, pr_number, event_head)
    neutral = validate_neutral_metadata(client, check, pr, pr_number, event_base, event_head, server_url)
    # Re-read every mutable binding after evidence verification.
    validate_source(client, workflow_ref, workflow_sha)
    final_pr = validate_live_pr(client, pr_number, event_base, event_head, binding)
    require_equal(final_pr["_metadata_revision"], pr["_metadata_revision"], "final metadata revision")
    require_equal(validate_neutral_metadata(client, check, final_pr, pr_number, event_base, event_head, server_url), neutral, "final neutral publisher")
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
        attempts = (
            1
            if os.environ.get("REPOSITORY") == TARGET_REPOSITORY
            and os.environ.get("LI219_EVENT_MODE") == "enabled"
            else 60
        )
        verify(client, os.environ, attempts=attempts)
    except VerificationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Protected cross-repository current-revision evidence verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
