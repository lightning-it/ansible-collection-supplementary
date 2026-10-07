"""LI-259: bounded Required-verifier recovery, never a review-request writer.

Only a prospectively sealed attempt-two contract can authorize attempts 3/4.
The native job rerun endpoint also reruns its deterministic dependent gate.
No caller retries a write, including a CAS with an unknown response.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import review_request_continuation as proof


WORKFLOW = ".github/workflows/review-infrastructure-retry.yml"
RECEIVER = ".github/workflows/supplementary-current-revision-required.yml"
HELPER = ".github/workflows/current-revision-rerun.yml"
JOB = "Legacy protected current-revision verifier"
AGGREGATE = "Required current-revision workflow"
SOURCE_MARKER = "LI-259 receiver source "
ACQUISITION = "The job was not acquired by Runner of type hosted even after multiple attempts"
POLICY = {"schema": 1, "max_attempt": 4, "total_seconds": 10800,
          "cooldown_seconds": {"3": 1200, "4": 2400}, "runtime_reserve_seconds": 3600,
          "cause": "github-hosted-runner-not-acquired", "receiver": RECEIVER, "job": JOB}


class CandidateClosed(ValueError):
    """A bound candidate lost authority; other candidates remain independent."""


class GlobalReadFailure(RuntimeError):
    """Unavailable or incomplete API evidence must stop the whole sweep."""


def require(condition, message):
    if not condition:
        raise CandidateClosed(message)


def api(route, payload=None, fields=()):
    try:
        return proof.api(route, payload, fields)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        if payload is not None:
            raise
        raise GlobalReadFailure(f"API read failed: {route}") from exc


def pages(route, key=None):
    try:
        return proof.pages(route, key)
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise GlobalReadFailure(f"API inventory failed: {route}") from exc


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def policy_hash():
    return digest({"policy": POLICY, "retry_source": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "proof_source": hashlib.sha256(Path(proof.__file__).read_bytes()).hexdigest()})


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def stamp(now):
    return now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def root_path(run_id):
    require(proof.positive(run_id), "run identity")
    return f"li259/{run_id}"


def source_marker(job, pr):
    markers = [step for step in job["steps"] if step.get("name", "").startswith(SOURCE_MARKER)]
    require(len(markers) == 1 and markers[0]["status"] == "completed"
            and markers[0]["conclusion"] == "success", "receiver has no native source seal")
    value = markers[0]["name"][len(SOURCE_MARKER):]
    binding = f" PR {pr['number']} base {pr['base']['sha']} head {pr['head']['sha']}"
    match = re.fullmatch(r"(lightning-it/\.github)/(" + re.escape(RECEIVER)
                         + r")@refs/heads/(main|develop) ([0-9a-f]{40})" + re.escape(binding), value)
    require(match is not None, "unwired receiver source")
    repository, path, branch, sha = match.groups()
    current = api(f"repos/{repository}/branches/{branch}")
    require(current["name"] == branch and current["protected"] is True
            and current["commit"]["sha"] == sha, "receiver controller drift")
    return {"repository": repository, "path": path, "branch": branch, "sha": sha}


def bound_run(repo, pr, run):
    require(proof.positive(run.get("id")) and proof.positive(run.get("workflow_id")), "run identity")
    workflow_url = f"https://api.github.com/repos/{repo}/actions/required_workflows/{run['workflow_id']}"
    if repo == "lightning-it/.github":
        workflow_url = f"https://api.github.com/repos/{repo}/actions/workflows/{run['workflow_id']}"
    require(run["workflow_url"] == workflow_url and run["path"] == RECEIVER
            and run["event"] == "pull_request_target"
            and run["repository"]["full_name"] == repo
            and run["head_repository"]["full_name"] == repo
            and run["head_sha"] == pr["head"]["sha"]
            and run["head_branch"] == pr["head"]["ref"]
            and run["actor"]["login"] == "litroc", "native receiver authority")
    records = run["pull_requests"]
    require(isinstance(records, list) and len(records) <= 1, "native PR inventory")
    require(run["display_title"] in {f"Protected current revision PR #{pr['number']} {event} {pr['head']['sha']}"
            for event in ("opened", "synchronize", "reopened", "ready_for_review", "edited")}, "native event title")
    # Native pull_request_target runs can have an empty PR projection. The
    # mandatory successful source_marker below binds PR/base/head from the
    # immutable workflow context and authenticates precisely that case.
    if not records:
        return
    recorded = records[0]
    require(recorded["number"] == pr["number"]
            and recorded["url"] == f"https://api.github.com/repos/{repo}/pulls/{pr['number']}"
            and recorded["head"]["sha"] == pr["head"]["sha"]
            and recorded["head"]["ref"] == pr["head"]["ref"]
            and recorded["head"]["repo"]["url"] == f"https://api.github.com/repos/{repo}"
            and recorded["base"]["sha"] == pr["base"]["sha"]
            and recorded["base"]["ref"] == pr["base"]["ref"]
            and recorded["base"]["repo"]["url"] == f"https://api.github.com/repos/{repo}", "native PR binding")


def jobs_for(repo, run_id, attempt, head, *, allow_pre_rollout=False):
    jobs = pages(f"repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs?filter=all", "jobs")
    require(jobs and all(job["run_id"] == run_id and type(job["run_attempt"]) is int
                        and job["run_attempt"] == attempt and job["head_sha"] == head for job in jobs), "native job binding")
    if (allow_pre_rollout and len(jobs) == 1 and jobs[0]["name"] == AGGREGATE
            and isinstance(jobs[0]["steps"], list)
            and not any(step.get("name", "").startswith(SOURCE_MARKER) for step in jobs[0]["steps"])):
        return jobs, jobs[0]
    selected = [job for job in jobs if job["name"] == JOB]
    require(len(selected) == 1, "ambiguous native verifier")
    return jobs, selected[0]


def threads(repo, number):
    # A complete bounded inventory is mandatory, including outdated threads.
    nodes, cursor, seen = [], None, set()
    for _ in range(10):
        result = api("graphql", fields=["-f", "query=query($owner:String!,$name:String!,$number:Int!,$after:String){repository(owner:$owner,name:$name){pullRequest(number:$number){reviewThreads(first:100,after:$after){nodes{id isResolved} pageInfo{hasNextPage endCursor}}}}}",
                    "-f", f"owner={repo.split('/')[0]}", "-f", f"name={repo.split('/')[1]}",
                    "-F", f"number={number}", *([] if cursor is None else ["-f", f"after={cursor}"])])
        proof.require("errors" not in result, "partial thread inventory")
        connection = result["data"]["repository"]["pullRequest"]["reviewThreads"]
        batch = connection["nodes"]
        proof.require(isinstance(batch, list) and len(batch) <= 100, "thread inventory")
        for item in batch:
            proof.require(isinstance(item["id"], str) and item["id"] and item["id"] not in seen,
                          "duplicate thread")
            seen.add(item["id"])
        nodes.extend(batch)
        page = connection["pageInfo"]
        proof.require(type(page["hasNextPage"]) is bool, "thread pagination")
        if not page["hasNextPage"]:
            require(all(item["isResolved"] is True for item in nodes), "unresolved thread")
            return sorted(nodes, key=lambda item: item["id"])
        proof.require(len(batch) == 100 and isinstance(page["endCursor"], str)
                and page["endCursor"] and page["endCursor"] != cursor, "incomplete thread inventory")
        cursor = page["endCursor"]
    raise ValueError("thread inventory limit")


def metadata_revision(repo, pr):
    # A content hash cannot detect edit-and-revert. Bind the producer's native
    # metadata revision to the same live REST input, including both Git OIDs.
    result = api("graphql", fields=["-f", "query=query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){nameWithOwner pullRequest(number:$number){number baseRefOid headRefOid title body lastEditedAt}}}",
                "-f", f"owner={repo.split('/')[0]}", "-f", f"name={repo.split('/')[1]}",
                "-F", f"number={pr['number']}"])
    try:
        proof.require(isinstance(result, dict) and ("errors" not in result
                      or isinstance(result["errors"], list) and not result["errors"]), "partial metadata response")
        repository = result["data"]["repository"]
        current = repository["pullRequest"]
        edited = current["lastEditedAt"]
        if edited is not None:
            proof.epoch(edited)
        binding = (repository["nameWithOwner"], current["number"], current["baseRefOid"],
                   current["headRefOid"], current["title"], current["body"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GlobalReadFailure("invalid metadata revision response") from exc
    require(binding == (repo, pr["number"], pr["base"]["sha"], pr["head"]["sha"],
                        pr["title"], pr["body"] or ""), "metadata snapshot drift")
    return edited


def snapshot(repo, repo_id, pr_number, run_id, writer_source):
    """GET-only binding of the actual native inputs, not caller-supplied claims."""
    require(repo in proof.PILOTS and proof.sha(writer_source), "pilot/controller")
    pr = api(f"repos/{repo}/pulls/{pr_number}")
    require(pr["number"] == pr_number and pr["state"] == "open" and pr["draft"] is False
            and pr["user"]["login"] == "litroc" and pr["user"]["type"] == "User", "live human PR")
    require(pr["head"]["repo"]["full_name"] == repo and pr["base"]["repo"]["full_name"] == repo
            and pr["base"]["ref"] in {"develop", "main"} and pr["head"]["ref"]
            and proof.sha(pr["head"]["sha"]) and proof.sha(pr["base"]["sha"]), "PR refs")
    meta = api(f"repos/{repo}")
    proof.require(meta["full_name"] == repo and str(meta["id"]) == repo_id
                  and meta["default_branch"] == "develop", "repository")
    scheduler = api(f"repos/{repo}/branches/develop")
    require(scheduler["name"] == "develop" and scheduler["protected"] is True
            and proof.sha(scheduler["commit"]["sha"]), "scheduler source")
    branch = api(f"repos/{repo}/branches/{pr['base']['ref']}")
    # Exact current source equality also proves the ancestry required at seal.
    require(branch["name"] == pr["base"]["ref"] and branch["protected"] is True
            and branch["commit"]["sha"] == writer_source == pr["base"]["sha"], "base/controller drift")
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    require(run["id"] == run_id, "target run identity")
    bound_run(repo, pr, run)
    _, original = jobs_for(repo, run_id, 1, pr["head"]["sha"])
    source = source_marker(original, pr)
    checks = pages(f"repos/{repo}/commits/{pr['head']['sha']}/check-runs?filter=all", "check_runs")
    neutral = [check for check in checks if check["name"] == "Current revision review"]
    require(len(neutral) == 1, "ambiguous neutral evidence")
    check = neutral[0]
    require(check["app"]["id"] == 15368 and check["app"]["slug"] == "github-actions"
            and check["status"] == "completed" and check["conclusion"] == "success"
            and check["head_sha"] == pr["head"]["sha"], "neutral evidence")
    try:
        summary = json.loads(check["output"]["summary"], object_pairs_hook=proof.unique)
        require(isinstance(summary, dict) and {"schema", "producer_run_id", "pull_request_number",
                "base_sha", "head_sha", "controller_sha", "pull_request_last_edited_at"} <= summary.keys(), "neutral contract fields")
        owner = summary["producer_run_id"]
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateClosed("invalid neutral evidence") from exc
    require(proof.positive(owner) and type(summary["schema"]) is int and summary["schema"] == 4
            and summary["pull_request_number"] == pr_number
            and summary["base_sha"] == pr["base"]["sha"] and summary["head_sha"] == pr["head"]["sha"]
            and proof.sha(summary["controller_sha"])
            and check["external_id"] == f"mlx90-current-revision:copilot:v6:{pr_number}:{owner}:{pr['base']['sha']}:{pr['head']['sha']}", "neutral binding")
    producer = api(f"repos/{repo}/actions/runs/{owner}")
    require(producer["id"] == owner and producer["path"] == proof.PRODUCER
            and producer["event"] == "pull_request_target" and producer["repository"]["full_name"] == repo
            and producer["head_repository"]["full_name"] == repo and producer["head_sha"] == pr["head"]["sha"]
            and producer["head_branch"] == pr["head"]["ref"] and producer["status"] == "completed"
            and type(producer["run_attempt"]) is int and producer["run_attempt"] in (1, 2)
            and producer["actor"]["login"] == "litroc"
            and producer["triggering_actor"]["login"] == ("litroc" if producer["run_attempt"] == 1 else "github-actions[bot]"), "producer identity")
    producer_jobs = pages(f"repos/{repo}/actions/runs/{owner}/attempts/{producer['run_attempt']}/jobs?filter=all", "jobs")
    verified = [job for job in producer_jobs if job["name"] == "Verify current revision policy"]
    require(len(verified) == 1 and verified[0]["conclusion"] == "success"
            and proof.positive(verified[0]["runner_id"])
            and all(job["run_id"] == owner and job["run_attempt"] == producer["run_attempt"]
                    and job["head_sha"] == pr["head"]["sha"] and job["status"] == "completed"
                    and (job["conclusion"] in ("success", "skipped")
                         or job["name"] == "Request protected verifier re-evaluation" and job["conclusion"] == "failure")
                    for job in producer_jobs), "producer verification")
    policy_steps = [step for step in verified[0]["steps"] if step["name"] == "Verify current Copilot review and resolved findings"]
    require(len(policy_steps) == 1 and policy_steps[0]["conclusion"] == "success", "producer policy execution")
    reviews = pages(f"repos/{repo}/pulls/{pr_number}/reviews")
    reviews = [review for review in reviews if review["commit_id"] == pr["head"]["sha"]
               and review["user"]["login"] in proof.REVIEWERS]
    require(len(reviews) == 1, "ambiguous review evidence")
    review = reviews[0]
    require(review["user"]["type"] == "Bot" and review["state"] in ("COMMENTED", "APPROVED")
            and proof.epoch(review["submitted_at"]) <= proof.epoch(check["completed_at"]), "review identity/time")
    comments = pages(f"repos/{repo}/pulls/{pr_number}/reviews/{review['id']}/comments")
    try:
        proof.require_usable_review_content(review["body"], [comment["body"] for comment in comments])
    except proof.ReviewContentError as exc:
        raise CandidateClosed("unusable review content") from exc
    resolved = threads(repo, pr_number)
    edited = metadata_revision(repo, pr)
    require(summary["pull_request_last_edited_at"] == edited, "neutral metadata revision")
    # Immutable Git sources bind the complete policies and controller inputs.
    # Native receiver marker establishes its actual source, not today's branch.
    return {"repository": repo, "repository_id": repo_id, "pr": pr_number,
            "base": pr["base"]["sha"], "head": pr["head"]["sha"], "base_ref": pr["base"]["ref"],
            "head_ref": pr["head"]["ref"], "run_id": run_id, "workflow_id": run["workflow_id"],
            "receiver": source, "writer_source": writer_source, "scheduler_source": scheduler["commit"]["sha"],
            "producer_run": owner, "producer_attempt": producer["run_attempt"],
            "producer_controller": summary["controller_sha"], "review_id": review["id"],
            "neutral_id": check["id"], "neutral_sha256": digest(check),
            "pull_request_last_edited_at": edited,
            "review_sha256": digest({"review": review, "comments": comments, "threads": resolved}),
            "input_sha256": digest({"title": pr["title"], "body": pr["body"],
                                     "author": {key: pr["user"][key] for key in ("id", "login", "type")},
                                     "labels": sorted(item["name"] for item in pr["labels"])}),
            "policy_sha256": policy_hash()}


def annotations(repo, check):
    count = check["output"]["annotations_count"]
    proof.require(type(count) is int and 0 <= count < 1000, "annotation inventory")
    require(count > 0, "no native failure annotation")
    rows = []
    for page in range(1, (count + 99) // 100 + 1):
        batch = api(f"repos/{repo}/check-runs/{check['id']}/annotations?per_page=100&page={page}")
        proof.require(isinstance(batch, list) and len(batch) == min(100, count - len(rows)), "incomplete annotations")
        rows.extend(batch)
    return rows


def infrastructure_cause(repo, run, head, now):
    require(type(run["run_attempt"]) is int and run["run_attempt"] in (2, 3)
            and run["status"] == "completed" and run["conclusion"] in ("failure", "cancelled")
            and run["triggering_actor"]["login"] == "github-actions[bot]", "terminal native attempt")
    jobs, job = jobs_for(repo, run["id"], run["run_attempt"], head)
    require(job["status"] == "completed" and job["conclusion"] == "cancelled"
            and type(job["runner_id"]) is int and job["runner_id"] == 0
            and job["runner_name"] == "" and job["steps"] == []
            and job["labels"] == ["ubuntu-latest"]
            and job["check_run_url"] == f"https://api.github.com/repos/{repo}/check-runs/{job['id']}", "not native runner acquisition")
    def dependent_failure(item):
        return (item["name"] == AGGREGATE and item["conclusion"] == "failure"
                and proof.positive(item.get("runner_id"))
                and isinstance(item.get("steps"), list)
                and [step["name"] for step in item["steps"] if step["conclusion"] == "failure"]
                    == ["Enforce exactly one terminal verification route"]
                and all(step["status"] == "completed" and step["conclusion"] in ("success", "skipped", "failure")
                        for step in item["steps"]))
    require(all(item["status"] == "completed" and (item["id"] == job["id"]
                or item["conclusion"] in ("success", "skipped")
                or dependent_failure(item)) for item in jobs), "independent failed job")
    # Completion may become visible during the sweep. Observe it against the
    # current clock; the separately sealed budget still uses its original epoch.
    require(proof.epoch(job["created_at"]) <= proof.epoch(job["started_at"])
            <= proof.epoch(job["completed_at"]) <= utc_now().timestamp(), "job timing")
    check = api(f"repos/{repo}/check-runs/{job['id']}")
    require(check["id"] == job["id"] and check["name"] == JOB and check["head_sha"] == head
            and check["app"]["id"] == 15368 and check["app"]["slug"] == "github-actions"
            and check["status"] == "completed" and check["conclusion"] == "cancelled", "native cause check")
    rows = annotations(repo, check)
    failures = [item for item in rows if item["annotation_level"] == "failure"]
    require(len(failures) == 1 and failures[0]["message"] == ACQUISITION
            and failures[0]["path"] == ".github" and failures[0]["start_line"] == 1
            and failures[0]["end_line"] == 1
            and all(item["annotation_level"] in ("failure", "notice") for item in rows), "unclassified native failure")
    return {"code": POLICY["cause"], "job_id": job["id"], "attempt": run["run_attempt"],
            "completed_at": job["completed_at"], "annotations_sha256": digest(rows)}


def validate_seed(seed, repo, repo_id, run_id):
    require(isinstance(seed, dict) and seed["schema"] == 1 and type(seed["schema"]) is int
            and seed["contract"]["repository"] == repo and seed["contract"]["repository_id"] == repo_id
            and seed["contract"]["run_id"] == run_id and seed["contract_sha256"] == digest(seed["contract"])
            and isinstance(seed["contract"]["policy_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", seed["contract"]["policy_sha256"])
            and proof.positive(seed["claim_run"]), "seed contract")
    proof.epoch(seed["created_at"])
    frontier = seed["scheduler_frontier"]
    require(proof.positive(frontier["workflow_id"]) and type(frontier["run_number"]) is int
            and frontier["run_number"] >= 0, "scheduler frontier")


def scheduler_frontier(repo):
    """Freeze an observed native workflow sequence before granting attempt two."""
    workflow = api(f"repos/{repo}/actions/workflows/{WORKFLOW.rsplit('/', 1)[1]}")
    proof.require(proof.positive(workflow["id"]) and workflow["path"] == WORKFLOW, "scheduler workflow")
    result = api(f"repos/{repo}/actions/workflows/{workflow['id']}/runs?per_page=1")
    rows = result["workflow_runs"]
    proof.require(type(result["total_count"]) is int and result["total_count"] >= 0
                  and isinstance(rows, list) and len(rows) == min(1, result["total_count"]), "scheduler frontier inventory")
    number = 0
    if rows:
        proof.require(proof.positive(rows[0]["id"]) and rows[0]["workflow_id"] == workflow["id"]
                      and proof.positive(rows[0]["run_number"]), "scheduler frontier binding")
        number = rows[0]["run_number"]
    return {"workflow_id": workflow["id"], "run_number": number}


def elected_claimant(repo, seed, cause, attempt):
    """One immutable native run owns each slot, even if its Git CAS stays unseen.

    Never skip a missing run number: delayed visibility/deletion cannot elect a
    successor. Cancelled or rerun owners do not restore the slot either.
    """
    frontier = seed["scheduler_frontier"]
    runs = pages(f"repos/{repo}/actions/workflows/{frontier['workflow_id']}/runs?created=>={seed['created_at']}", "workflow_runs")
    for run in runs:
        proof.require(run["workflow_id"] == frontier["workflow_id"] and run["path"] == WORKFLOW
                      and run["event"] == "schedule" and proof.positive(run["run_number"])
                      and run["repository"]["full_name"] == repo
                      and run["head_repository"]["full_name"] == repo, "scheduler inventory binding")
    runs = [run for run in runs if run["run_number"] > frontier["run_number"]]
    numbers = sorted(run["run_number"] for run in runs)
    proof.require(numbers and all(number == frontier["run_number"] + index
                                  for index, number in enumerate(numbers, 1)),
                  "incomplete scheduler sequence")
    eligible_at = proof.epoch(cause["completed_at"]) + POLICY["cooldown_seconds"][str(attempt)]
    candidates = [run for run in runs if proof.epoch(run["created_at"]) >= eligible_at]
    proof.require(candidates, "scheduler claimant not visible")
    return min(candidates, key=lambda run: run["run_number"])["id"]


def writer(repo, source, path, event):
    require(os.environ["GITHUB_RUN_ATTEMPT"] == "1" and os.environ["GITHUB_EVENT_NAME"] == event
            and os.environ["GITHUB_REF_PROTECTED"] == "true"
            and os.environ["GITHUB_WORKFLOW_SHA"] == source, "protected writer environment")
    run_id = int(os.environ["GITHUB_RUN_ID"])
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    require(run["id"] == run_id and type(run["run_attempt"]) is int and run["run_attempt"] == 1
            and run["path"] == path and run["event"] == event and run["head_sha"] == source
            and run["repository"]["full_name"] == repo and run["head_repository"]["full_name"] == repo
            and run["actor"]["login"] == run["triggering_actor"]["login"]
            and run["actor"]["login"] in ({"github-actions[bot]"} if event == "workflow_dispatch"
                                             else {"litroc", "github-actions[bot]"}), "native writer")
    return run_id


def scheduler_claimant(repo, seed, claimant, *, posting=False):
    """Re-read actual native authority; election alone proves only ownership."""
    run = api(f"repos/{repo}/actions/runs/{claimant}")
    require(run["id"] == claimant and run["workflow_id"] == seed["scheduler_frontier"]["workflow_id"]
            and run["path"] == WORKFLOW and run["event"] == "schedule"
            and run["head_sha"] == seed["contract"]["scheduler_source"]
            and run["head_branch"] == "develop"
            and type(run["run_attempt"]) is int and run["run_attempt"] == 1
            and run["repository"]["full_name"] == repo and run["head_repository"]["full_name"] == repo
            and run["actor"]["login"] in {"litroc", "github-actions[bot]"}
            and run["triggering_actor"]["login"] == run["actor"]["login"]
            and run["status"] in ({"in_progress"} if posting else {"in_progress", "completed"}), "native scheduler claimant")


def readback_only(repo, repo_id, path):
    # No write follows an unknown CAS or effect result, even if our claim is seen.
    try:
        return proof.Journal(repo, repo_id).read(path)
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        return None


def seal(repo, repo_id, pr, run_id, source, now):
    # This optional grant must not narrow the existing attempt-two entitlement.
    # snapshot() and receiver() retain strict LI-259 authority for every seed.
    if repo not in proof.PILOTS:
        return False
    candidate = api(f"repos/{repo}/pulls/{pr}")
    if (candidate["user"]["login"] != "litroc" or candidate["user"]["type"] != "User"
            or candidate["head"]["repo"]["full_name"] != repo
            or candidate["base"]["repo"]["full_name"] != repo):
        return False
    claim_run = writer(repo, source, HELPER, "workflow_dispatch")
    live = proof.live_pr(repo, pr)
    _, original = jobs_for(repo, run_id, 1, live["head"]["sha"], allow_pre_rollout=True)
    if not any(step.get("name", "").startswith(SOURCE_MARKER) for step in original["steps"]):
        # A pre-rollout run keeps its original LI-219 attempt-two route. It
        # receives no seed and consequently no additional technical authority.
        require(proof.live_pr(repo, pr) == live, "legacy fallback live binding drift")
        return False
    contract = snapshot(repo, repo_id, pr, run_id, source)
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    require(run["run_attempt"] == 1 and run["status"] == "completed", "seal before attempt two")
    path = root_path(run_id) + "/seed.json"
    journal = proof.Journal(repo, repo_id)
    previous = journal.read(path)
    if previous is not None:
        validate_seed(previous, repo, repo_id, run_id)
        require(previous["contract"] == contract and previous["claim_run"] == claim_run, "seed already owned")
        return True
    record = {"schema": 1, "contract": contract, "contract_sha256": digest(contract),
              "scheduler_frontier": scheduler_frontier(repo),
              "created_at": stamp(now), "claim_run": claim_run}
    try:
        journal.create(path, record)
    except (ValueError, OSError, subprocess.SubprocessError):
        readback_only(repo, repo_id, path)
        raise ValueError("unconfirmed seed; readback only") from None
    require(snapshot(repo, repo_id, pr, run_id, source) == contract, "post-seal drift")
    return True


def original_consumption(journal, seed):
    c = seed["contract"]
    key = f"li219-verifier-operation:v1:{c['pr']}:{c['base']}:{c['head']}:{c['run_id']}"
    record = journal.read(proof.record_path(key))
    require(record is not None and record["schema"] == 1 and record["action"] == "rerun"
            and record["operation"] == key and record["repository"] == c["repository"]
            and record["repository_id"] == c["repository_id"] and record["claim_run"] == str(seed["claim_run"])
            and record["claim_attempt"] == "1" and record["source_sha"] == c["writer_source"], "original event consumption")
    caller = api(f"repos/{c['repository']}/actions/runs/{seed['claim_run']}")
    require(caller["id"] == seed["claim_run"] and caller["run_attempt"] == 1
            and caller["path"] == HELPER and caller["event"] == "workflow_dispatch"
            and caller["head_sha"] == c["writer_source"]
            and caller["repository"]["full_name"] == c["repository"]
            and caller["head_repository"]["full_name"] == c["repository"]
            and caller["actor"]["login"] == "github-actions[bot]"
            and caller["triggering_actor"]["login"] == "github-actions[bot]", "original event caller")


def validate_claim(claim, seed, attempt):
    require(isinstance(claim, dict) and type(claim["schema"]) is int and claim["schema"] == 1 and claim["attempt"] == attempt
            and type(claim["attempt"]) is int and claim["contract_sha256"] == seed["contract_sha256"]
            and claim["state"] == "consumed-before-post" and proof.positive(claim["claim_run"])
            and claim["cause"]["attempt"] == attempt - 1 and claim["cause"]["code"] == POLICY["cause"], "technical claim")
    started = proof.epoch(seed["created_at"])
    claimed = proof.epoch(claim["created_at"])
    require(started <= proof.epoch(claim["cause"]["completed_at"])
            and claimed >= proof.epoch(claim["cause"]["completed_at"]) + POLICY["cooldown_seconds"][str(attempt)]
            and claimed + POLICY["runtime_reserve_seconds"] <= started + POLICY["total_seconds"], "claimed budget")


def terminal(journal, path, seed, reason, now, attempt=None):
    record = {"schema": 1, "contract_sha256": seed["contract_sha256"],
              "state": reason, "created_at": stamp(now), "native_attempt": attempt,
              "max_attempt": POLICY["max_attempt"],
              "deadline_epoch": int(proof.epoch(seed["created_at"])) + POLICY["total_seconds"]}
    try:
        journal.create(path, record)
    except (ValueError, OSError, subprocess.SubprocessError):
        if readback_only(journal.repo, journal.repo_id, path) != record:
            raise GlobalReadFailure("terminal record not confirmed") from None
    print(f"LI-259 run {seed['contract']['run_id']}: terminal {reason}")


def recover(repo, repo_id, run_id, source, now):
    claimant = writer(repo, source, WORKFLOW, "schedule")
    path = root_path(run_id)
    journal = proof.Journal(repo, repo_id)
    seed = journal.read(path + "/seed.json")
    if seed is None or journal.read(path + "/terminal.json") is not None:
        return "inactive"
    validate_seed(seed, repo, repo_id, run_id)
    try:
        return recover_bound(repo, repo_id, run_id, source, now, claimant, path, journal, seed)
    except CandidateClosed:
        terminal(proof.Journal(repo, repo_id), path + "/terminal.json", seed, "contract-drift", now)
        return "terminal"


def recover_bound(repo, repo_id, run_id, source, now, claimant, path, journal, seed):
    c = seed["contract"]
    deadline = proof.epoch(seed["created_at"]) + POLICY["total_seconds"]
    observed = api(f"repos/{repo}/actions/runs/{run_id}")
    observed_attempt = observed["run_attempt"]
    require(type(observed_attempt) is int, "native attempt type")
    if observed_attempt in (2, 3) and journal.read(path + f"/attempt-{observed_attempt + 1}.json") is not None:
        # The claimed effect has not appeared natively. Even after expiry or
        # drift this worker is permanently GET-only; a new event is no authority.
        return "consumed-readback-only"
    # Native completed-at and run-number evidence survives an unobservable Git
    # CAS. Check its fixed owner before any terminal write on drift or expiry.
    if observed_attempt in (2, 3) and observed["status"] == "completed":
        try:
            observed_cause = infrastructure_cause(repo, observed, c["head"], now)
        except CandidateClosed:
            observed_cause = None
        if (observed_cause is not None
                and now.timestamp() >= proof.epoch(observed_cause["completed_at"])
                + POLICY["cooldown_seconds"][str(observed_attempt + 1)]
                and elected_claimant(repo, seed, observed_cause, observed_attempt + 1) != claimant):
            readback_only(repo, repo_id, path + f"/attempt-{observed_attempt + 1}.json")
            return "native-owner-readback-only"
    original_consumption(journal, seed)
    try:
        require(source == c["scheduler_source"]
                and snapshot(repo, repo_id, c["pr"], run_id, c["writer_source"]) == c, "contract drift")
    except CandidateClosed:
        terminal(journal, path + "/terminal.json", seed, "contract-drift", now, observed_attempt)
        return "terminal"
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    attempt = run["run_attempt"]
    require(type(attempt) is int and 2 <= attempt <= POLICY["max_attempt"], "native attempt limit")
    for number in range(3, attempt + 1):
        claim = journal.read(path + f"/attempt-{number}.json")
        validate_claim(claim, seed, number)
    if run["status"] != "completed":
        return "active"
    if run["conclusion"] == "success":
        terminal(journal, path + "/terminal.json", seed, "verified", now, attempt)
        return "terminal"
    if attempt >= POLICY["max_attempt"] or now.timestamp() + POLICY["runtime_reserve_seconds"] > deadline:
        terminal(journal, path + "/terminal.json", seed, "budget-exhausted", now, attempt)
        return "terminal"
    try:
        cause = infrastructure_cause(repo, run, c["head"], now)
    except CandidateClosed:
        terminal(journal, path + "/terminal.json", seed, "non-retryable-native-failure", now, attempt)
        return "terminal"
    next_attempt = attempt + 1
    if now.timestamp() < proof.epoch(cause["completed_at"]) + POLICY["cooldown_seconds"][str(next_attempt)]:
        return "cooldown"
    claim_path = path + f"/attempt-{next_attempt}.json"
    if journal.read(claim_path) is not None:
        return "consumed-readback-only"
    if elected_claimant(repo, seed, cause, next_attempt) != claimant:
        # The original native owner may have timed out before its CAS was
        # observable. A later scheduler never retries that ambiguous write.
        readback_only(repo, repo_id, claim_path)
        return "native-owner-readback-only"
    record = {"schema": 1, "contract_sha256": seed["contract_sha256"], "attempt": next_attempt,
              "cause": cause, "created_at": stamp(now), "claim_run": claimant, "state": "consumed-before-post"}
    validate_claim(record, seed, next_attempt)
    try:
        journal.create(claim_path, record)
    except (ValueError, OSError, subprocess.SubprocessError):
        readback_only(repo, repo_id, claim_path)
        return "unconfirmed-claim-readback-only"
    try:
        original_consumption(proof.Journal(repo, repo_id), seed)
        require(snapshot(repo, repo_id, c["pr"], run_id, c["writer_source"]) == c, "post-claim contract drift")
        current = api(f"repos/{repo}/actions/runs/{run_id}")
        require(infrastructure_cause(repo, current, c["head"], now) == cause, "post-claim native drift")
        require(elected_claimant(repo, seed, cause, next_attempt) == claimant, "post-claim native owner drift")
        fresh = proof.Journal(repo, repo_id)
        require(fresh.read(claim_path) == record and fresh.read(path + "/terminal.json") is None, "post-claim readback")
        scheduler_claimant(repo, seed, claimant, posting=True)
        require(utc_now().timestamp() + POLICY["runtime_reserve_seconds"] <= deadline, "post-claim deadline")
    except CandidateClosed:
        # The durable consumed slot closes this effect forever. Do not write a
        # second record or POST after the CAS, including when authority drifts.
        readback_only(repo, repo_id, claim_path)
        return "consumed-readback-only"
    try:
        api(f"repos/{repo}/actions/jobs/{cause['job_id']}/rerun", {})
    except (OSError, subprocess.SubprocessError, ValueError):
        api(f"repos/{repo}/actions/runs/{run_id}")
        return "unknown-post-readback-only"
    return "dispatched"


def receiver(repo, repo_id, run_id, attempt, now):
    require(type(attempt) is int and attempt in (3, 4), "receiver attempt")
    journal = proof.Journal(repo, repo_id)
    path = root_path(run_id)
    seed = journal.read(path + "/seed.json")
    validate_seed(seed, repo, repo_id, run_id)
    require(journal.read(path + "/terminal.json") is None, "terminal operation")
    original_consumption(journal, seed)
    c = seed["contract"]
    require(snapshot(repo, repo_id, c["pr"], run_id, c["writer_source"]) == c, "receiver contract drift")
    require(os.environ["WORKFLOW_SHA"] == c["receiver"]["sha"]
            and os.environ["WORKFLOW_REF"] == f"{c['receiver']['repository']}/{RECEIVER}@refs/heads/{c['receiver']['branch']}"
            and os.environ["EVENT_BASE"] == c["base"] and os.environ["EVENT_HEAD"] == c["head"]
            and os.environ["PR_NUMBER"] == str(c["pr"]), "receiver execution contract")
    require(now.timestamp() <= proof.epoch(seed["created_at"]) + POLICY["total_seconds"], "receiver deadline")
    for number in range(3, attempt + 1):
        claim = journal.read(path + f"/attempt-{number}.json")
        validate_claim(claim, seed, number)
        previous = api(f"repos/{repo}/actions/runs/{run_id}/attempts/{number - 1}")
        require(infrastructure_cause(repo, previous, c["head"], now) == claim["cause"], "receiver native cause")
        require(elected_claimant(repo, seed, claim["cause"], number) == claim["claim_run"], "receiver native owner")
        scheduler_claimant(repo, seed, claim["claim_run"])
    run = api(f"repos/{repo}/actions/runs/{run_id}")
    require(run["run_attempt"] == attempt and run["triggering_actor"]["login"] == "github-actions[bot]"
            and proof.epoch(run["run_started_at"]) >= proof.epoch(claim["created_at"]), "receiver native attempt")
    require(utc_now().timestamp() <= proof.epoch(seed["created_at"]) + POLICY["total_seconds"], "final receiver deadline")


def active_seed_runs(repo, repo_id):
    """Inventory the immutable journal, including closed/draft/old-head PRs."""
    try:
        journal = proof.Journal(repo, repo_id)
        journal.read("manifest.json")  # Authenticate the journal repository binding.
        commit = api(f"repos/{repo}/git/commits/{journal.oid}")
        proof.require(commit["sha"] == journal.oid and proof.sha(commit["tree"]["sha"]), "journal tree binding")
        tree_sha = commit["tree"]["sha"]
        tree = api(f"repos/{repo}/git/trees/{tree_sha}?recursive=1")
        proof.require(tree["sha"] == tree_sha and tree["truncated"] is False
                      and isinstance(tree["tree"], list) and len(tree["tree"]) <= 10000, "journal tree inventory")
        entries = {}
        for entry in tree["tree"]:
            path = entry["path"]
            proof.require(isinstance(path, str) and path and path not in entries
                          and proof.sha(entry["sha"]), "journal tree entry")
            entries[path] = entry
        runs = []
        for path, entry in entries.items():
            match = re.fullmatch(r"li259/([1-9][0-9]*)/seed\.json", path)
            if match:
                proof.require(entry["type"] == "blob" and entry["mode"] == "100644", "journal seed entry")
                if f"li259/{match[1]}/terminal.json" not in entries:
                    runs.append(int(match[1]))
        proof.require(len(runs) < 1000, "active seed inventory limit")
        return sorted(runs)
    except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        raise GlobalReadFailure("active seed inventory failed") from exc


def main():
    if os.environ.get("LI259_INFRA_RETRY") != "enabled" or os.environ.get("LI219_EVENT_MODE") != "enabled":
        require(sys.argv[1] != "receiver", "receiver feature disabled")
        return
    repo, repo_id = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REPOSITORY_ID"]
    now = utc_now()
    mode = sys.argv[1]
    if mode == "seal":
        seal(repo, repo_id, int(sys.argv[2]), int(sys.argv[3]), os.environ["GITHUB_WORKFLOW_SHA"], now)
    elif mode == "receiver":
        receiver(repo, repo_id, int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"]), now)
    elif mode == "reconcile":
        # Seed authority survives PR listing filters. Observe drift once and
        # close it durably before an old head or ready/open state can return.
        for run_id in active_seed_runs(repo, repo_id):
            print(f"LI-259 run {run_id}: {recover(repo, repo_id, run_id, os.environ['GITHUB_WORKFLOW_SHA'], now)}")
    else:
        raise ValueError("unknown mode")


if __name__ == "__main__":
    main()
