"""Execute actual embedded workflow steps and existing scheduled caller with stateful native API evidence."""

import copy
import datetime as dt
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPO = "lightning-it/ansible-collection-supplementary"
RID = "1103407173"
BASE, HEAD, SOURCE, OLD, INITIAL = (char * 40 for char in "abcde")
# Supplementary develop requests execute the exact protected PR base controller.
SOURCE = BASE
KEY = f"li219-review-request:v1:{RID}:23:{HEAD}"
REQUEST = "operations/" + hashlib.sha256(KEY.encode()).hexdigest() + ".json"
INTENT = REQUEST.replace("operations/", "deferred/")
BOT = "copilot-pull-request-reviewer[bot]"

MOCK = r"""#!/usr/bin/env python3
import base64, json, os, sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
args = sys.argv[1:]
assert args[0] == 'api'
file = Path(os.environ['STATE'])
s = json.loads(file.read_text())
route = next(a for a in args if a.startswith('repos/') or a == 'graphql')
fields = dict(arg.split('=', 1) for arg in args if '=' in arg)
payload = json.load(sys.stdin) if '--input' in args else None
s['calls'].append({'route': route, 'payload': payload})
result, code = None, 0
def blob(value):
    if value is None: return None
    text = json.dumps(value)
    return {'__typename': 'Blob', 'isTruncated': False, 'byteSize': len(text.encode()), 'text': text}
if route == 'graphql' and payload:
    value = payload['variables']['input']
    assert value['branch'] == {'repositoryNameWithOwner': s['repo'], 'branchName': 'lit-review-operations'}
    assert set(value['fileChanges']) == {'additions'} and len(value['fileChanges']['additions']) == 1
    old = value['expectedHeadOid']
    if old != s['oid'] or s.get('lose_cas'):
        result, code = {'errors': [{'message': 'CAS lost'}]}, 1
    else:
        item = value['fileChanges']['additions'][0]
        assert item['path'] not in s['versions'][old]
        oid = format(int(old, 16) + 1, '040x')
        s['versions'][oid] = {**s['versions'][old], item['path']: json.loads(base64.b64decode(item['contents']))}
        s['oid'] = oid
        if s.get('drift_after_cas') and item['path'].startswith('operations/'):
            s['routes']['repos/' + s['repo'] + '/pulls/23']['head']['ref'] = 'fix/changed'
        result = {'data': {'createCommitOnBranch': {'commit': {'oid': oid, 'parents': {'nodes': [{'oid': old}]}}}}}
        if s.get('lost_cas_response'): result, code = None, 42
elif route == 'graphql':
    oid = fields['oid']
    assert fields['manifest'] == oid + ':manifest.json'
    path = fields['record'].split(':', 1)[1]
    result = {'data': {'repository': {'nameWithOwner': s['repo'], 'source': {'__typename': 'Commit', 'oid': oid},
        'manifest': blob({'schema': 1, 'repository': s['repo'], 'repository_id': s['repo_id'],
                          'ref': 'refs/heads/lit-review-operations'}),
        'record': blob(s['versions'][oid].get(path))}}}
elif '/git/ref/' in route:
    result = {'ref': 'refs/heads/lit-review-operations', 'object': {'type': 'commit',
                                                            'sha': s.get('stale_ref', s['oid'])}}
elif '/compare/' in route:
    result = s.get('ancestry', {'status': 'identical'})
elif payload is not None:
    if route.endswith('/dispatches'):
        assert route.endswith('/review-request-continuation.yml/dispatches')
        s['dispatches'].append(payload)
    elif route.endswith('/requested_reviewers'):
        assert payload == {'reviewers': ['copilot-pull-request-reviewer[bot]']}
        s['requests'].append(payload)
        s['routes'][route] = {'users': [{'login': 'copilot-pull-request-reviewer[bot]'}]}
        if s.get('lost_post_response'): code = 42
    else:
        raise AssertionError('unexpected mutation ' + route)
elif '/actions/workflows/' in route and '/runs?' in route:
    name = route.split('/actions/workflows/', 1)[1].split('/', 1)[0]
    rows = [row for row in s.get('history', []) if row['path'] == '.github/workflows/' + name]
    result = {'total_count': len(rows), 'workflow_runs': rows}
else:
    parsed = urlsplit(route)
    result = s['routes'].get(route, s['routes'].get(parsed.path))
    assert result is not None, route
    if isinstance(result, list) and parse_qs(parsed.query).get('page', ['1'])[0] != '1': result = []
file.write_text(json.dumps(s))
if result is not None: print(json.dumps(result))
sys.exit(code)
"""


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.file = self.root / "state.json"
        self.event = self.root / "event.json"
        (self.root / "gh").write_text(MOCK)
        (self.root / "gh").chmod(0o755)
        self.now = dt.datetime.now(dt.UTC).replace(microsecond=0)

        def at(seconds):
            return (self.now + dt.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

        self.at = at
        pr = {
            "id": 23,
            "number": 23,
            "state": "open",
            "draft": False,
            "user": {"login": "litroc", "type": "User"},
            "head": {"sha": HEAD, "ref": "fix/new", "repo": {"full_name": REPO}},
            "base": {"sha": BASE, "ref": "develop", "repo": {"full_name": REPO}},
        }
        recorded = copy.deepcopy(pr)
        for side in ("head", "base"):
            recorded[side]["repo"] = {"url": "https://api.github.com/repos/" + REPO}
        owner = {
            "id": 77,
            "run_attempt": 1,
            "event": "pull_request_target",
            "path": ".github/workflows/copilot-review.yml",
            "name": "Current revision review gate",
            "head_sha": HEAD,
            "head_branch": "fix/new",
            "repository": {"full_name": REPO},
            "head_repository": {"full_name": REPO},
            "actor": {"login": "litroc"},
            "triggering_actor": {"login": "litroc"},
            "pull_requests": [recorded],
            "status": "completed",
            "conclusion": "failure",
            "created_at": at(-120),
            "updated_at": at(2),
        }
        names = [
            "Set up job",
            "Materialize the protected operation claim",
            "Request Copilot review for the current revision",
            "Complete job",
        ]
        intervals = [(-110, -109), (-109, -108), (-108, 1), (1, 2)]
        steps = [
            {
                "name": name,
                "number": index + 1,
                "status": "completed",
                "conclusion": "success",
                "started_at": at(intervals[index][0]),
                "completed_at": at(intervals[index][1]),
            }
            for index, name in enumerate(names)
        ]
        job = {
            "id": 78,
            "run_id": 77,
            "run_attempt": 1,
            "head_sha": HEAD,
            "name": "Request Copilot review for current revision",
            "status": "completed",
            "conclusion": "success",
            "runner_id": 4,
            "started_at": at(-110),
            "completed_at": at(2),
            "steps": steps,
        }
        review = {
            "id": 17,
            "commit_id": OLD,
            "user": {"login": BOT, "type": "Bot"},
            "state": "COMMENTED",
            "body": "Reviewed old head.",
            "submitted_at": at(-20),
        }
        prefix = "repos/" + REPO
        self.state = {
            "repo": REPO,
            "repo_id": RID,
            "oid": INITIAL,
            "versions": {INITIAL: {}},
            "calls": [],
            "requests": [],
            "dispatches": [],
            "routes": {
                prefix: {"full_name": REPO, "id": int(RID), "default_branch": "develop"},
                prefix + "/branches/develop": {"name": "develop", "protected": True, "commit": {"sha": SOURCE}},
                prefix + "/pulls/23": pr,
                prefix + "/pulls": [pr],
                prefix + "/actions/runs/77/attempts/1": owner,
                prefix + "/actions/runs/77": owner,
                prefix + "/actions/runs/77/attempts/1/jobs": {"total_count": 1, "jobs": [job]},
                prefix + "/actions/runs": {"total_count": 1, "workflow_runs": [owner]},
                prefix + "/commits/" + HEAD + "/check-runs": {"total_count": 0, "check_runs": []},
                prefix + "/pulls/23/reviews/17": review,
                prefix + "/pulls/23/reviews": [review],
                prefix + "/pulls/23/reviews/17/comments": [],
                prefix + "/issues/23/comments": [],
                prefix + "/pulls/23/requested_reviewers": {"users": []},
            },
        }
        resume = {
            **owner,
            "id": 88,
            "event": "workflow_dispatch",
            "path": ".github/workflows/review-request-continuation.yml",
            "name": "Continue deferred first review request",
            "head_sha": SOURCE,
            "head_branch": "develop",
            "actor": {"login": "github-actions[bot]"},
            "triggering_actor": {"login": "github-actions[bot]"},
            "status": "in_progress",
            "conclusion": None,
            "display_title": f"First review PR #23 head {HEAD} owner 77 old review 17",
        }
        self.state["routes"][prefix + "/actions/runs/88/attempts/1"] = resume
        self.state["routes"][prefix + "/actions/runs/89/attempts/1"] = {**resume, "id": 89}
        self.env = {
            **os.environ,
            "PATH": str(self.root) + ":" + os.environ["PATH"],
            "STATE": str(self.file),
            "RUNNER_TEMP": str(self.root),
            "GITHUB_EVENT_PATH": str(self.event),
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_REPOSITORY_ID": RID,
            "WORKFLOW_SHA": SOURCE,
            "GITHUB_REF": "refs/heads/develop",
            "GITHUB_REF_PROTECTED": "true",
            "GITHUB_RUN_ID": "77",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_EVENT_NAME": "pull_request_target",
            "GITHUB_ACTOR": "litroc",
            "GITHUB_TRIGGERING_ACTOR": "litroc",
            "LI219_EVENT_MODE": "enabled",
            "PR_NUMBER": "23",
            "EXPECTED_HEAD": HEAD,
            "EXPECTED_BASE": BASE,
        }
        self.workflow = yaml.safe_load((ROOT / ".github/workflows/review-request-continuation.yml").read_text())
        self.original = yaml.safe_load((ROOT / ".github/workflows/copilot-review.yml").read_text())
        # Exercise the real local six-job owner topology, including failed policy
        # and inactive handoffs; only the actual original request job must pass.
        others = [
            {
                "id": 100 + index,
                "run_id": 77,
                "run_attempt": 1,
                "head_sha": HEAD,
                "name": definition["name"],
                "status": "completed",
                "conclusion": "failure" if name == "verify-current-revision-policy" else "skipped",
                "runner_id": None,
                "steps": [],
            }
            for index, (name, definition) in enumerate(self.original["jobs"].items())
            if name != "request-current-revision-review"
        ]
        self.route("/actions/runs/77/attempts/1/jobs").update(total_count=6, jobs=[job, *others])

    def route(self, suffix):
        return self.state["routes"]["repos/" + REPO + suffix]

    def execute(self, shell, event, changes=None):
        self.file.write_text(json.dumps(self.state))
        self.event.write_text(json.dumps(event))
        result = subprocess.run(  # noqa: S603 -- Actual embedded workflow with local mock transport.
            ["/bin/bash", "-euo", "pipefail", "-c", shell],
            env={**self.env, **(changes or {})},
            text=True,
            capture_output=True,
            timeout=35,
        )
        self.state = json.loads(self.file.read_text())
        return result

    def defer(self):
        steps = self.original["jobs"]["request-current-revision-review"]["steps"]
        caller = steps[1]["run"]
        start = caller.index("if reviewer_is_requested; then")
        end = caller.index("else\n", start)
        # Execute the actual Pending branch and actual materialization; the
        # native author/run/source/PR proof inside defer is not replaced.
        shell = steps[0]["run"] + "\nreviewer_is_requested() { return 0; }\n" + caller[start:end] + "fi\n"
        return self.execute(shell, {"action": "synchronize", "pull_request": self.route("/pulls/23")})

    def consumer(self, **changes):
        steps = self.workflow["jobs"]["resume"]["steps"]
        return self.execute(
            "\n".join(step["run"] for step in steps),
            {"inputs": {"pr_number": "23", "expected_head": HEAD, "owner_run": "77", "old_review": "17"}},
            {
                "GITHUB_EVENT_NAME": "workflow_dispatch",
                "GITHUB_ACTOR": "github-actions[bot]",
                "GITHUB_TRIGGERING_ACTOR": "github-actions[bot]",
                "GITHUB_RUN_ID": "88",
                **changes,
            },
        )

    def locator(self, companion=False):
        steps = self.workflow["jobs"]["locate"]["steps"]
        event = (
            {"action": "completed", "workflow_run": self.route("/actions/runs/77")}
            if companion
            else {
                "action": "submitted",
                "pull_request": self.route("/pulls/23"),
                "review": self.route("/pulls/23/reviews/17"),
            }
        )
        return self.execute(
            "\n".join(step["run"] for step in steps),
            event,
            {"GITHUB_EVENT_NAME": "workflow_run" if companion else "pull_request_review"},
        )

    def test_actual_pending_then_both_locators_and_duplicate_consumer_share_one_request(self):
        result = self.defer()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(INTENT, self.state["versions"][self.state["oid"]])
        self.assertNotIn(REQUEST, self.state["versions"][self.state["oid"]])
        self.assertEqual([], self.state["requests"])
        for companion in (False, True):
            result = self.locator(companion)
            self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, len(self.state["dispatches"]))
        result = self.consumer()
        self.assertEqual(0, result.returncode, result.stderr)
        receipt = self.state["versions"][self.state["oid"]][REQUEST]
        self.assertEqual(2, receipt["schema"])
        self.assertEqual((OLD, HEAD, SOURCE), (receipt["old_head"], receipt["intent"]["head"], receipt["source_sha"]))
        self.assertNotEqual(0, self.consumer(GITHUB_RUN_ID="89").returncode)
        self.assertEqual(1, len(self.state["requests"]))

    def test_old_completion_before_intent_is_recovered_by_owner_completion(self):
        self.assertEqual(0, self.locator().returncode)
        self.assertEqual([], self.state["dispatches"])
        self.assertEqual(0, self.defer().returncode)
        result = self.locator(companion=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(0, self.consumer().returncode)
        self.assertEqual(1, len(self.state["requests"]))

    def test_old_completion_before_new_owner_with_stale_pending_is_reconciled(self):
        old_time = self.at(-150)  # Original new-head run starts at -120.
        self.route("/pulls/23/reviews/17")["submitted_at"] = old_time
        self.route("/pulls/23/reviews")[0]["submitted_at"] = old_time
        self.assertEqual(0, self.defer().returncode)
        self.route("/pulls/23/requested_reviewers")["users"] = [{"login": BOT}]
        self.assertNotEqual(0, self.locator().returncode)
        self.assertNotEqual(0, self.locator(companion=True).returncode)
        self.route("/pulls/23/requested_reviewers")["users"] = []
        result = self.execute("python3 " + str(ROOT / "scripts/review-event-reconcile.py"), {})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(self.state["dispatches"]))
        result = self.consumer()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotEqual(0, self.consumer(GITHUB_RUN_ID="89").returncode)
        self.assertEqual(1, len(self.state["requests"]))

    def test_pre_owner_quota_expired_or_foreign_old_review_still_blocks(self):
        for changes in (
            {"body": "Quota exceeded", "submitted_at": self.at(-150)},
            {"submitted_at": self.at(-604801)},
            {"user": {"login": "mallory", "type": "User"}},
            {"submitted_at": self.at(60)},
        ):
            with self.subTest(changes=changes):
                self.setUp()
                self.assertEqual(0, self.defer().returncode)
                self.route("/pulls/23/reviews/17").update(changes)
                self.route("/pulls/23/reviews")[0].update(changes)
                self.assertNotEqual(0, self.consumer().returncode)
                self.assertEqual([], self.state["requests"])

    def test_both_events_before_visibility_then_existing_reconciler_once(self):
        self.assertEqual(0, self.defer().returncode)
        jobs = copy.deepcopy(self.route("/actions/runs/77/attempts/1/jobs"))
        self.state["routes"]["repos/" + REPO + "/actions/runs/77/attempts/1/jobs"] = {"total_count": 0, "jobs": []}
        self.assertNotEqual(0, self.locator().returncode)
        self.assertNotEqual(0, self.locator(companion=True).returncode)
        self.state["routes"]["repos/" + REPO + "/actions/runs/77/attempts/1/jobs"] = jobs
        self.route("/pulls/23/requested_reviewers")["users"] = [{"login": BOT}]
        script = "python3 " + str(ROOT / "scripts/review-event-reconcile.py")
        result = self.execute(script, {})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([], self.state["dispatches"])
        self.route("/pulls/23/requested_reviewers")["users"] = []
        result = self.execute(script, {})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(self.state["dispatches"]))
        self.assertEqual(0, self.consumer().returncode)
        self.assertEqual(0, self.execute(script, {}).returncode)
        self.assertEqual(1, len(self.state["requests"]))
        self.assertEqual(1, len(self.state["dispatches"]))

    def test_terminal_old_review_in_body_or_comment_never_continues(self):
        for marker in (
            "Quota exceeded",
            "premium\nrequest quota",
            "Encountered an error",
            "was not able to review any files",
            "suppressed comments",
        ):
            for comment in (False, True):
                with self.subTest(marker=marker, comment=comment):
                    self.setUp()
                    self.assertEqual(0, self.defer().returncode)
                    if comment:
                        self.route("/pulls/23/reviews/17/comments").append({"id": 18, "body": marker})
                    else:
                        self.route("/pulls/23/reviews/17")["body"] = marker
                    self.assertNotEqual(0, self.locator().returncode)
                    self.assertNotEqual(0, self.consumer().returncode)
                    self.assertEqual([], self.state["requests"])

    def test_real_consumer_preserves_contractions_singular_marker_and_content_shapes(self):
        self.assertEqual(0, self.defer().returncode)
        baseline = copy.deepcopy(self.state)
        markers = (
            "Copilot was not able to review this pull request.",
            "Copilot wasn't able to review this pull request.",
            "Copilot wasn’t able to review this pull request.",
            "suppressed comment",
            "COPILOT\u00a0WASN’T\u2003ABLE\tTO REVIEW THIS PULL REQUEST",
        )
        for marker in markers:
            for inline in (False, True):
                with self.subTest(marker=marker, inline=inline):
                    self.state = copy.deepcopy(baseline)
                    if inline:
                        self.route("/pulls/23/reviews/17/comments").append({"id": 18, "body": marker})
                    else:
                        self.route("/pulls/23/reviews/17")["body"] = marker
                    result = self.consumer()
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual([], self.state["requests"])
                    self.assertNotIn(REQUEST, self.state["versions"][self.state["oid"]])
        for body, comments in (({}, []), (None, []), ("\u2003", []), ("Reviewed.", [None]), ("Reviewed.", [False])):
            with self.subTest(body=body, comments=comments):
                self.state = copy.deepcopy(baseline)
                self.route("/pulls/23/reviews/17")["body"] = body
                self.route("/pulls/23/reviews/17/comments").extend(
                    {"id": 18 + index, "body": value} for index, value in enumerate(comments)
                )
                self.assertNotEqual(0, self.consumer().returncode)
                self.assertEqual([], self.state["requests"])
        self.state = copy.deepcopy(baseline)
        result = self.consumer()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(self.state["requests"]))

    def test_writer_and_readonly_content_contract_match_canonical_policy(self):
        import ast

        names = {"FAILURE_MARKERS", "ReviewContentError", "normalize", "require_usable_review_content"}

        def definitions(path):
            result = {}
            for node in ast.parse(path.read_text()).body:
                name = (
                    node.targets[0].id
                    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    else getattr(node, "name", None)
                )
                if name in names:
                    result[name] = ast.dump(node, include_attributes=False)
            self.assertEqual(names, set(result))
            return result

        writer = definitions(ROOT / "scripts/review_request_continuation.py")
        self.assertEqual(writer, definitions(ROOT / "scripts/review_request_provenance.py"))
        canonical = ROOT / "scripts/review_content_markers.py"
        if canonical.exists():
            self.assertEqual(writer, definitions(canonical))

    def test_unknown_cas_and_post_and_existing_schema1_never_repeat(self):
        for mode in ("lose_cas", "lost_cas_response", "lost_post_response", "schema1"):
            with self.subTest(mode=mode):
                self.setUp()
                self.assertEqual(0, self.defer().returncode)
                if mode == "schema1":
                    self.state["versions"][self.state["oid"]][REQUEST] = {"schema": 1}
                else:
                    self.state[mode] = True
                self.assertNotEqual(0, self.consumer().returncode)
                self.consumer(GITHUB_RUN_ID="89")
                self.assertEqual(1 if mode == "lost_post_response" else 0, len(self.state["requests"]))

    def test_ref_drift_after_cas_consumes_budget_without_requesting_stale_head(self):
        self.assertEqual(0, self.defer().returncode)
        self.state["drift_after_cas"] = True
        self.assertNotEqual(0, self.consumer().returncode)
        self.assertIn(REQUEST, self.state["versions"][self.state["oid"]])
        self.assertEqual([], self.state["requests"])

    def test_concurrent_consumer_with_stale_complete_snapshot_loses_same_cas(self):
        self.assertEqual(0, self.defer().returncode)
        before = self.state["oid"]
        self.assertEqual(0, self.consumer().returncode)
        self.state["stale_ref"] = before
        self.route("/pulls/23/requested_reviewers")["users"] = []
        result = self.consumer(GITHUB_RUN_ID="89")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(1, len(self.state["requests"]))
        attempted = [
            call
            for call in self.state["calls"]
            if call["route"] == "graphql"
            and call["payload"]
            and call["payload"]["variables"]["input"]["fileChanges"]["additions"][0]["path"] == REQUEST
        ]
        self.assertEqual(2, len(attempted))

    def test_existing_reconciler_reads_resume_family_and_applies_native_cooldown(self):
        self.assertEqual(0, self.defer().returncode)
        self.state["history"] = [
            {
                "id": 99,
                "event": "workflow_dispatch",
                "path": ".github/workflows/review-request-continuation.yml",
                "display_title": f"First review PR #23 head {HEAD} owner 77 old review 17",
                "status": "queued",
                "created_at": self.at(-900),
                "updated_at": self.at(-1),
            }
        ]
        script = "python3 " + str(ROOT / "scripts/review-event-reconcile.py")
        self.assertEqual(0, self.execute(script, {}).returncode)
        self.assertEqual([], self.state["dispatches"])
        self.state["history"][0]["status"] = "completed"
        self.assertEqual(0, self.execute(script, {}).returncode)
        self.assertEqual([], self.state["dispatches"])
        self.state["history"][0]["updated_at"] = self.at(-700)
        result = self.execute(script, {})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(self.state["dispatches"]))

    def test_consumer_actor_attempt_and_source_are_not_subject_head_authority(self):
        self.assertEqual(0, self.defer().returncode)
        for changes in (
            {"GITHUB_ACTOR": "litroc"},
            {"GITHUB_TRIGGERING_ACTOR": "litroc"},
            {"GITHUB_RUN_ATTEMPT": "2"},
            {"GITHUB_REF_PROTECTED": "false"},
            {"WORKFLOW_SHA": HEAD},
            {"LI219_EVENT_MODE": "disabled"},
            {"GITHUB_REF": "refs/heads/fix/new"},
        ):
            with self.subTest(changes=changes):
                self.assertNotEqual(0, self.consumer(**changes).returncode)
                self.assertNotIn(REQUEST, self.state["versions"][self.state["oid"]])
        self.assertEqual([], self.state["requests"])

    def test_authority_and_native_drift_block_before_request_cas(self):
        mutations = {
            "owner actor": lambda: self.route("/actions/runs/77/attempts/1")["actor"].update(login="mallory"),
            "owner event": lambda: self.route("/actions/runs/77/attempts/1").update(event="workflow_dispatch"),
            "new head": lambda: self.route("/pulls/23")["head"].update(sha="f" * 40),
            "base drift": lambda: self.route("/pulls/23")["base"].update(sha="f" * 40),
            "fork": lambda: self.route("/pulls/23")["head"]["repo"].update(full_name="other/repo"),
            "draft": lambda: self.route("/pulls/23").update(draft=True),
            "spent attempt": lambda: self.route("/actions/runs/77").update(run_attempt=2),
            "current head review": lambda: self.route("/pulls/23/reviews").append(
                {**self.route("/pulls/23/reviews/17"), "id": 19, "commit_id": HEAD}
            ),
            "pending": lambda: self.route("/pulls/23/requested_reviewers")["users"].append({"login": BOT}),
            "source": lambda: self.state.update(ancestry={"status": "diverged"}),
            "unsuccessful step": lambda: self.route("/actions/runs/77/attempts/1/jobs")["jobs"][0]["steps"][2].update(
                conclusion="failure"
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.setUp()
                self.assertEqual(0, self.defer().returncode)
                mutate()
                self.assertNotEqual(0, self.consumer().returncode)
                self.assertEqual([], self.state["requests"])
                self.assertNotIn(REQUEST, self.state["versions"][self.state["oid"]])

    def test_embedded_helpers_match_canonical_source_and_narrow_job_guards(self):
        import textwrap

        helper = (ROOT / "scripts/review_request_continuation.py").read_text().strip()
        for path in (".github/workflows/copilot-review.yml", ".github/workflows/review-request-continuation.yml"):
            text = (ROOT / path).read_text()
            chunks = text.split("<<'CONTINUATION'\n")[1:]
            self.assertTrue(chunks)
            for chunk in chunks:
                self.assertEqual(helper, textwrap.dedent(chunk.split("\n          CONTINUATION", 1)[0]).strip())
        job = self.workflow["jobs"]["resume"]
        for guard in (
            "github.ref_protected",
            "github.ref == 'refs/heads/develop'",
            "github.actor == 'github-actions[bot]'",
            "github.triggering_actor == 'github-actions[bot]'",
            "github.run_attempt == 1",
            "vars.LI219_EVENT_MODE == 'enabled'",
        ):
            self.assertIn(guard, job["if"])
        self.assertEqual("read", self.workflow["jobs"]["locate"]["permissions"]["contents"])
        self.assertEqual("read", self.workflow["jobs"]["locate"]["permissions"]["pull-requests"])
        self.assertNotIn("concurrency", self.workflow)  # CAS is global across all request writers.

    def test_readonly_provenance_accepts_local_owner_and_binds_native_resume_steps(self):
        result = self.defer()
        self.assertEqual(0, result.returncode, result.stderr)
        result = self.consumer()
        self.assertEqual(0, result.returncode, result.stderr)
        receipt = self.state["versions"][self.state["oid"]][REQUEST]
        original = self.route("/actions/runs/77")
        start = dt.datetime.strptime(original["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.UTC)

        def at(seconds):
            return (start + dt.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

        run = self.route("/actions/runs/88/attempts/1")
        run.update(status="completed", conclusion="success", created_at=at(0), updated_at=at(8))
        names = [
            "Set up job",
            "Materialize protected first-request continuation",
            "Resume the deferred first request",
            "Complete job",
        ]
        steps = [
            {
                "name": name,
                "number": index + 1,
                "status": "completed",
                "conclusion": "success",
                "started_at": at(index + 1),
                "completed_at": at(index + 2),
            }
            for index, name in enumerate(names)
        ]
        job = {
            "id": 180,
            "run_id": 88,
            "run_attempt": 1,
            "head_sha": SOURCE,
            "name": "Resume deferred first review request",
            "status": "completed",
            "conclusion": "success",
            "runner_id": 4,
            "started_at": at(1),
            "completed_at": at(6),
            "steps": steps,
        }
        locator = {
            "id": 181,
            "run_id": 88,
            "run_attempt": 1,
            "head_sha": SOURCE,
            "name": "Locate deferred first review request",
            "status": "completed",
            "conclusion": "skipped",
            "runner_id": None,
            "steps": [],
        }
        self.state["routes"]["repos/" + REPO + "/actions/runs/88/attempts/1/jobs"] = {
            "total_count": 2,
            "jobs": [job, locator],
        }
        context = {
            "repository": REPO,
            "repository_id": RID,
            "owner": 23,
            "head": HEAD,
            "base": BASE,
            "base_ref": "develop",
            "run_id": 77,
            "controller": SOURCE,
            "review_submitted_at": at(9),
            "timeline": [
                [
                    {
                        "id": 700,
                        "event": "review_requested",
                        "requested_reviewer": {"login": "Copilot"},
                        "actor": {"login": "github-actions[bot]", "type": "Bot"},
                        "created_at": at(3),
                    }
                ]
            ],
        }
        check = self.root / "verify_provenance.py"
        check.write_text(
            "import importlib.util, json, os\n"
            + "spec = importlib.util.spec_from_file_location('provenance', "
            + repr(str(ROOT / "scripts/review_request_provenance.py"))
            + ")\n"
            + "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n"
            + "module.verify_receipt(json.loads(os.environ['CONTEXT']), json.loads(os.environ['RECEIPT']))\n"
        )
        before = (len(self.state["requests"]), len(self.state["dispatches"]), self.state["oid"])
        result = self.execute(
            "python3 " + str(check), {}, {"CONTEXT": json.dumps(context), "RECEIPT": json.dumps(receipt)}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        baseline = copy.deepcopy(self.state)
        for case in ("step", "source", "timeline", "locator"):
            with self.subTest(case=case):
                self.state = copy.deepcopy(baseline)
                invalid = copy.deepcopy(context)
                if case == "step":
                    self.route("/actions/runs/88/attempts/1/jobs")["jobs"][0]["steps"][2]["name"] = "Wrong request step"
                elif case == "source":
                    self.route("/actions/runs/88/attempts/1")["head_sha"] = HEAD
                elif case == "timeline":
                    invalid["timeline"][0][0]["created_at"] = at(7)
                else:
                    self.route("/actions/runs/88/attempts/1/jobs")["jobs"][1]["runner_id"] = 9
                result = self.execute(
                    "python3 " + str(check), {}, {"CONTEXT": json.dumps(invalid), "RECEIPT": json.dumps(receipt)}
                )
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(
                    before, (len(self.state["requests"]), len(self.state["dispatches"]), self.state["oid"])
                )
