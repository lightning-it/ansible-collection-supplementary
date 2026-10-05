import datetime as dt
import importlib.util
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

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
        self,
        *,
        delay=180,
        missing=False,
        state="completed",
        drift=False,
        uncertain=False,
        body="Review complete.",
        history=(),
        pr_count=1,
        transform=None,
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
            "pull_requests": [{"number": 23 + i} for i in range(pr_count)],
            "status": state,
            "created_at": (self.now - dt.timedelta(seconds=delay)).isoformat(),
        }
        inventories = {
            f"{prefix}/pulls?state=open": [{**pr, "id": 23 + i, "number": 23 + i} for i in range(pr_count)],
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
            if "/actions/workflows/" in route:
                response = self.inventory_response(history, route)
                return transform(route, response) if transform else response
            if route == prefix:
                return {"default_branch": "develop"}
            if route.startswith(f"{prefix}/pulls/"):
                live = {**pr, "id": int(route.rsplit("/", 1)[1]), "number": int(route.rsplit("/", 1)[1])}
                return {**live, "head": {**live["head"], "sha": self.base}} if drift else live
            raise AssertionError(route)

        with (
            patch.object(EVENT, "api", side_effect=api),
            patch.object(
                EVENT,
                "pages",
                side_effect=lambda route, key=None: inventories[
                    route.replace("/pulls/24/", "/pulls/23/").replace("/pulls/25/", "/pulls/23/")
                ],
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

    def locator(self, index, *, pr=99, workflow=EVENT.REFRESH, **changes):
        created = self.now - dt.timedelta(seconds=1 + index * 600)
        return {
            "id": 10000 + index,
            "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "path": f".github/workflows/{workflow}",
            "event": "workflow_dispatch",
            "display_title": f"Reconcile review PR #{pr} head {self.head}",
            "status": "completed",
            **changes,
        }

    @staticmethod
    def inventory_response(history, route):
        parsed = urlsplit(route)
        query = parse_qs(parsed.query)
        lower, upper = query["created"][0].split("..")
        workflow = parsed.path.split("/workflows/")[1].split("/")[0]
        selected = sorted(
            (
                run
                for run in history
                if lower <= run["created_at"] <= upper and run["path"] == f".github/workflows/{workflow}"
            ),
            key=lambda run: run["id"],
            reverse=True,
        )
        page = int(query["page"][0])
        # Emulate the server's 1000-result ceiling, not an unlimited list.
        return {"total_count": len(selected), "workflow_runs": selected[:1000][(page - 1) * 100 : page * 100]}

    def inventory(self, history, transform=None):
        routes = []

        def api(route, payload=None):
            self.assertIsNone(payload)
            routes.append(route)
            response = self.inventory_response(history, route)
            return transform(route, response) if transform else response

        with patch.object(EVENT, "api", side_effect=api):
            result = EVENT.dispatch_inventory("repos/lightning-it/ansible-collection-supplementary", self.now)
        self.assertLessEqual(len(routes), EVENT.DISPATCH_INVENTORY_REQUESTS)
        self.assertTrue(all(int(parse_qs(urlsplit(route).query)["page"][0]) <= 10 for route in routes))
        return result

    def test_dispatch_inventory_boundaries_and_full_seven_day_volume(self):
        for count in (0, 99, 100, 999, 1000, 1008):
            with self.subTest(count=count):
                history = [self.locator(i) for i in range(count)]
                self.assertEqual({run["id"] for run in history}, {run["id"] for run in self.inventory(history)})
        # Ten PRs each generating 1008 locators, including both consumers.
        history = [
            self.locator(i, id=10000 + pr * 1008 + i, pr=pr, workflow=EVENT.REFRESH if pr % 2 else EVENT.HELPER)
            for pr in range(10)
            for i in range(1008)
        ]
        self.assertEqual(10080, len(self.inventory(history)))

    def test_large_history_reaches_real_caller_and_keeps_per_pr_event_dedup(self):
        history = [self.locator(i) for i in range(1008)]
        history.append(self.locator(0, id=99999, pr=24, status="in_progress"))
        calls = self.reconcile(history=history, pr_count=3, delay=86400)
        self.assertEqual(["23", "25"], [payload["inputs"]["pr_number"] for _, payload in calls])
        self.assertTrue(all(route.endswith("/dispatches") for route, _ in calls))

    def test_unknown_post_later_native_inventory_suppresses_duplicate(self):
        history = [self.locator(i) for i in range(1008)]
        self.assertEqual(1, len(self.reconcile(history=history, uncertain=True)))
        accepted = self.locator(0, id=99999, pr=23, status="queued")
        self.assertEqual([], self.reconcile(history=[*history, accepted]))
        accepted["status"] = "completed"
        self.assertEqual([], self.reconcile(history=[*history, accepted]))
        accepted["updated_at"] = (self.now - dt.timedelta(minutes=11)).isoformat()
        self.assertEqual(1, len(self.reconcile(history=[*history, accepted])))
        # These are locators only; actual rerun CAS is covered by the real writer suite.

    def test_split_boundaries_are_disjoint_and_include_both_ttl_endpoints(self):
        middle = self.now - EVENT.TTL / 2
        stamps = (self.now - EVENT.TTL, middle, middle + dt.timedelta(seconds=1), self.now)
        history = [self.locator(i, created_at=stamps[i % 4].strftime("%Y-%m-%dT%H:%M:%SZ")) for i in range(1008)]
        self.assertEqual(1008, len(self.inventory(history)))

    def test_incomplete_duplicate_or_racing_inventory_prevents_all_dispatches(self):
        history = [self.locator(i) for i in range(200)]

        def duplicate(route, response):
            if "page=2" in route and response["workflow_runs"]:
                response["workflow_runs"][0] = history[-1]
            return response

        def count_race(route, response):
            if "page=2" in route:
                response["total_count"] += 1
            return response

        def partial(route, response):
            response["workflow_runs"] = response["workflow_runs"][:-1]
            return response

        for transform in (duplicate, count_race, partial):
            with self.subTest(transform=transform.__name__), self.assertRaises(ValueError):
                self.reconcile(history=history, transform=transform)

    def test_split_count_race_and_cross_workflow_duplicate_fail_before_dispatch(self):
        history = [self.locator(i) for i in range(1008)]

        def split_race(route, response):
            if response["total_count"] == 1008:
                response["total_count"] = 1009
            return response

        with self.assertRaisesRegex(ValueError, "changed while splitting"):
            self.reconcile(history=history, transform=split_race)
        history = [self.locator(0), self.locator(0, workflow=EVENT.HELPER)]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.reconcile(history=history)

    def test_long_running_locator_beyond_first_thousand_still_suppresses_dispatch(self):
        history = [self.locator(i) for i in range(1008)]
        history[0] = self.locator(0, pr=23, status="in_progress")
        self.assertEqual([], self.reconcile(history=history))

    def test_saturated_second_and_budget_exhaustion_fail_closed(self):
        history = [self.locator(i, created_at=self.now.strftime("%Y-%m-%dT%H:%M:%SZ")) for i in range(1000)]
        with self.assertRaisesRegex(ValueError, "within one second"):
            self.reconcile(history=history)
        with patch.object(EVENT, "DISPATCH_INVENTORY_REQUESTS", 1):
            with self.assertRaisesRegex(ValueError, "budget exhausted"):
                self.reconcile(history=[self.locator(i) for i in range(1008)])

    def test_unbound_and_malformed_inventory_is_never_accepted(self):
        for field, value in (
            ("id", True),
            ("event", "push"),
            ("created_at", "invalid"),
            ("created_at", "2020-01-01T00:00:00Z"),
            ("path", "foreign"),
        ):

            def change(route, response, field=field, value=value):
                if response["workflow_runs"]:
                    response["workflow_runs"][0] = {**response["workflow_runs"][0], field: value}
                return response

            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.reconcile(history=[self.locator(0)], transform=change)

    def test_all_rerun_writers_share_the_exact_head_lane(self):
        helper = (ROOT / ".github/workflows/current-revision-rerun.yml").read_text()
        self.assertIn(
            "format('current-revision-{0}-head-{1}-check-current-revision-review', "
            "github.repository_id, inputs.expected_head)",
            helper,
        )
        self.assertIn("cancel-in-progress: false", helper)
