"""Read-only native provenance for LI-219 first-request continuation."""
# Exact JSON schema types deliberately reject bool as int and subclasses.
# pylint: disable=unidiomatic-typecheck


import datetime as dt
import hashlib
import json
import re
import subprocess
from urllib.parse import urlencode


PILOTS = {"lightning-it/.github", "lightning-it/shared-assets-lit",
          "lightning-it/ansible-collection-supplementary"}


PRODUCER = ".github/workflows/copilot-review.yml"


WORKFLOW = ".github/workflows/review-request-continuation.yml"


BOT = "copilot-pull-request-reviewer[bot]"
REVIEWERS = frozenset({BOT, "copilot-pull-request-reviewer"})


FAILURE_MARKERS = (
    "unabletoreviewthispullrequest", "cannotreviewthispullrequest", "cannotreviewanyfiles",
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


class ReviewContentError(ValueError):
    """The selected review has malformed or unsuccessful content."""


def normalize(value: str) -> str:
    """Match the protected gate's ASCII fold, contraction and Unicode whitespace rules."""
    ascii_lower = "".join(chr(ord(char) + 32) if "A" <= char <= "Z" else char for char in value)
    expanded = ascii_lower.replace("can't", "cannot").replace("can’t", "cannot").replace("n't", " not").replace("n’t", " not")
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


def api(route, fields=()):
    result = subprocess.run(["gh", "api", route, *fields], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(result.stdout, object_pairs_hook=unique)


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
        pr = empty_owner(repo, run, intent["pr"], intent["base"], intent["head"], intent["base_ref"])
        require(pr["head"]["ref"] == intent["head_ref"], "fallback head ref")
    else:
        recorded_pr(repo, intent, prs[0])
    if completed:
        require(run["status"] == "completed" and run["conclusion"] == "failure", "original not completed failure")
    return run


def empty_owner(repo, run, owner, base, head, base_ref):
    require(repo in PILOTS and positive(owner) and positive(run.get("id"))
            and type(run.get("run_attempt")) is int and run["run_attempt"] in (1, 2)
            and run["event"] == "pull_request_target" and run["path"] == PRODUCER
            and run["name"] == "Current revision review gate" and run["head_sha"] == head
            and run["actor"]["login"] == "litroc"
            and run["triggering_actor"]["login"] == ("litroc" if run["run_attempt"] == 1 else "github-actions[bot]")
            and run["repository"]["full_name"] == repo and run["head_repository"]["full_name"] == repo
            and run["pull_requests"] == [] and sha(base) and sha(head), "fallback native owner")
    pr = branch_pr(repo, run)
    require(pr["number"] == owner and pr["base"]["sha"] == base and pr["base"]["ref"] == base_ref, "fallback PR binding")
    jobs = pages(f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?filter=all", "jobs")
    policy = [job for job in jobs if job.get("name") == "Verify current revision policy"]
    require(len(policy) == 1, "fallback policy job")
    job = policy[0]
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
    require(isinstance(steps, list) and all(isinstance(step, dict) and isinstance(step.get("name"), str) for step in steps)
            and sum(step["name"] == binding for step in steps) == 1, "fallback event binding")
    step = next(step for step in steps if step["name"] == binding)
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
    if isinstance(intent, dict) and intent.get("schema") == 2:
        expected.add("source_ref")
    require(isinstance(intent, dict) and set(intent) == expected and type(intent["schema"]) is int
            and intent["schema"] in (1, 2) and intent["kind"] == "deferred-first-request"
            and intent["repository"] == repo and intent["repository_id"] == repo_id and intent["operation"] == key
            and positive(intent["pr"]) and positive(intent["owner_run"]) and type(intent["owner_attempt"]) is int
            and intent["owner_attempt"] == 1 and intent["event"] == "pull_request_target"
            and intent["action"] in {"opened", "ready_for_review", "synchronize"}
            and intent["author"] == intent["actor"] == intent["triggering_actor"] == "litroc"
            and intent["base_ref"] in {"develop", "main"} and isinstance(intent["head_ref"], str) and intent["head_ref"]
            and all(sha(intent[field]) for field in ("base", "head", "source_sha")), "deferred intent")
    require(key == key_for(repo_id, intent["pr"], intent["head"]), "intent budget key")
    if intent["schema"] == 1:
        # Schema 1 authenticated the protected Default Develop source,
        # independently of its recorded PR base (including Main D != M).
        source_ref = "develop"
    else:
        require(intent["source_ref"] == "develop", "original default controller ref")
        source_ref = intent["source_ref"]
    repository(repo, repo_id, intent["source_sha"], source_ref)
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


def native_resume_run(repo, run_id, source, intent, review_id, completed=True):
    run = api(f"repos/{repo}/actions/runs/{run_id}/attempts/1")
    expected_title = (
        f"First review PR #{intent['pr']} head {intent['head']} "
        f"owner {intent['owner_run']} old review {review_id}"
    )
    require(type(run["id"]) is int and str(run["id"]) == run_id and type(run["run_attempt"]) is int and run["run_attempt"] == 1
            and run["event"] == "workflow_dispatch" and run["path"] == WORKFLOW and run["name"] == "Continue deferred first review request"
            and run["repository"]["full_name"] == repo and run["head_repository"]["full_name"] == repo
            and run["head_sha"] == source
            and ((intent["schema"] == 1 and run["head_branch"] == "develop")
                 or (run["head_branch"] == intent["base_ref"] and source == intent["base"]))
            and run["actor"]["login"] == run["triggering_actor"]["login"] == "github-actions[bot]"
            and run["display_title"] == expected_title, "resume native run")
    repository(repo, intent["repository_id"], source, run["head_branch"])
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
