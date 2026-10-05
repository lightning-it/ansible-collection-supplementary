import datetime as dt
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("review_event", ROOT / "scripts/review-event-reconcile.py")
EVENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVENT)


class ReviewEventTests(unittest.TestCase):
    head, base = "b" * 40, "a" * 40
    now = dt.datetime(2026, 10, 5, 18, tzinfo=dt.UTC)

    def review(self, **changes):
        return {
            "id": 17,
            "commit_id": self.head,
            "body": "Review complete.",
            "user": {"login": "copilot-pull-request-reviewer[bot]"},
            "state": "COMMENTED",
            **changes,
        }

    def test_review_content_rejects_stale_empty_quota_and_foreign(self):
        self.assertTrue(EVENT.clean_review(self.review(), [], self.head))
        for review in (
            self.review(commit_id=self.base),
            self.review(body=" "),
            self.review(body="Quota\nexceeded"),
            self.review(state="DISMISSED"),
            self.review(user={"login": "litroc"}),
        ):
            self.assertFalse(EVENT.clean_review(review, [], self.head))
        self.assertFalse(EVENT.clean_review(self.review(), [{"body": "Suppressed comments"}], self.head))
        self.assertTrue(EVENT.clean_review(self.review(body=""), [{"body": "Reviewed files"}], self.head))

    def reconcile(
        self, *, delay=180, missing=False, state="completed", drift=False, uncertain=False, body="Review complete."
    ):
        prefix = "repos/lightning-it/ansible-collection-supplementary"
        pr = {
            "id": 23,
            "number": 23,
            "draft": False,
            "state": "open",
            "user": {"login": "litroc", "type": "User"},
            "head": {
                "sha": self.head,
                "ref": "fix/final",
                "repo": {"full_name": "lightning-it/ansible-collection-supplementary"},
            },
            "base": {"sha": self.base, "ref": "develop"},
        }
        run = {
            "id": 77,
            "path": EVENT.PRODUCER,
            "head_sha": self.head,
            "head_branch": "fix/final",
            "pull_requests": [{"number": 23}],
            "status": state,
            "created_at": (self.now - dt.timedelta(seconds=delay)).isoformat(),
        }
        inventories = {
            f"{prefix}/pulls?state=open": [pr],
            f"{prefix}/actions/runs?event=pull_request_target&head_sha={self.head}": [run],
            f"{prefix}/commits/{self.head}/check-runs?filter=all": [],
            f"{prefix}/pulls/23/reviews": [] if missing else [self.review(body=body)],
            f"{prefix}/pulls/23/reviews/17/comments": [],
        }
        mutations = []

        def api(route, payload=None):
            if payload is not None:
                mutations.append((route, payload))
                if uncertain:
                    raise TimeoutError("response lost after server accepted dispatch")
                return None
            if route == prefix:
                return {"default_branch": "develop"}
            if route == f"{prefix}/pulls/23":
                return {**pr, "head": {**pr["head"], "sha": self.base}} if drift else pr
            raise AssertionError(route)

        with (
            patch.object(EVENT, "api", side_effect=api),
            patch.object(
                EVENT,
                "pages",
                side_effect=lambda route, key=None: [] if "/actions/workflows/" in route else inventories[route],
            ),
            patch.dict(
                os.environ, LI219_EVENT_MODE="enabled", GITHUB_REF="refs/heads/develop", GITHUB_REF_PROTECTED="true"
            ),
        ):
            if uncertain:
                with self.assertRaises(TimeoutError):
                    EVENT.reconcile("lightning-it/ansible-collection-supplementary", self.now)
            else:
                EVENT.reconcile("lightning-it/ansible-collection-supplementary", self.now)
        return mutations

    def test_late_review_after_ten_minutes_dispatches_same_pr_without_review_request(self):
        for delay in (180, 601, 3600):
            calls = self.reconcile(delay=delay)
            self.assertEqual(1, len(calls))
            self.assertTrue(calls[0][0].endswith("copilot-review-refresh.yml/dispatches"))
            self.assertEqual("23", calls[0][1]["inputs"]["pr_number"])
            self.assertEqual(self.head, calls[0][1]["inputs"]["expected_head"])

    def test_missing_event_expiry_early_producer_and_stale_head_never_dispatch(self):
        for args in ({"missing": True}, {"delay": 7 * 86400 + 1}, {"state": "in_progress"}, {"drift": True}):
            self.assertEqual([], self.reconcile(**args))

    def test_every_terminal_marker_blocks_dispatch_then_valid_review_can_resume(self):
        for marker in EVENT.MARKERS:
            with self.subTest(marker=marker):
                self.assertEqual([], self.reconcile(body=marker))
                self.assertFalse(EVENT.clean_review(self.review(), [{"body": marker}], self.head))
                self.assertEqual(1, len(self.reconcile()))

    def test_ambiguous_dispatch_response_is_not_retried(self):
        self.assertEqual(1, len(self.reconcile(uncertain=True)))

    def test_active_dispatch_is_deduplicated(self):
        run = {
            "path": ".github/workflows/copilot-review-refresh.yml",
            "event": "workflow_dispatch",
            "display_title": "bound",
            "status": "queued",
        }
        self.assertTrue(EVENT.recent_dispatch([run], EVENT.REFRESH, "bound"))
        self.assertFalse(EVENT.recent_dispatch([run], EVENT.REFRESH, "foreign"))

    def test_all_rerun_writers_share_the_exact_head_lane(self):
        helper = (ROOT / ".github/workflows/current-revision-rerun.yml").read_text()
        self.assertIn(
            "format('current-revision-{0}-head-{1}-check-current-revision-review', "
            "github.repository_id, inputs.expected_head)",
            helper,
        )
        self.assertIn("cancel-in-progress: false", helper)
