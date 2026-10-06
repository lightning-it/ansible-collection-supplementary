"""LI-219 v2 first-request continuation. Never retry an effect or mint a new budget.

This file is embedded in protected workflows, never loaded from a PR checkout.
The deferred record carries original authorization, not request consumption.
"""
# Exact JSON schema types deliberately reject bool as int and subclasses.
# pylint: disable=unidiomatic-typecheck
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode
import re
import subprocess
import sys
import time

PILOTS = {"lightning-it/.github", "lightning-it/shared-assets-lit",
          "lightning-it/ansible-collection-supplementary"}
PRODUCER = ".github/workflows/copilot-review.yml"
WORKFLOW = ".github/workflows/review-request-continuation.yml"
BOT = "copilot-pull-request-reviewer[bot]"
REVIEWERS = frozenset({BOT, "copilot-pull-request-reviewer"})
FAILURE_MARKERS = (
    "unabletoreviewthispullrequest",
    "notabletoreviewthispullrequest", "wasnotabletoreviewthispullrequest",
    "nofilestoreview", "nofileswerereviewed",
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
ORIGINAL_STEPS = ["Set up job", "Materialize the protected operation claim",
                  "Request Copilot review for the current revision", "Complete job"]
RESUME_STEPS = ["Set up job", "Materialize protected first-request continuation",
                "Resume the deferred first request", "Complete job"]


VISIBILITY_READS = 24
VISIBILITY_SECONDS = 20
_visibility_budget = None


class NativeBindingPending(ValueError):
    """A valid unfinished native owner has not exposed its policy binding yet."""


class ConfirmedIntentConflict(ValueError):
    """The server explicitly rejected the expected journal head."""


class UnknownWriteResult(ValueError):
    """Only readback is allowed after an unconfirmed journal write."""


class ReviewContentError(ValueError):
    """The selected review has malformed or unsuccessful content."""


def normalize(value: str) -> str:
    """Match the protected gate's ASCII fold, contraction and Unicode whitespace rules."""
    ascii_lower = "".join(chr(ord(char) + 32) if "A" <= char <= "Z" else char for char in value)
    expanded = ascii_lower.replace("n't", " not").replace("n\u2019t", " not")
    return "".join(char for char in expanded if not char.isspace())


def require_usable_review_content(review_body: object, inline_bodies: object) -> None:
    """Reject malformed, empty, or known unsuccessful Copilot review content."""
    if review_body is not None and type(review_body) is not str:
        raise ReviewContentError("review-body-shape")
    if type(inline_bodies) is not list or any(type(body) is not str for body in inline_bodies):
        raise ReviewContentError("inline-body-shape")
    parts = [normalize(review_body or ""), *(normalize(body) for body in inline_bodies)]
    if not any(parts):
        raise ReviewContentError("review-content-empty")
    if any(marker in part for part in parts for marker in FAILURE_MARKERS):
        raise ReviewContentError("review-content-failed")


def require(value, message):
    if not value:
        raise ValueError(message)


def positive(value):
    return type(value) is int and value > 0


def sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value)


def epoch(value):
    parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    require(parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value, "timestamp")
    return parsed.replace(tzinfo=dt.timezone.utc).timestamp()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def api(route, payload=None, fields=()):
    args = ["gh", "api", route, *fields]
    if payload is not None:
        args += ["--method", "POST", "--input", "-"]
    timeout = 30
    if _visibility_budget is not None:
        require(payload is None and not fields and route.startswith("repos/"), "visibility is GET-only")
        remaining = _visibility_budget[1] - time.monotonic()
        require(_visibility_budget[0] > 0 and remaining > 0, "visibility read/time budget exhausted")
        _visibility_budget[0] -= 1
        timeout = min(timeout, remaining)
    result = subprocess.run(args, input=None if payload is None else json.dumps(payload),
                            capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(result.stdout, object_pairs_hook=unique) if result.stdout.strip() else None


def commit_response(payload):
    transport_failed = False
    try:
        result = api("graphql", payload)
    except subprocess.CalledProcessError as exc:
        transport_failed = True
        try:
            result = json.loads(exc.stdout, object_pairs_hook=unique)
        except (TypeError, ValueError):
            raise UnknownWriteResult("unconfirmed journal transport") from exc
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise UnknownWriteResult("unconfirmed journal transport") from exc
    prior = payload["variables"]["input"]["expectedHeadOid"]
    errors = result.get("errors") if isinstance(result, dict) else None
    if (isinstance(result, dict) and result.get("data") == {"createCommitOnBranch": None}
            and isinstance(errors, list) and len(errors) == 1 and isinstance(errors[0], dict)
            and errors[0].get("type") == "STALE_DATA"
            and errors[0].get("path") == ["createCommitOnBranch"]
            and errors[0].get("message") == f'Expected branch to point to "{prior}" but it did not. Pull and try again.'):
        raise ConfirmedIntentConflict("confirmed journal head conflict")
    if transport_failed or not isinstance(result, dict) or "errors" in result:
        raise UnknownWriteResult("unconfirmed journal response")
    return result


def pages(route, key=None):
    result, total = [], None
    for page in range(1, 11):
        response = api(f"{route}{'&' if '?' in route else '?'}per_page=100&page={page}")
        batch = response if key is None else response[key]
        require(isinstance(batch, list) and len(batch) <= 100, "page shape")
        if key:
            count = response["total_count"]
            require(type(count) is int and 0 <= count < 1000, "inventory limit")
            require(total is None or total == count, "changing inventory")
            total = count
        result.extend(batch)
        if len(batch) < 100:
            require(total is None or len(result) == total, "incomplete inventory")
            require(all(isinstance(item, dict) and positive(item.get("id")) for item in result), "item identity")
            require(len({item["id"] for item in result}) == len(result), "duplicate inventory")
            return result
    raise ValueError("inventory limit")


def key_for(repo_id, pr, head):
    return f"li219-review-request:v1:{repo_id}:{pr}:{head}"


def record_path(key, deferred=False):
    return ("deferred/" if deferred else "operations/") + hashlib.sha256(key.encode()).hexdigest() + ".json"


def blob(value):
    require(isinstance(value, dict) and value.get("__typename") == "Blob"
            and value.get("isTruncated") is False, "journal blob")
    text = value["text"]
    require(isinstance(text, str) and positive(value["byteSize"])
            and len(text.encode()) == value["byteSize"] <= 4096, "journal size")
    return json.loads(text, object_pairs_hook=unique)


class Journal:
    def __init__(self, repo, repo_id):
        self.repo, self.repo_id = repo, repo_id
        ref = api(f"repos/{repo}/git/ref/heads/lit-review-operations")
        require(ref["ref"] == "refs/heads/lit-review-operations" and ref["object"]["type"] == "commit", "journal ref")
        self.oid = ref["object"]["sha"]
        require(sha(self.oid), "journal commit")

    def read(self, path):
        query = (
            'query($owner:String!,$name:String!,$oid:String!,$manifest:String!,$record:String!){repository(owner:'
            '$owner,name:$name){nameWithOwner source:object(expression:$oid){__typename oid} manifest:object(expr'
            'ession:$manifest){__typename ... on Blob{isTruncated byteSize text}} record:object(expression:$recor'
            'd){__typename ... on Blob{isTruncated byteSize text}}}}'
        )
        result = api("graphql", fields=[
            "-f", "query=" + query,
            "-f", f"owner={self.repo.split('/')[0]}", "-f", f"name={self.repo.split('/')[1]}",
            "-f", f"oid={self.oid}", "-f", f"manifest={self.oid}:manifest.json",
            "-f", f"record={self.oid}:{path}",
        ])
        require("errors" not in result, "partial journal")
        data = result["data"]["repository"]
        require(data["nameWithOwner"] == self.repo and data["source"] == {"__typename": "Commit", "oid": self.oid}, "mixed journal")
        manifest = blob(data["manifest"])
        require(type(manifest.get("schema")) is int and manifest == {"schema": 1, "repository": self.repo,
                "repository_id": self.repo_id, "ref": "refs/heads/lit-review-operations"}, "manifest")
        return None if data["record"] is None else blob(data["record"])

    def create(self, path, record):
        require(self.read(path) is None, "record already exists")
        query = ("mutation($input:CreateCommitOnBranchInput!){"
                 "createCommitOnBranch(input:$input){commit{oid parents(first:2){nodes{oid}}}}}")
        contents = base64.b64encode(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).decode()
        result = commit_response({
            "query": query,
            "variables": {"input": {
                "branch": {"repositoryNameWithOwner": self.repo, "branchName": "lit-review-operations"},
                "expectedHeadOid": self.oid,
                "message": {"headline": "Record LI-219 first-request continuation"},
                "fileChanges": {"additions": [{"path": path, "contents": contents}]},
            }},
        })
        require(isinstance(result, dict) and "errors" not in result, "uncertain CAS")
        commit = result["data"]["createCommitOnBranch"]["commit"]
        require(sha(commit["oid"]) and commit["oid"] != self.oid
                and commit["parents"]["nodes"] == [{"oid": self.oid}], "CAS result")
        self.oid = commit["oid"]
        require(self.read(path) == record, "CAS readback")


def repository(repo, repo_id, source, base_ref="develop"):
    require(repo in PILOTS and re.fullmatch(r"[1-9][0-9]*", repo_id) and sha(source), "pilot/source")
    meta = api(f"repos/{repo}")
    require(meta["full_name"] == repo and str(meta["id"]) == repo_id
            and meta["default_branch"] == "develop", "repository")
    require(base_ref in {"develop", "main"}, "protected base ref")
    branch = api(f"repos/{repo}/branches/{base_ref}")
    require(branch["name"] == base_ref and branch["protected"] is True and sha(branch["commit"]["sha"]), "protected default")
    ancestry = api(f"repos/{repo}/compare/{source}...{branch['commit']['sha']}")
    require(ancestry.get("status") == "identical" or (ancestry.get("status") == "ahead"
            and ancestry.get("behind_by") == 0 and ancestry.get("merge_base_commit", {}).get("sha") == source), "source ancestry")
    return branch["commit"]["sha"]


def live_pr(repo, pr, head=None, base=None):
    require(positive(pr), "PR ID")
    value = api(f"repos/{repo}/pulls/{pr}")
    require(value["number"] == pr and value["state"] == "open" and value["draft"] is False
            and value["user"]["login"] == "litroc" and value["user"]["type"] == "User", "live human PR")
    require(value["head"]["repo"]["full_name"] == repo and value["base"]["repo"]["full_name"] == repo
            and value["base"]["ref"] in {"develop", "main"} and value["head"]["ref"]
            and sha(value["head"]["sha"]) and sha(value["base"]["sha"]), "PR refs")
    require(head is None or value["head"]["sha"] == head, "stale head")
    require(base is None or value["base"]["sha"] == base, "stale base")
    return value


def original_run(repo, intent, completed=True):
    run = api(f"repos/{repo}/actions/runs/{intent['owner_run']}/attempts/1")
    require(run["id"] == intent["owner_run"] and type(run["id"]) is int and type(run["run_attempt"]) is int and run["run_attempt"] == 1
            and run["event"] == "pull_request_target" and run["path"] == PRODUCER
            and run["name"] == "Current revision review gate" and run["head_sha"] == intent["head"]
            and run["head_branch"] == intent["head_ref"] and run["actor"]["login"] == "litroc"
            and run["triggering_actor"]["login"] == "litroc"
            and run["repository"]["full_name"] == repo and run["head_repository"]["full_name"] == repo, "original run")
    prs = run["pull_requests"]
    require(isinstance(prs, list) and len(prs) <= 1, "original PR inventory")
    if not prs:
        lookup = empty_owner if completed else await_empty_owner
        pr = lookup(repo, run, intent["pr"], intent["base"], intent["head"], intent["base_ref"])
        require(pr["head"]["ref"] == intent["head_ref"], "fallback head ref")
    else:
        recorded_pr(repo, intent, prs[0])
    if completed:
        require(run["status"] == "completed" and run["conclusion"] == "failure", "original not completed failure")
    return run


def await_empty_owner(repo, run, owner, base, head, base_ref):
    """Only visibility races get a short read-only wait before intent creation."""
    global _visibility_budget
    require(_visibility_budget is None, "nested visibility wait")
    _visibility_budget = [VISIBILITY_READS, time.monotonic() + VISIBILITY_SECONDS]
    try:
        for observation in range(4):
            try:
                return empty_owner(repo, run, owner, base, head, base_ref, allow_pending=True)
            except NativeBindingPending:
                require(observation < 3, "native binding visibility exhausted")
                remaining = _visibility_budget[1] - time.monotonic()
                require(_visibility_budget[0] > 0 and remaining > 2, "visibility read/time budget exhausted")
                time.sleep(2)
    finally:
        _visibility_budget = None


def empty_owner(repo, run, owner, base, head, base_ref, allow_pending=False):
    require(repo in PILOTS and positive(owner) and positive(run.get("id"))
            and type(run.get("run_attempt")) is int and run["run_attempt"] in (1, 2)
            and run["event"] == "pull_request_target" and run["path"] == PRODUCER
            and run["name"] == "Current revision review gate" and run["head_sha"] == head
            and run["actor"]["login"] == "litroc"
            and run["triggering_actor"]["login"] == ("litroc" if run["run_attempt"] == 1 else "github-actions[bot]")
            and run["repository"]["full_name"] == repo and run["head_repository"]["full_name"] == repo
            and run["pull_requests"] == [] and sha(base) and sha(head), "fallback native owner")
    require(repo in {"lightning-it/.github", "lightning-it/shared-assets-lit"}, "no native fallback sender")
    pr = branch_pr(repo, run)
    require(pr["number"] == owner and pr["base"]["sha"] == base and pr["base"]["ref"] == base_ref, "fallback PR binding")
    jobs = pages(f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?filter=all", "jobs")
    policy = [job for job in jobs if job.get("name") == "Verify current revision policy"]
    if allow_pending and not policy:
        raise NativeBindingPending("policy job not visible")
    require(len(policy) == 1, "fallback policy job")
    job = policy[0]
    require(type(job.get("run_id")) is int and job["run_id"] == run["id"]
            and type(job.get("run_attempt")) is int and job["run_attempt"] == run["run_attempt"]
            and job["head_sha"] == head, "fallback native policy identity")
    if allow_pending and job["status"] in {"queued", "waiting", "pending"} and job["conclusion"] is None:
        raise NativeBindingPending("policy job queued")
    require(type(job.get("run_id")) is int and job["run_id"] == run["id"]
            and type(job.get("run_attempt")) is int and job["run_attempt"] == run["run_attempt"]
            and job["head_sha"] == head and positive(job.get("runner_id"))
            and job["status"] in {"in_progress", "completed"}
            and (job["conclusion"] is None if job["status"] == "in_progress"
                 else job["conclusion"] in {"success", "failure"}), "fallback native policy")
    require(repo in {"lightning-it/.github", "lightning-it/shared-assets-lit"}, "no native fallback sender")
    binding = (f"Event binding #{owner}:{base}:{head}:{run['id']}" if repo == "lightning-it/.github" else
               f"Current revision tuple #{owner} {base_ref}@{base} -> {repo}:{run['head_branch']}@{head} run {run['id']}")
    steps = job["steps"]
    require(isinstance(steps, list) and all(isinstance(step, dict) and isinstance(step.get("name"), str) for step in steps),
            "fallback step inventory")
    if allow_pending and job["status"] == "in_progress" and not any(step.get("number") == 2 for step in steps):
        raise NativeBindingPending("policy binding not visible")
    require(sum(step["name"] == binding for step in steps) == 1, "fallback event binding")
    step = next(step for step in steps if step["name"] == binding)
    if (allow_pending and job["status"] == "in_progress" and type(step.get("number")) is int
            and step["number"] == 2 and step["status"] in {"queued", "in_progress"} and step["conclusion"] is None):
        raise NativeBindingPending("policy binding unfinished")
    require(type(step.get("number")) is int and step["number"] == 2
            and step["status"] == "completed" and step["conclusion"] == "success", "fallback binding step")
    return pr


def branch_pr(repo, run):
    query = urlencode({"state": "open", "head": repo.split('/')[0] + ':' + run["head_branch"]})
    candidates = pages(f"repos/{repo}/pulls?{query}")
    require(len(candidates) == 1, "ambiguous live branch")
    pr = live_pr(repo, candidates[0]["number"], run["head_sha"])
    require(pr["head"]["ref"] == run["head_branch"], "branch drift")
    return pr


def recorded_pr(repo, intent, pr):
    require(pr["number"] == intent["pr"] and all(pr[side][field] == intent[side if field == "sha" else side + "_ref"]
            for side in ("base", "head") for field in ("sha", "ref"))
            and all(pr[side]["repo"]["url"] == f"https://api.github.com/repos/{repo}" for side in ("base", "head")), "original recorded PR")


def native_job(repo, run, name, names):
    jobs = pages(f"repos/{repo}/actions/runs/{run['id']}/attempts/1/jobs?filter=all", "jobs")
    require(len({job["name"] for job in jobs}) == len(jobs), "duplicate job names")
    require(all(type(job["run_id"]) is int and job["run_id"] == run["id"] and type(job["run_attempt"]) is int and job["run_attempt"] == 1
            and job["head_sha"] == run["head_sha"] and job["status"] == "completed" for job in jobs), "native job binding")
    selected = [job for job in jobs if job["name"] == name]
    require(len(selected) == 1, "native job inventory")
    if names == RESUME_STEPS:
        others = [job for job in jobs if job["name"] != name]
        require(len(others) == 1 and others[0]["name"] == "Locate deferred first review request"
                and others[0]["conclusion"] == "skipped" and others[0].get("runner_id") is None
                and others[0]["steps"] == [], "resume native job layout")
    job = selected[0]
    require(job["conclusion"] == "success" and positive(job.get("runner_id")), "native job unsuccessful")
    steps = job["steps"]
    require(isinstance(steps, list) and len(steps) == len(names), "native step inventory")
    last = epoch(job["started_at"])
    require(epoch(run["created_at"]) <= last, "job predates run")
    for index, (step, expected) in enumerate(zip(steps, names), 1):
        require(step["name"] == expected and type(step["number"]) is int and step["number"] == index
                and step["status"] == "completed" and step["conclusion"] == "success", "native step binding")
        require(last <= epoch(step["started_at"]) <= epoch(step["completed_at"]), "native step order")
        last = epoch(step["completed_at"])
    require(last <= epoch(job["completed_at"]) <= epoch(run["updated_at"]), "native job order")
    return job


def validate_intent(intent, repo, repo_id, key):
    expected = {"schema", "kind", "repository", "repository_id", "operation", "pr", "base", "head",
                "base_ref", "head_ref", "owner_run", "owner_attempt", "source_sha", "event", "action",
                "author", "actor", "triggering_actor", "created_at"}
    require(isinstance(intent, dict) and set(intent) == expected and type(intent["schema"]) is int
            and intent["schema"] == 1 and intent["kind"] == "deferred-first-request"
            and intent["repository"] == repo and intent["repository_id"] == repo_id and intent["operation"] == key
            and positive(intent["pr"]) and positive(intent["owner_run"]) and type(intent["owner_attempt"]) is int
            and intent["owner_attempt"] == 1 and intent["event"] == "pull_request_target"
            and intent["action"] in {"opened", "ready_for_review", "synchronize"}
            and intent["author"] == intent["actor"] == intent["triggering_actor"] == "litroc"
            and intent["base_ref"] in {"develop", "main"} and isinstance(intent["head_ref"], str) and intent["head_ref"]
            and all(sha(intent[field]) for field in ("base", "head", "source_sha")), "deferred intent")
    require(key == key_for(repo_id, intent["pr"], intent["head"]), "intent budget key")
    repository(repo, repo_id, intent["source_sha"], intent["base_ref"])
    run = original_run(repo, intent)
    job = native_job(repo, run, "Request Copilot review for current revision", ORIGINAL_STEPS)
    require(epoch(job["steps"][2]["started_at"]) <= epoch(intent["created_at"]) <= epoch(job["steps"][2]["completed_at"]), "intent outside original step")
    return run


def clean_old_review(repo, pr, review_id, head, after, reference_time=None):
    value = api(f"repos/{repo}/pulls/{pr}/reviews/{review_id}")
    require(positive(value["id"]) and value["id"] == review_id and sha(value["commit_id"])
            and value["commit_id"] != head and value["user"]["login"] in REVIEWERS and value["user"]["type"] == "Bot"
            and value["state"] in {"COMMENTED", "APPROVED"}
            and epoch(value["submitted_at"]) >= epoch(after) - 604800, "old review identity")
    # A stale PR-wide Pending flag may outlive completion before owner creation.
    # Original human authority is independent of this ordering; the latest old
    # review must still be no older than seven days at the actual request step.
    reference = epoch(reference_time) if reference_time is not None else dt.datetime.now(dt.timezone.utc).timestamp()
    require(0 <= reference - epoch(value["submitted_at"]) <= 604800, "old review age")
    inline = [item.get("body") for item in pages(f"repos/{repo}/pulls/{pr}/reviews/{review_id}/comments")]
    require_usable_review_content(value.get("body"), inline)
    candidates = [item for item in pages(f"repos/{repo}/pulls/{pr}/reviews")
                  if item.get("user", {}).get("login") in REVIEWERS and item.get("commit_id") != head
                  and epoch(item["submitted_at"]) >= epoch(after) - 604800
                  and (reference_time is None or epoch(item["submitted_at"]) <= reference)]
    require(candidates and max(candidates, key=lambda item: (epoch(item["submitted_at"]), item["id"]))["id"] == review_id,
            "superseded old review")
    return value


def unconsumed(repo, intent, journal):
    pr = live_pr(repo, intent["pr"], intent["head"], intent["base"])
    require(pr["head"]["ref"] == intent["head_ref"] and pr["base"]["ref"] == intent["base_ref"], "live ref drift")
    current = api(f"repos/{repo}/actions/runs/{intent['owner_run']}")
    require(current["id"] == intent["owner_run"] and type(current["run_attempt"]) is int
            and current["run_attempt"] == 1 and current["status"] == "completed" and current["conclusion"] == "failure", "verifier budget spent or active")
    rerun_key = f"li219-verifier-operation:v1:{intent['pr']}:{intent['base']}:{intent['head']}:{intent['owner_run']}"
    require(journal.read(record_path(rerun_key)) is None and journal.read(record_path(intent["operation"])) is None, "consumed operation")
    reviews = pages(f"repos/{repo}/pulls/{intent['pr']}/reviews")
    require(not any(review.get("commit_id") == intent["head"] and review.get("user", {}).get("login") in REVIEWERS
                    for review in reviews), "current-head review exists")
    pending = api(f"repos/{repo}/pulls/{intent['pr']}/requested_reviewers")
    require(isinstance(pending["users"], list) and not any(item["login"] in REVIEWERS for item in pending["users"]), "review still pending")
    comments = pages(f"repos/{repo}/issues/{intent['pr']}/comments")
    markers = (f"<!-- mlx90-copilot-request head={intent['head']} -->",
               f"<!-- mlx90-copilot-request-uncertain head={intent['head']} -->")
    require(not any(item["user"]["login"] == "github-actions[bot]" and any(marker in item["body"] for marker in markers)
                    for item in comments), "existing request consumption marker")


def environment():
    repo, repo_id, source = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REPOSITORY_ID"], os.environ["WORKFLOW_SHA"]
    require(os.environ.get("LI219_EVENT_MODE") == "enabled" and repo in PILOTS, "inactive pilot")
    require(os.environ["GITHUB_RUN_ATTEMPT"] == "1", "attempt")
    return repo, repo_id, source


def reconcile_candidate(repo, repo_id, pr, head, now):
    """Read-only fallback for the existing bounded ten-minute reconciler."""
    key = key_for(repo_id, pr, head)
    journal = Journal(repo, repo_id)
    intent = journal.read(record_path(key, True))
    if intent is None or journal.read(record_path(key)) is not None:
        return None
    owner = validate_intent(intent, repo, repo_id, key)
    require(0 <= now.timestamp() - epoch(owner["created_at"]) <= 604800, "expired intent")
    candidates = [item for item in pages(f"repos/{repo}/pulls/{pr}/reviews")
                  if item.get("user", {}).get("login") in REVIEWERS and item.get("commit_id") != head
                  and epoch(item["submitted_at"]) >= epoch(owner["created_at"]) - 604800]
    if not candidates:
        return None
    review_id = max(candidates, key=lambda item: (epoch(item["submitted_at"]), item["id"]))["id"]
    clean_old_review(repo, pr, review_id, head, owner["created_at"])
    unconsumed(repo, intent, journal)
    return {"pr_number": str(pr), "owner_run": str(owner["id"]), "expected_head": head, "old_review": str(review_id)}


def defer():
    repo, repo_id, source = environment()
    require(os.environ["GITHUB_EVENT_NAME"] == "pull_request_target" and os.environ["GITHUB_ACTOR"] == "litroc"
            and os.environ["GITHUB_TRIGGERING_ACTOR"] == "litroc" and os.environ["GITHUB_REF_PROTECTED"] == "true"
            and os.environ["GITHUB_REF"] in {"refs/heads/develop", "refs/heads/main"}, "original authority")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(), object_pairs_hook=unique)
    require(event["action"] in {"opened", "ready_for_review", "synchronize"}, "original action")
    pr = live_pr(repo, int(os.environ["PR_NUMBER"]), os.environ["EXPECTED_HEAD"], os.environ["EXPECTED_BASE"])
    require(event["pull_request"]["number"] == pr["number"] and event["pull_request"]["head"]["sha"] == pr["head"]["sha"]
            and event["pull_request"]["base"]["sha"] == pr["base"]["sha"] and event["pull_request"]["user"]["login"] == "litroc", "event PR")
    require(os.environ["GITHUB_REF"] == f"refs/heads/{pr['base']['ref']}"
            and source == pr["base"]["sha"], "original protected base source")
    repository(repo, repo_id, source, pr["base"]["ref"])
    key = key_for(repo_id, pr["number"], pr["head"]["sha"])
    intent = {"schema": 1, "kind": "deferred-first-request", "repository": repo, "repository_id": repo_id,
              "operation": key, "pr": pr["number"], "base": pr["base"]["sha"], "head": pr["head"]["sha"],
              "base_ref": pr["base"]["ref"], "head_ref": pr["head"]["ref"], "owner_run": int(os.environ["GITHUB_RUN_ID"]),
              "owner_attempt": 1, "source_sha": source, "event": "pull_request_target", "action": event["action"],
              "author": "litroc", "actor": "litroc", "triggering_actor": "litroc",
              "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    original_run(repo, intent, completed=False)
    journal = Journal(repo, repo_id)
    if journal.read(record_path(key)) is not None or journal.read(record_path(key, True)) is not None:
        return
    # This records eligibility only. No request marker or request budget is spent.
    for attempt in range(3):
        try:
            journal.create(record_path(key, True), intent)
            return
        except ConfirmedIntentConflict:
            journal = Journal(repo, repo_id)
            if journal.read(record_path(key)) is not None or journal.read(record_path(key, True)) is not None:
                return
            require(attempt < 2, "deferred intent conflict budget exhausted")
            live_pr(repo, intent["pr"], intent["head"], intent["base"])
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
            # Unknown delivery is GET-only, even when the record is absent.
            journal = Journal(repo, repo_id)
            require(journal.read(record_path(key, True)) == intent
                    and journal.read(record_path(key)) is None, "unconfirmed deferred intent")
            return


def locate():
    repo, repo_id, source = environment()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(), object_pairs_hook=unique)
    event_name = os.environ["GITHUB_EVENT_NAME"]
    if event_name == "workflow_run":
        run = event["workflow_run"]
        require(event["action"] == "completed" and run["event"] == "pull_request_target" and run["path"] == PRODUCER
                and type(run["run_attempt"]) is int and run["run_attempt"] == 1
                and isinstance(run["pull_requests"], list) and len(run["pull_requests"]) <= 1, "companion event")
        pr_number = run["pull_requests"][0]["number"] if run["pull_requests"] else branch_pr(repo, run)["number"]
    else:
        require(event_name == "pull_request_review" and event["action"] == "submitted"
                and event["review"]["user"]["login"] in REVIEWERS, "review completion event")
        pr_number = event["pull_request"]["number"]
    pr = live_pr(repo, pr_number)
    key = key_for(repo_id, pr_number, pr["head"]["sha"])
    journal = Journal(repo, repo_id)
    intent = journal.read(record_path(key, True))
    if intent is None:
        return
    owner = validate_intent(intent, repo, repo_id, key)
    if event_name == "workflow_run":
        require(run["id"] == owner["id"], "companion owner")
        reviews = [item for item in pages(f"repos/{repo}/pulls/{pr_number}/reviews")
                   if item.get("user", {}).get("login") in REVIEWERS and item.get("commit_id") != intent["head"]
                   and epoch(item["submitted_at"]) >= epoch(owner["created_at"]) - 604800]
        if not reviews:
            return
        review_id = max(reviews, key=lambda item: (epoch(item["submitted_at"]), item["id"]))["id"]
    else:
        review_id = event["review"]["id"]
    clean_old_review(repo, pr_number, review_id, intent["head"], owner["created_at"])
    unconsumed(repo, intent, journal)
    # Locator only; no input below grants consumer mutation authority.
    api(f"repos/{repo}/actions/workflows/review-request-continuation.yml/dispatches", {
        "ref": intent["base_ref"],
        "inputs": {
            "pr_number": str(pr_number), "owner_run": str(owner["id"]),
            "expected_head": intent["head"], "old_review": str(review_id),
        },
    })


def resume():
    repo, repo_id, source = environment()
    require(os.environ["GITHUB_EVENT_NAME"] == "workflow_dispatch" and os.environ["GITHUB_ACTOR"] == "github-actions[bot]"
            and os.environ["GITHUB_TRIGGERING_ACTOR"] == "github-actions[bot]" and os.environ["GITHUB_REF_PROTECTED"] == "true"
            and os.environ["GITHUB_REF"] in {"refs/heads/develop", "refs/heads/main"}, "resume authority")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(), object_pairs_hook=unique)
    inputs = event["inputs"]
    pr, owner_id, review_id = (int(inputs[key]) for key in ("pr_number", "owner_run", "old_review"))
    require(all(positive(value) for value in (pr, owner_id, review_id)) and sha(inputs["expected_head"]), "resume locators")
    key = key_for(repo_id, pr, inputs["expected_head"])
    journal = Journal(repo, repo_id)
    intent = journal.read(record_path(key, True))
    owner = validate_intent(intent, repo, repo_id, key)
    require(intent["owner_run"] == owner_id, "resume original owner")
    require(os.environ["GITHUB_REF"] == f"refs/heads/{intent['base_ref']}"
            and source == intent["source_sha"] == intent["base"], "resume protected base source")
    repository(repo, repo_id, source, intent["base_ref"])
    require(0 <= dt.datetime.now(dt.timezone.utc).timestamp() - epoch(owner["created_at"]) <= 604800, "expired intent")
    old = clean_old_review(repo, pr, review_id, intent["head"], owner["created_at"])
    native_resume_run(repo, os.environ["GITHUB_RUN_ID"], source, intent, review_id, completed=False)
    unconsumed(repo, intent, journal)
    record = {"schema": 2, "repository": repo, "repository_id": repo_id, "action": "request", "operation": key,
              "claim_run": os.environ["GITHUB_RUN_ID"], "claim_attempt": "1", "source_sha": source,
              "intent": intent, "intent_commit": journal.oid, "old_review": review_id, "old_head": old["commit_id"]}
    journal.create(record_path(key), record)
    # Recheck the live PR at the effect boundary; a consumed stale claim stays closed.
    current = live_pr(repo, pr, intent["head"], intent["base"])
    require(current["base"]["ref"] == intent["base_ref"] and current["head"]["ref"] == intent["head_ref"], "effect ref drift")
    api(f"repos/{repo}/pulls/{pr}/requested_reviewers", {"reviewers": [BOT]})


def native_resume_run(repo, run_id, source, intent, review_id, completed=True):
    run = api(f"repos/{repo}/actions/runs/{run_id}/attempts/1")
    expected_title = (
        f"First review PR #{intent['pr']} head {intent['head']} "
        f"owner {intent['owner_run']} old review {review_id}"
    )
    require(type(run["id"]) is int and str(run["id"]) == run_id and type(run["run_attempt"]) is int and run["run_attempt"] == 1
            and run["event"] == "workflow_dispatch" and run["path"] == WORKFLOW and run["name"] == "Continue deferred first review request"
            and run["repository"]["full_name"] == repo and run["head_repository"]["full_name"] == repo
            and run["head_sha"] == source == intent["base"] and run["head_branch"] == intent["base_ref"]
            and run["actor"]["login"] == run["triggering_actor"]["login"] == "github-actions[bot]"
            and run["display_title"] == expected_title, "resume native run")
    if completed:
        require(run["status"] == "completed" and run["conclusion"] == "success", "resume native completion")
    else:
        require(run["status"] == "in_progress" and run["conclusion"] is None, "resume native active")
    return run


def verify_receipt(context, record):
    """Read-only Required branch; invoked only after existing verifier-rerun proof."""
    repo, repo_id = context["repository"], context["repository_id"]
    require(set(record) == {"schema", "repository", "repository_id", "action", "operation", "claim_run", "claim_attempt",
                            "source_sha", "intent", "intent_commit", "old_review", "old_head"}
            and type(record["schema"]) is int and record["schema"] == 2 and record["repository"] == repo
            and record["repository_id"] == repo_id and record["action"] == "request" and record["claim_attempt"] == "1"
            and isinstance(record["claim_run"], str) and re.fullmatch(r"[1-9][0-9]*", record["claim_run"])
            and sha(record["intent_commit"]), "resume receipt schema")
    intent = record["intent"]
    key = key_for(repo_id, context["owner"], context["head"])
    require(record["operation"] == key, "resume operation")
    original = validate_intent(intent, repo, repo_id, key)
    require(intent["owner_run"] == context["run_id"] and intent["base"] == context["base"]
            and intent["head"] == context["head"] and intent["base_ref"] == context["base_ref"]
            and intent["source_sha"] == context["controller"], "resume original context")
    journal = Journal(repo, repo_id)
    journal.oid = record["intent_commit"]
    require(journal.read(record_path(key, True)) == intent and journal.read(record_path(key)) is None, "pre-request intent snapshot")
    repository(repo, repo_id, record["source_sha"], intent["base_ref"])
    run = native_resume_run(repo, record["claim_run"], record["source_sha"], intent, record["old_review"])
    job = native_job(repo, run, "Resume deferred first review request", RESUME_STEPS)
    start, end = epoch(job["steps"][2]["started_at"]), epoch(job["steps"][2]["completed_at"])
    require(epoch(original["updated_at"]) <= start, "resume ordering")
    timeline = context["timeline"]
    require(isinstance(timeline, list) and 0 < len(timeline) <= 10
            and all(isinstance(page, list) and len(page) <= 100 and all(isinstance(item, dict) for item in page)
                    for page in timeline), "resume timeline pages")
    events = [item for page in context["timeline"] for item in page if item.get("event") == "review_requested"
              and item.get("requested_reviewer", {}).get("login") == "Copilot"
              and epoch(original["created_at"]) <= epoch(item["created_at"]) <= epoch(context["review_submitted_at"])]
    require(len(events) == 1 and positive(events[0].get("id")) and events[0]["actor"]["login"] == "github-actions[bot]"
            and events[0]["actor"]["type"] == "Bot" and start <= epoch(events[0]["created_at"]) <= end, "resume timeline")
    # The authenticated request event, not entry into the effect step, is the
    # historical cutoff. Reviews arriving before the actual POST still supersede.
    old = clean_old_review(repo, intent["pr"], record["old_review"], intent["head"], original["created_at"],
                           reference_time=events[0]["created_at"])
    require(old["commit_id"] == record["old_head"], "old head proof")


if __name__ == "__main__":
    try:
        {"defer": defer, "locate": locate, "resume": resume}[sys.argv[1]]()
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"First-request continuation stopped: {exc}", file=sys.stderr)
        sys.exit(1)
