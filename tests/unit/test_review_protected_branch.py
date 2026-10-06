"""Real embedded locator/consumer regressions for protected develop and main."""

import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from unit import test_review_request_continuation as continuation

ROOT = Path(__file__).resolve().parents[2]


class ProtectedReviewBranchTests(unittest.TestCase):
    def fixture(self, branch):
        fixture = continuation.ContinuationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.route("/pulls/23")["base"]["ref"] = branch
        for route in ("/actions/runs/77", "/actions/runs/77/attempts/1"):
            fixture.route(route)["pull_requests"][0]["base"]["ref"] = branch
        fixture.state["routes"]["repos/" + continuation.REPO + "/branches/" + branch] = {
            "name": branch,
            "protected": True,
            "commit": {"sha": continuation.BASE},
        }
        for run in ("88", "89"):
            fixture.route("/actions/runs/" + run + "/attempts/1")["head_branch"] = branch
        # PRT executes default develop D; dispatch resumes on PR base M.
        original = "c" * 40 if branch == "main" else continuation.BASE
        fixture.env.update(WORKFLOW_SHA=original, GITHUB_SHA=original)
        fixture.route("/branches/develop")["commit"]["sha"] = original
        fixture.resume_changes = {
            "WORKFLOW_SHA": continuation.BASE,
            "GITHUB_SHA": continuation.BASE,
            "GITHUB_REF": "refs/heads/" + branch,
            "GITHUB_WORKFLOW_REF": continuation.REPO
            + "/.github/workflows/review-request-continuation.yml@refs/heads/"
            + branch,
        }
        return fixture

    def test_develop_and_main_locator_and_consumer_share_exact_protected_ref(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                f = self.fixture(branch)
                result = f.defer()
                self.assertEqual(0, result.returncode, result.stderr)
                for companion in (False, True):
                    result = f.locator(companion)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual(branch, f.state["dispatches"][-1]["ref"])
                result = f.consumer()
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(1, len(f.state["requests"]))
                self.assertNotEqual(0, f.consumer().returncode)
                self.assertEqual(1, len(f.state["requests"]))

    def test_main_intent_rejects_develop_consumer_before_request_CAS(self):
        f = self.fixture("main")
        self.assertEqual(0, f.defer().returncode)
        before = copy.deepcopy(f.state["versions"])
        result = f.consumer(GITHUB_REF="refs/heads/develop")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, f.state["versions"])
        self.assertEqual([], f.state["requests"])

    def test_reconciler_main_continuation_uses_live_base_ref(self):
        f = self.fixture("main")
        self.assertEqual(0, f.defer().returncode)
        result = f.execute(
            "python3 " + str(ROOT / "scripts/review-event-reconcile.py"), {}, {"GITHUB_REF": "refs/heads/develop"}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["main"], [v["ref"] for v in f.state["dispatches"]])

    def refresh(
        self,
        branch,
        consumer=False,
        execution_branch=None,
        controller=None,
        final_fence=False,
        live_head=None,
        head_repository=None,
        actual_head_repository=None,
        trigger_actor="github-actions[bot]",
        author_type="User",
    ):
        workflow = yaml.safe_load((ROOT / ".github/workflows/copilot-review-refresh.yml").read_text())
        if final_fence:
            body = workflow["jobs"]["refresh-canonical-gate"]["steps"][1]["run"]
            start = body.index("validate_live_pr_tuple() {")
            end = body.index("\n}\nvalidate_live_pr_tuple", start) + 2
            text = 'oa() { gh api "$@"; }\n' + body[start:end] + "\nvalidate_live_pr_tuple"
        elif consumer:
            text = workflow["jobs"]["refresh-canonical-gate"]["steps"][1]["run"]
            text = text[: text.index("\njq -e \\\n  --arg actor")]
        else:
            text = workflow["jobs"]["forward-review-event"]["steps"][0]["run"]
        pr = {
            "number": 23,
            "state": "open",
            "draft": False,
            "user": {"login": "litroc", "type": author_type},
            "head": {
                "sha": continuation.HEAD,
                "ref": "fix/new",
                "repo": {"full_name": actual_head_repository or head_repository or continuation.REPO},
            },
            "base": {"sha": continuation.BASE, "ref": branch, "repo": {"full_name": continuation.REPO}},
        }
        review = {"id": 17, "commit_id": continuation.HEAD, "user": {"login": continuation.BOT}, "state": "COMMENTED"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pr").write_text(json.dumps(pr))
            (root / "review").write_text(json.dumps(review))
            mock = root / "gh"
            mock.write_text(
                """#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
r=Path(os.environ['FIXTURE']);args=sys.argv[1:]
if 'POST' in args:
    with (r/'dispatches').open('a') as f:f.write(json.dumps(args)+'\\n')
elif any('/reviews?per_page' in a for a in args):print('['+ '['+(r/'review').read_text()+']'+']')
elif any('/reviews/' in a for a in args):print((r/'review').read_text())
elif any('/pulls/' in a for a in args):print((r/'pr').read_text())
elif any('/branches/' in a for a in args):
    p=json.loads((r/'pr').read_text())
    source=os.environ.get('LIVE_BRANCH_HEAD') or p['base']['sha']
    print(json.dumps({'name':p['base']['ref'],'protected':True,'commit':{'sha':source}}))
elif '--jq' in args:print('develop')
else:raise SystemExit('unexpected fixture route '+repr(args))
"""
            )
            mock.chmod(0o755)
            result = subprocess.run(  # noqa: S603 -- Actual workflow shell with offline mock transport.
                ["/bin/bash", "-euo", "pipefail", "-c", text],
                env={
                    **os.environ,
                    "PATH": str(root) + ":" + os.environ["PATH"],
                    "FIXTURE": str(root),
                    "RUNNER_TEMP": str(root),
                    "REPOSITORY": continuation.REPO,
                    "HEAD_REPOSITORY": head_repository or continuation.REPO,
                    "PR_NUMBER": "23",
                    "PR_AUTHOR": "litroc",
                    "BASE_REF": branch,
                    "BASE_SHA": continuation.BASE,
                    "HEAD_REF": "fix/new",
                    "HEAD_SHA": continuation.HEAD,
                    "LIVE_BRANCH_HEAD": live_head or continuation.BASE,
                    "EXPECTED_HEAD": continuation.HEAD,
                    "EXPECTED_BASE": continuation.BASE,
                    "LOCATOR_PR": "23",
                    "LOCATOR_HEAD": continuation.HEAD,
                    "LOCATOR_BASE": continuation.BASE,
                    "LOCATOR_REVIEW": "17",
                    "EVENT_NAME": "workflow_dispatch",
                    "TRIGGER_ACTOR": trigger_actor,
                    "GITHUB_REF": "refs/heads/" + (execution_branch or branch),
                    "GITHUB_REF_PROTECTED": "true",
                    "WORKFLOW_SHA": controller or continuation.BASE,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            dispatches = (
                [json.loads(line) for line in (root / "dispatches").read_text().splitlines()]
                if (root / "dispatches").exists()
                else []
            )
        return result, dispatches

    def test_refresh_locator_dispatches_authenticated_base_instead_of_default(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                result, dispatched = self.refresh(branch)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(1, len(dispatched))
                self.assertIn("ref=" + branch, dispatched[0])

    def test_refresh_consumer_accepts_matching_ref_and_rejects_cross_ref(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                result, unused_dispatches = self.refresh(branch, consumer=True)
                self.assertEqual(0, result.returncode, result.stderr)
                result, unused_dispatches = self.refresh(
                    branch, consumer=True, execution_branch="main" if branch == "develop" else "develop"
                )
                self.assertNotEqual(0, result.returncode)

    def test_consumers_reject_wrong_controller_before_any_request_claim(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                fixture = self.fixture(branch)
                self.assertEqual(0, fixture.defer().returncode)
                before = copy.deepcopy(fixture.state["versions"])
                result = fixture.consumer(WORKFLOW_SHA="d" * 40)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual(before, fixture.state["versions"])
                self.assertEqual([], fixture.state["requests"])
                result, dispatches = self.refresh(branch, consumer=True, controller="d" * 40)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], dispatches)

    def test_readonly_receipt_binds_main_intent_and_native_execution_branch(self):
        fixture = self.fixture("main")
        receipt, context, check = fixture.prepare_readonly_provenance()
        context["base_ref"] = "main"
        environment = {"CONTEXT": json.dumps(context), "RECEIPT": json.dumps(receipt)}
        result = fixture.execute("python3 " + str(check), {}, environment)
        self.assertEqual(0, result.returncode, result.stderr)
        before = copy.deepcopy(fixture.state)
        fixture.route("/actions/runs/88/attempts/1")["head_branch"] = "develop"
        result = fixture.execute("python3 " + str(check), {}, environment)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before["versions"], fixture.state["versions"])
        self.assertEqual(before["requests"], fixture.state["requests"])

    def test_protected_controller_drift_before_claim_preserves_budget(self):
        f = self.fixture("main")
        self.assertEqual(0, f.defer().returncode)
        before = copy.deepcopy(f.state["versions"])
        f.route("/branches/main")["commit"]["sha"] = "d" * 40
        result = f.consumer()
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, f.state["versions"])
        self.assertEqual([], f.state["requests"])

    def test_live_branch_race_at_final_claim_and_effect_fences(self):
        for branch in ("develop", "main"):
            for mode in ("controller_drift_before_claim", "controller_drift_after_cas"):
                with self.subTest(branch=branch, mode=mode):
                    f = self.fixture(branch)
                    self.assertEqual(0, f.defer().returncode)
                    before = copy.deepcopy(f.state["versions"])
                    f.state[mode] = True
                    result = f.consumer()
                    self.assertNotEqual(0, result.returncode)
                    self.assertEqual([], f.state["requests"])
                    if mode == "controller_drift_before_claim":
                        self.assertEqual(before, f.state["versions"])
                    else:
                        self.assertIn(continuation.REQUEST, f.state["versions"][f.state["oid"]])
                        self.assertNotEqual(0, f.consumer().returncode)
                        self.assertEqual([], f.state["requests"])

    def test_refresh_final_fence_rechecks_live_protected_controller(self):
        for branch in ("develop", "main"):
            with self.subTest(branch=branch):
                result, effects = self.refresh(branch, final_fence=True)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual([], effects)
                result, effects = self.refresh(branch, final_fence=True, live_head="d" * 40)
                self.assertNotEqual(0, result.returncode)
                self.assertEqual([], effects)
