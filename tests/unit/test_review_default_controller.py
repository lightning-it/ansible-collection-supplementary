"""Real default-controller D to Main-controller M request and receipt paths."""

import copy
import json
import unittest
from pathlib import Path

from unit import test_review_protected_branch as branches
from unit import test_review_request_continuation as c

ROOT = Path(__file__).resolve().parents[2]


class DefaultControllerTests(unittest.TestCase):
    def fixture(self, branch="main"):
        harness = branches.ProtectedReviewBranchTests()
        fixture = harness.fixture(branch)
        self.addCleanup(harness.doCleanups)
        return fixture

    def test_full_main_defer_locator_resume_and_readonly_receipt_preserve_distinct_sources(self):
        self.full_main_receipt(2)

    def test_active_schema1_main_resumes_and_verifies_both_receipts_from_main(self):
        self.full_main_receipt(1)

    def test_historical_schema1_main_receipts_accept_later_develop_resume_source(self):
        self.full_main_receipt(1, historical=True)

    def test_schema2_main_receipts_reject_historical_develop_resume_source(self):
        self.full_main_receipt(2, historical=True)

    def full_main_receipt(self, schema, historical=False):
        f = self.fixture()
        self.assertEqual("refs/heads/main", f.env["GITHUB_REF"])
        self.assertEqual(c.BASE, f.env["GITHUB_SHA"])
        self.assertNotEqual(f.env["WORKFLOW_SHA"], f.env["GITHUB_SHA"])
        self.assertEqual(0, f.defer().returncode)
        intent = f.state["versions"][f.state["oid"]][c.INTENT]
        self.assertEqual(
            (2, "develop", "c" * 40, c.BASE, "main"),
            (intent["schema"], intent["source_ref"], intent["source_sha"], intent["base"], intent["base_ref"]),
        )
        if schema == 1:
            intent["schema"] = 1
            del intent["source_ref"]
        self.assertEqual(0, f.locator().returncode)
        self.assertEqual("main", f.state["dispatches"][-1]["ref"])
        result = f.consumer()
        self.assertEqual(0, result.returncode, result.stderr)
        record = f.state["versions"][f.state["oid"]][c.REQUEST]
        resume_sha = "e" * 40 if historical else c.BASE
        if historical:
            record = copy.deepcopy(record)
            record["source_sha"] = resume_sha
            f.route("/branches/develop")["commit"]["sha"] = resume_sha
            f.state["ancestries"] = {
                f"repos/{c.REPO}/compare/{intent['source_sha']}...{resume_sha}": {
                    "status": "ahead",
                    "behind_by": 0,
                    "merge_base_commit": {"sha": intent["source_sha"]},
                }
            }
        self.assertEqual(resume_sha, record["source_sha"])
        self.assertEqual(intent, record["intent"])
        run = f.route("/actions/runs/88/attempts/1")
        run.update(
            status="completed",
            conclusion="success",
            created_at=f.at(3),
            updated_at=f.at(9),
            head_sha=resume_sha,
            head_branch="develop" if historical else "main",
        )
        names = [
            "Set up job",
            "Materialize protected first-request continuation",
            "Resume the deferred first request",
            "Complete job",
        ]
        steps = [
            {
                "name": name,
                "number": i + 1,
                "status": "completed",
                "conclusion": "success",
                "started_at": f.at(3 + i),
                "completed_at": f.at(4 + i),
            }
            for i, name in enumerate(names)
        ]
        common = {"run_id": 88, "run_attempt": 1, "head_sha": resume_sha, "status": "completed"}
        f.state["routes"]["repos/" + c.REPO + "/actions/runs/88/attempts/1/jobs"] = {
            "total_count": 2,
            "jobs": [
                dict(
                    common,
                    id=90,
                    name="Resume deferred first review request",
                    conclusion="success",
                    runner_id=4,
                    started_at=f.at(3),
                    completed_at=f.at(7),
                    steps=steps,
                ),
                dict(
                    common,
                    id=91,
                    name="Locate deferred first review request",
                    conclusion="skipped",
                    runner_id=None,
                    steps=[],
                ),
            ],
        }
        context = {
            "repository": c.REPO,
            "repository_id": c.RID,
            "owner": 23,
            "run_id": 77,
            "base": c.BASE,
            "head": c.HEAD,
            "base_ref": "main",
            "controller": "c" * 40,
            "review_submitted_at": f.at(10),
            "timeline": [
                [
                    {
                        "id": 92,
                        "event": "review_requested",
                        "requested_reviewer": {"login": "Copilot"},
                        "created_at": f.at(5),
                        "actor": {"login": "github-actions[bot]", "type": "Bot"},
                    }
                ]
            ],
        }
        for helper in ("review_request_continuation", "review_request_provenance"):
            script = (
                f"import sys,json;sys.path.insert(0,{str(ROOT / 'scripts')!r});"
                f"import {helper} as m;m.verify_receipt({context!r},{record!r})"
            )
            result = f.execute("python3 - <<'VERIFY'\n" + script + "\nVERIFY", {})
            if historical and schema == 2:
                self.assertNotEqual(0, result.returncode)
            else:
                self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(1, len(f.state["requests"]))
        bad = copy.deepcopy(record)
        bad["source_sha"] = intent["source_sha"]
        result = f.execute("python3 - <<'VERIFY'\n" + script.replace(repr(record), repr(bad)) + "\nVERIFY", {})
        self.assertNotEqual(0, result.returncode)

    def test_wrong_default_execution_and_live_default_or_base_drift_cannot_create_intent(self):
        for mutation in (
            "base_ref",
            "base_sha",
            "workflow_ref",
            "workflow_sha",
            "default_drift_before_intent",
            "base_drift_before_intent",
        ):
            with self.subTest(mutation=mutation):
                f = self.fixture()
                if mutation == "base_ref":
                    f.env["GITHUB_REF"] = "refs/heads/develop"
                elif mutation == "base_sha":
                    f.env["GITHUB_SHA"] = f.env["WORKFLOW_SHA"]
                elif mutation == "workflow_ref":
                    f.env["GITHUB_WORKFLOW_REF"] = c.REPO + "/.github/workflows/copilot-review.yml@refs/heads/main"
                elif mutation == "workflow_sha":
                    f.env["WORKFLOW_SHA"] = c.BASE
                else:
                    f.state[mutation] = True
                before = copy.deepcopy(f.state["versions"])
                self.assertNotEqual(0, f.defer().returncode)
                self.assertEqual(before, f.state["versions"])
                self.assertEqual([], f.state["requests"])

    def test_main_unknown_claim_or_post_never_replays(self):
        for mode in ("lost_cas_response", "lost_post_response"):
            with self.subTest(mode=mode):
                f = self.fixture()
                self.assertEqual(0, f.defer().returncode)
                f.state[mode] = True
                self.assertNotEqual(0, f.consumer().returncode)
                count = len(f.state["requests"])
                self.assertEqual(0 if mode == "lost_cas_response" else 1, count)
                self.assertNotEqual(0, f.consumer().returncode)
                self.assertEqual(count, len(f.state["requests"]))

    def test_legacy_intent_is_not_reinterpreted_as_main_controller(self):
        for branch in ("develop", "main"):
            f = self.fixture(branch)
            self.assertEqual(0, f.defer().returncode)
            intent = f.state["versions"][f.state["oid"]][c.INTENT]
            intent["schema"] = 1
            del intent["source_ref"]
            result = f.locator()
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(branch, f.state["dispatches"][-1]["ref"])

    def test_post_intent_default_and_main_drift_fail_even_with_lost_response(self):
        for branch in ("develop", "main"):
            for lost in (False, True):
                with self.subTest(branch=branch, lost=lost):
                    f = self.fixture()
                    f.state.update(intent_drift_after_cas=branch, lost_cas_response=lost)
                    self.assertNotEqual(0, f.defer().returncode)
                    self.assertIn(c.INTENT, f.state["versions"][f.state["oid"]])
                    self.assertEqual([], f.state["requests"])

    def test_actual_scheduled_candidate_retains_legacy_or_typed_resume_ref_without_effects(self):
        for schema, ref in ((1, "main"), (2, "main")):
            with self.subTest(schema=schema):
                f = self.fixture()
                self.assertEqual(0, f.defer().returncode)
                intent = f.state["versions"][f.state["oid"]][c.INTENT]
                if schema == 1:
                    intent["schema"] = 1
                    del intent["source_ref"]
                code = (
                    f"import sys,json,datetime;sys.path.insert(0,{str(ROOT / 'scripts')!r});"
                    f"import review_request_continuation as m;"
                    f"print(json.dumps(m.reconcile_candidate({c.REPO!r},{c.RID!r},23,{c.HEAD!r},datetime.datetime.now(datetime.timezone.utc))))"
                )
                result = f.execute("python3 - <<'VERIFY'\n" + code + "\nVERIFY", {})
                self.assertEqual(0, result.returncode, result.stderr)
                candidate = json.loads(result.stdout)
                self.assertEqual(ref, candidate.pop("resume_ref"))
                self.assertEqual({"pr_number", "owner_run", "expected_head", "old_review"}, set(candidate))
                self.assertEqual([], f.state["requests"])
                self.assertEqual([], f.state["dispatches"])

    def test_active_schema1_main_cannot_request_from_develop_controller(self):
        f = self.fixture()
        self.assertEqual(0, f.defer().returncode)
        intent = f.state["versions"][f.state["oid"]][c.INTENT]
        intent["schema"] = 1
        del intent["source_ref"]
        before = copy.deepcopy(f.state["versions"])
        result = f.consumer(
            WORKFLOW_SHA=intent["source_sha"],
            GITHUB_SHA=intent["source_sha"],
            GITHUB_REF="refs/heads/develop",
            GITHUB_WORKFLOW_REF=c.REPO + "/.github/workflows/review-request-continuation.yml@refs/heads/develop",
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, f.state["versions"])
        self.assertEqual([], f.state["requests"])
