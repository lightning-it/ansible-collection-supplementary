"""Locate delayed review evidence; protected consumers remain the authority.

Dispatch responses are never retried here. Every later observation reads native
run history first. The consumers serialize and claim the effective rerun before
its sole mutation. This service never requests an AI review or publishes PASS.
"""

import datetime as dt
import json
import os
import re
import subprocess

PRODUCER = ".github/workflows/copilot-review.yml"
REFRESH = "copilot-review-refresh.yml"
HELPER = "current-revision-rerun.yml"
CONTINUATION = "review-request-continuation.yml"
PILOTS = {
    "lightning-it/.github",
    "lightning-it/shared-assets-lit",
    "lightning-it/ansible-collection-supplementary",
}
TTL = dt.timedelta(days=7)
# Shared by all three dispatch workflows, including split probes. The Actions API
# caps filtered searches at 1000 results, independently of our page limit.
DISPATCH_INVENTORY_REQUESTS = 256
REVIEWERS = {"copilot-pull-request-reviewer", "copilot-pull-request-reviewer[bot]"}
# Match the canonical producer/refresh terminal marker vocabulary.
MARKERS = (
    "unabletoreviewthispullrequest",
    "wasnotabletoreviewthispullrequest",
    "nofilestoreview",
    "unabletoreviewanyfiles",
    "notabletoreviewanyfiles",
    "wasnotabletoreviewanyfiles",
    "quotaexhausted",
    "quotaexceeded",
    "premiumrequestquota",
    "premiumrequestsquota",
    "suppressedcomment",
    "encounteredanerror",
)


def api(route, payload=None):
    args = ["gh", "api", route]
    if payload is not None:
        args += ["--method", "POST", "--input", "-"]
    result = subprocess.run(
        args,
        input=None if payload is None else json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def pages(route, key=None):
    items = []
    for page in range(1, 11):
        response = api(f"{route}{'&' if '?' in route else '?'}per_page=100&page={page}")
        batch = response if key is None else response[key]
        if not isinstance(batch, list) or len(batch) > 100:
            raise ValueError("invalid inventory")
        items += batch
        if len(batch) < 100:
            if len({item["id"] for item in items}) != len(items):
                raise ValueError("duplicate inventory")
            return items
    raise ValueError("incomplete inventory")


def dispatch_inventory(prefix, now):
    """Read the complete seven-day locator history before any dispatch.

    Split saturated searches into disjoint inclusive UTC-second ranges, never
    page beyond GitHub's 1000-result search ceiling. Every leaf must have fewer
    than 1000 results and stable counts, exact page lengths, unique IDs and
    matching timestamps/workflow/event. No partial result escapes on failure.
    A saturated single second or exhausted shared request budget fails closed;
    the caller's existing five-minute job timeout remains the wall-time bound.
    """
    remaining = DISPATCH_INVENTORY_REQUESTS
    seen = set()
    end = now.astimezone(dt.timezone.utc).replace(microsecond=0)
    start = end - TTL
    second = dt.timedelta(seconds=1)

    def read(workflow, lower, upper, page):
        nonlocal remaining
        if remaining <= 0:
            raise ValueError("dispatch inventory request budget exhausted")
        remaining -= 1
        interval = f"{lower:%Y-%m-%dT%H:%M:%SZ}..{upper:%Y-%m-%dT%H:%M:%SZ}"
        response = api(
            f"{prefix}/actions/workflows/{workflow}/runs"
            f"?event=workflow_dispatch&created={interval}&per_page=100&page={page}"
        )
        if not isinstance(response, dict):
            raise ValueError("invalid dispatch inventory")
        total, batch = response.get("total_count"), response.get("workflow_runs")
        if type(total) is not int or total < 0 or not isinstance(batch, list):
            raise ValueError("invalid dispatch inventory")
        if len(batch) != min(100, max(0, total - (page - 1) * 100)):
            raise ValueError("incomplete dispatch inventory")
        return total, batch

    def window(workflow, lower, upper):
        total, batch = read(workflow, lower, upper, 1)
        if total >= 1000:
            if lower == upper:
                raise ValueError("dispatch inventory saturated within one second")
            middle = lower + dt.timedelta(seconds=int((upper - lower).total_seconds()) // 2)
            items = window(workflow, lower, middle) + window(workflow, middle + second, upper)
            # Saturated parent total_count is only a lower bound: native GitHub
            # clips it (observed at 2500), even when disjoint children sum higher.
            # Exact counts are required only for unsaturated leaves. Retain the
            # lower-bound check to reject observable loss between split reads.
            if len(items) < total:
                raise ValueError("dispatch inventory changed while splitting")
            return items
        items = batch
        for page in range(2, (total + 99) // 100 + 1):
            current_total, batch = read(workflow, lower, upper, page)
            if current_total != total:
                raise ValueError("dispatch inventory changed while paging")
            items += batch
        for run in items:
            if not isinstance(run, dict) or type(run.get("id")) is not int or run["id"] <= 0:
                raise ValueError("invalid dispatch identity")
            if run["id"] in seen:
                raise ValueError("duplicate dispatch inventory")
            seen.add(run["id"])
            timestamp = run.get("created_at")
            if not isinstance(timestamp, str) or not re.fullmatch(
                r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", timestamp
            ):
                raise ValueError("invalid dispatch timestamp")
            created = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if (
                not lower <= created <= upper
                or run.get("path") != f".github/workflows/{workflow}"
                or run.get("event") != "workflow_dispatch"
            ):
                raise ValueError("unbound dispatch inventory")
        return items

    return window(REFRESH, start, end) + window(HELPER, start, end) + window(CONTINUATION, start, end)


def clean_review(review, comments, head):
    if (
        review.get("commit_id") != head
        or review.get("user", {}).get("login") not in REVIEWERS
        or review.get("state", "").upper() not in {"COMMENTED", "APPROVED"}
    ):
        return False
    texts = [review.get("body")] + [comment.get("body") for comment in comments]
    if any(text is not None and not isinstance(text, str) for text in texts):
        raise ValueError("malformed review body")
    normalized = [
        re.sub(
            r"\s",
            "",
            (text or "")
            .lower()
            .replace("wasn't", "was not")
            .replace("wasn’t", "was not"),
        )
        for text in texts
    ]
    return any(normalized) and not any(
        re.sub(r"\s", "", marker) in text for marker in MARKERS for text in normalized
    )


def recent_dispatch(runs, path, title, now=None):
    matching = [
        run
        for run in runs
        if run.get("path") == f".github/workflows/{path}"
        and run.get("event") == "workflow_dispatch"
        and run.get("display_title") == title
    ]
    # A failed locator may be revisited, but never in a rapid loop. The consumer's
    # durable claim prevents another effective mutation after uncertain delivery.
    if any(run.get("status") != "completed" for run in matching):
        return True
    if matching:
        latest = max(matching, key=lambda run: run["id"])
        timestamp = dt.datetime.fromisoformat(
            latest["updated_at"].replace("Z", "+00:00")
        )
        if (now or dt.datetime.now(dt.timezone.utc)) - timestamp < dt.timedelta(minutes=10):
            return True
    return False


def required_locator(run, repository, pr):
    """Locate only the native organization authority; never authorize a rerun."""
    central = repository == "lightning-it/.github"
    path = ("dot-github-current-revision-required.yml" if central
            else "supplementary-current-revision-required.yml")
    title = "Cross-protect .github" if central else "Protected current revision"
    name = ("Protected dot-github current-revision verifier" if central
            else "Protected current-revision evidence verifier")
    api_url = f"https://api.github.com/repos/{repository}"
    entries = run.get("pull_requests")
    if not isinstance(entries, list) or len(entries) != 1:
        return False
    recorded = entries[0]
    workflow_id = run.get("workflow_id")
    return (
        type(run.get("id")) is int and run["id"] > 0
        and type(workflow_id) is int and workflow_id > 0
        and run.get("event") == "pull_request_target"
        and run.get("path") == f".github/workflows/{path}"
        and run.get("workflow_url") == f"{api_url}/actions/required_workflows/{workflow_id}"
        and run.get("repository", {}).get("full_name") == repository
        and run.get("head_repository", {}).get("full_name") == repository
        and run.get("head_sha") == pr["head"]["sha"]
        and run.get("head_branch") == pr["head"]["ref"]
        and recorded.get("number") == pr["number"]
        and recorded.get("url") == f"{api_url}/pulls/{pr['number']}"
        and recorded.get("head", {}).get("sha") == pr["head"]["sha"]
        and recorded.get("head", {}).get("ref") == pr["head"]["ref"]
        and recorded.get("head", {}).get("repo", {}).get("url") == api_url
        and recorded.get("base", {}).get("sha") == pr["base"]["sha"]
        and recorded.get("base", {}).get("ref") == pr["base"]["ref"]
        and recorded.get("base", {}).get("repo", {}).get("url") == api_url
        and run.get("display_title") in {
            f"{title} PR #{pr['number']} {action} {pr['head']['sha']}"
            for action in ("opened", "synchronize", "reopened", "ready_for_review", "edited")
        }
        and run.get("name") in (name, run.get("display_title"))
    )


def reconcile(repository, now):
    if repository not in PILOTS or os.environ.get("LI219_EVENT_MODE") != "enabled":
        return
    prefix = f"repos/{repository}"
    metadata = api(prefix)
    branch = metadata["default_branch"]
    if (
        branch not in {"develop", "main"}
        or os.environ["GITHUB_REF"] != f"refs/heads/{branch}"
        or os.environ["GITHUB_REF_PROTECTED"] != "true"
    ):
        raise ValueError("unprotected reconciliation source")
    dispatches = dispatch_inventory(prefix, now)
    for pr in pages(f"{prefix}/pulls?state=open"):
        number, head, base = pr["number"], pr["head"]["sha"], pr["base"]["sha"]
        if (
            type(number) is not int
            or number <= 0
            or not re.fullmatch(r"[0-9a-f]{40}", head)
            or not re.fullmatch(r"[0-9a-f]{40}", base)
        ):
            raise ValueError("malformed PR binding")
        if (
            pr["draft"]
            or pr["head"]["repo"]["full_name"] != repository
            or pr["base"]["ref"] not in {"develop", "main"}
            or pr["user"]["type"] != "User"
        ):
            continue
        runs = pages(
            f"{prefix}/actions/runs?event=pull_request_target&head_sha={head}",
            "workflow_runs",
        )
        producers = [
            run
            for run in runs
            if run.get("event") == "pull_request_target"
            and run.get("repository", {}).get("full_name") == repository
            and run.get("head_repository", {}).get("full_name") == repository
            and run.get("path") == PRODUCER
            and run.get("head_sha") == head
            and run.get("head_branch") == pr["head"]["ref"]
            and (
                any(item["number"] == number for item in run["pull_requests"])
                or run["pull_requests"] == []
            )
        ]
        if not producers:
            continue
        created = min(
            dt.datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            for run in producers
        )
        if now - created > TTL:
            print(
                f"PR {number}: event reservation expired; required failure remains blocking"
            )
            continue
        if any(run["status"] != "completed" for run in producers):
            continue
        checks = pages(f"{prefix}/commits/{head}/check-runs?filter=all", "check_runs")
        neutral = [
            check
            for check in checks
            if check["name"] == "Current revision review"
            and check["app"]["id"] == 15368
            and check["app"]["slug"] == "github-actions"
            and check["status"] == "completed"
            and check["conclusion"] == "success"
        ]
        if len(neutral) > 1:
            raise ValueError("ambiguous neutral evidence")
        if neutral:
            # This is only a locator. The helper independently verifies summary,
            # immutable owner, terminal jobs, source and current PR before writing.
            summary = json.loads(neutral[0]["output"]["summary"])
            owner = summary["producer_run_id"]
            if type(owner) is not int or owner <= 0:
                raise ValueError("malformed producer locator")
            producer = api(f"{prefix}/actions/runs/{owner}")
            if producer["status"] != "completed":
                continue
            attempt = producer["run_attempt"]
            if type(attempt) is not int or attempt not in (1, 2):
                raise ValueError("invalid producer attempt")
            jobs = pages(
                f"{prefix}/actions/runs/{owner}/attempts/{attempt}/jobs", "jobs"
            )
            if not jobs or any(
                job.get("status") != "completed"
                or (
                    job.get("conclusion") not in {"success", "skipped"}
                    and not (
                        job.get("name") == "Request protected verifier re-evaluation"
                        and job.get("conclusion") == "failure"
                    )
                )
                for job in jobs
            ):
                continue
            title = (
                f"Protected verifier handoff PR #{number} producer {owner} "
                f"attempt {attempt} head {head}"
            )
            path = HELPER
            inputs = {
                "base_ref": pr["base"]["ref"],
                "pr_number": str(number),
                "expected_base": base,
                "expected_head": head,
                "producer_run_id": str(owner),
                "producer_run_attempt": str(attempt),
            }
            ref = pr["base"]["ref"]
            # Let the native admission terminate; never spend the retry while its
            # first attempt is still running or while producer jobs are invisible.
            # Required discovery must not depend on producer event filtering.
            # Keep the producer query separate and verify authority on each
            # unfiltered-by-event result; a local workflow is not the Required gate.
            required_runs = pages(
                f"{prefix}/actions/runs?head_sha={head}", "workflow_runs"
            )
            targets = [run for run in required_runs if required_locator(run, repository, pr)]
            if len(targets) != 1 or targets[0]["status"] != "completed":
                continue
            if all(run.get("conclusion") == "success" for run in targets):
                continue
        else:
            reviews = pages(f"{prefix}/pulls/{number}/reviews")
            usable = []
            for review in reviews:
                if (
                    review.get("commit_id") == head
                    and review.get("user", {}).get("login") in REVIEWERS
                ):
                    comments = pages(
                        f"{prefix}/pulls/{number}/reviews/{review['id']}/comments"
                    )
                    if clean_review(review, comments, head):
                        usable.append(review)
            if not usable:
                # The existing periodic locator also covers delayed job/pending
                # visibility. It never requests AI or grants a verifier attempt.
                if not reviews or any(item.get("commit_id") == head and item.get("user", {}).get("login") in REVIEWERS for item in reviews):
                    continue
                import importlib.util
                from pathlib import Path
                spec = importlib.util.spec_from_file_location("continuation", Path(__file__).with_name("review_request_continuation.py"))
                continuation = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(continuation)
                try:
                    inputs = continuation.reconcile_candidate(repository, str(metadata["id"]), number, head, now)
                except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
                    print(f"PR {number}: deferred locator remains closed: {exc}")
                    continue
                if inputs is None:
                    continue
                path, ref = CONTINUATION, branch
                title = f"First review PR #{number} head {head} owner {inputs['owner_run']} old review {inputs['old_review']}"
            else:
                review = max(usable, key=lambda item: item["id"])
                path, ref = REFRESH, branch
                title = f"Reconcile review PR #{number} head {head}"
                inputs = dict(pr_number=str(number), expected_head=head, expected_base=base,
                              review_id=str(review["id"]))
        if recent_dispatch(dispatches, path, title, now):
            continue
        # Re-read after inventory. No mutation on a changed/closed/draft PR.
        live = api(f"{prefix}/pulls/{number}")
        if (
            live["state"] != "open"
            or live["draft"]
            or live["head"]["sha"] != head
            or live["base"]["sha"] != base
        ):
            continue
        api(
            f"{prefix}/actions/workflows/{path}/dispatches",
            {"ref": ref, "inputs": inputs},
        )
        print(f"PR {number}: dispatched protected locator {path}")


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", repository):
        raise ValueError("foreign repository")
    reconcile(repository, dt.datetime.now(dt.timezone.utc))


if __name__ == "__main__":
    main()
