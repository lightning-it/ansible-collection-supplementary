import datetime as dt
import importlib.util
import os
import re
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

    def test_copilot_completion_wakes_only_the_protected_inventory_locator(self):
        import yaml

        path = ROOT / ".github/workflows/review-event-reconcile.yml"
        workflow = yaml.safe_load(path.read_text())
        events = workflow.get("on", workflow.get(True))
        self.assertEqual(["completed"], events["workflow_run"]["types"])
        self.assertEqual(
            {
                "Copilot",
                "Running Copilot Code Review",
                "Current revision review gate",
                "Protected current-revision evidence verifier",
                "Protected dot-github current-revision verifier",
                "Refresh Copilot review gate",
            },
            set(events["workflow_run"]["workflows"]),
        )
        self.assertEqual([{"cron": "*/10 * * * *"}], events["schedule"])
        job = workflow["jobs"]["reconcile"]
        self.assertIn("vars.LI219_EVENT_MODE == 'enabled'", job["if"])
        self.assertEqual("${{ github.workflow_sha }}", job["steps"][0]["with"]["ref"])
        self.assertIs(False, job["steps"][0]["with"]["persist-credentials"])
        executable = job["steps"][1]["run"]
        self.assertIn("python3 scripts/review-event-reconcile.py", executable)
        self.assertNotIn("github.event.", executable)
        self.assertNotIn("GITHUB_EVENT_PATH", executable)
        self.assertNotIn("GITHUB_EVENT_PATH", (ROOT / "scripts/review-event-reconcile.py").read_text())
        mirror = ROOT / "default/.github/workflows/review-event-reconcile.yml"
        if mirror.exists():
            self.assertEqual(path.read_bytes(), mirror.read_bytes())

    def test_review_completion_wakeup_is_scoped_to_review_events_and_loop_free(self):
        import json
        from types import SimpleNamespace as NS

        import yaml

        workflow = yaml.safe_load((ROOT / ".github/workflows/review-event-reconcile.yml").read_text())
        events = workflow.get("on", workflow.get(True))
        expression = " ".join(workflow["jobs"]["reconcile"]["if"].replace("&&", " and ").replace("||", " or ").split())
        missing_path = object()

        class WorkflowRun(NS):
            def __getattr__(self, _name):
                # GitHub expressions evaluate a missing property as an empty string.
                return ""

        def enabled(
            name="Refresh Copilot review gate",
            upstream="pull_request_review",
            conclusion="success",
            event="workflow_run",
            mode="enabled",
            status="completed",
            attempt=1,
            repository="lightning-it/ansible-collection-supplementary",
            head_repository="lightning-it/ansible-collection-supplementary",
            actor="Copilot",
            triggering_actor="Copilot",
            path=".github/workflows/copilot-review-refresh.yml",
        ):
            github = NS(
                repository="lightning-it/ansible-collection-supplementary",
                event_name=event,
                event=NS(
                    workflow_run=WorkflowRun(
                        name=name,
                        event=upstream,
                        conclusion=conclusion,
                        status=status,
                        run_attempt=attempt,
                        repository=NS(full_name=repository),
                        head_repository=NS(full_name=head_repository),
                        actor=NS(login=actor),
                        triggering_actor=NS(login=triggering_actor),
                        **({"path": path} if path is not missing_path else {}),
                    )
                ),
            )
            triggered = event == "schedule" or name in events["workflow_run"]["workflows"]
            return triggered and eval(  # noqa: S307 -- Actual bounded workflow predicate.
                expression,
                {"__builtins__": {}},
                {
                    "github": github,
                    "vars": NS(LI219_EVENT_MODE=mode),
                    "contains": lambda values, item: item in values,
                    "fromJSON": json.loads,
                },
            )

        for conclusion in (
            "success",
            "skipped",
            "failure",
            "cancelled",
            "timed_out",
            "neutral",
            "action_required",
            "stale",
        ):
            for upstream in ("pull_request_review", "pull_request_review_comment"):
                self.assertEqual(conclusion == "success", enabled(upstream=upstream, conclusion=conclusion))
            for upstream in ("workflow_dispatch", "pull_request_target", "push", "schedule", "workflow_run"):
                self.assertFalse(enabled(upstream=upstream, conclusion=conclusion))
        self.assertFalse(enabled(mode="disabled"))
        self.assertFalse(enabled(name="Reconcile delayed review events"))
        self.assertTrue(enabled(event="schedule", upstream="workflow_dispatch"))
        for path in (
            missing_path,
            "",
            None,
            ".github/workflows/foreign-refresh.yml",
            ".github/workflows/copilot-review-refresh.yml@refs/heads/foreign",
        ):
            with self.subTest(path=path):
                self.assertFalse(enabled(path=path))
                self.assertTrue(enabled(event="schedule", path=path))
        self.assertTrue(enabled(path=".github/workflows/copilot-review-refresh.yml"))
        for name in ("Copilot", "Running Copilot Code Review", "Refresh Copilot review gate"):
            for actor in ("Copilot", "copilot-pull-request-reviewer", "copilot-pull-request-reviewer[bot]"):
                self.assertTrue(enabled(name=name, actor=actor, triggering_actor=actor))
        for changes in (
            {"status": "in_progress"},
            {"status": "queued"},
            {"attempt": 2},
            {"attempt": 0},
            {"repository": "foreign/repo"},
            {"head_repository": "contributor/fork"},
            {"actor": "contributor", "triggering_actor": "contributor"},
            {"triggering_actor": "contributor"},
            {"actor": "github-actions[bot]", "triggering_actor": "github-actions[bot]"},
            {"name": "Current revision review gate"},
            {"name": "Protected dot-github current-revision verifier"},
            {"name": "Protected current-revision evidence verifier"},
            {"event": "workflow_dispatch"},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(enabled(**changes))
        self.assertTrue(
            enabled(event="schedule", conclusion="failure", actor="contributor", head_repository="fork/repo")
        )
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow["jobs"]["reconcile"]["if"])
        self.assertNotIn("Refresh Copilot review gate", workflow["jobs"]["reconcile"]["steps"][1]["run"])

    def review(self, **changes):
        return {
            "id": 17,
            "commit_id": self.head,
            "body": "Review complete.",
            "user": {"login": "copilot-pull-request-reviewer[bot]"},
            "state": "COMMENTED",
            **changes,
        }

    def test_any_files_marker_requires_explicit_negation_in_body_or_inline(self):
        positives = (
            "The bot was able to review any files.",
            "able to review any files",
            "THE BOT WAS\u00a0ABLE\u2003TO REVIEW ANY FILES",
        )
        negatives = (
            "I can't review this pull request.",
            "I can\u2019t review this pull request.",
            "I can't review any files.",
            "I can\u2019t review any files.",
            "Copilot wasn't able to review any files.",
            "Copilot wasn\u2019t able to review any files.",
            "Copilot isn't able to review any files.",
            "Copilot isn\u2019t able to review any files.",
            "COPILOT ISN\u2019T ABLE\u2003TO\u00a0REVIEW\u202fANY\u2009FILES.",
            "The bots aren't able to review any files.",
            "The bots weren\u2019t able to review any files.",
            "COPILOT\u00a0WASN\u2019T\u2003ABLE\tTO REVIEW ANY FILES",
            "Copilot is not able to review any files.",
            "Copilot is unable to review any files.",
        )
        for messages, expected in ((positives, True), (negatives, False)):
            for text in messages:
                for inline in (False, True):
                    with self.subTest(text=text, inline=inline):
                        review = self.review() if inline else self.review(body=text)
                        comments = [{"body": text}] if inline else []
                        self.assertEqual(expected, EVENT.clean_review(review, comments, self.head))

    def test_ordered_required_terminal_supersession_preserves_all_guards(self):
        old = self.required_run()
        new = {**old, "id": 89, "created_at": "2026-10-05T17:01:00Z"}
        self.assertEqual(1, len(self.reconcile(neutral=True, required=[new, old])))
        self.assertEqual([], self.reconcile(neutral=True, required=[old, {**new, "conclusion": "success"}]))
        for changes in (
            {"status": "in_progress", "conclusion": None},
            {"run_attempt": 3},
            {"actor": {"login": "foreign"}},
            {"triggering_actor": {"login": "foreign"}},
            {"created_at": "invalid"},
            {"created_at": "2026-02-30T17:00:00Z"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual([], self.reconcile(neutral=True, required=[{**old, **changes}, new]))
        self.assertEqual(
            1,
            len(
                self.reconcile(
                    neutral=True,
                    required=[old, {**new, "run_attempt": 2, "triggering_actor": {"login": "github-actions[bot]"}}],
                )
            ),
        )

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

    def test_maintainer_label_required_sender_and_original_rerun_provenance(self):
        for action in ("labeled", "unlabeled"):
            original = self.required_run()
            original.update(
                actor={"login": "maintainer"},
                triggering_actor={"login": "maintainer"},
                display_title=f"Cross-protect .github PR #23 {action} {self.head}",
            )
            self.assertEqual(1, len(self.reconcile(neutral=True, required=[original])))
            rerun = {**original, "run_attempt": 2, "triggering_actor": {"login": "github-actions[bot]"}}
            self.assertEqual(1, len(self.reconcile(neutral=True, required=[rerun], original_required=original)))
            for changes in (
                {"actor": {"login": "foreign"}},
                {"triggering_actor": {"login": "foreign"}},
                {"id": 999},
                {"run_attempt": 2},
                {"status": "in_progress"},
                {"conclusion": "success"},
                {"head_sha": self.base},
                {"display_title": f"Cross-protect .github PR #23 opened {self.head}"},
            ):
                with self.subTest(action=action, changes=changes):
                    self.assertEqual(
                        [], self.reconcile(neutral=True, required=[rerun], original_required={**original, **changes})
                    )
            rerun["triggering_actor"] = {"login": "maintainer"}
            self.assertEqual([], self.reconcile(neutral=True, required=[rerun], original_required=original))

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
        neutral=False,
        required=None,
        inventory_transform=None,
        base_ref="develop",
        head_repo="lightning-it/.github",
        producer_head_repo=None,
        final_head_repo=None,
        original_required=None,
    ):
        prefix = "repos/lightning-it/.github"
        pr = {
            "id": 23,
            "number": 23,
            "draft": False,
            "state": "open",
            "user": {"login": "litroc", "type": "User"},
            "head": {"sha": self.head, "ref": "fix/final", "repo": {"full_name": head_repo}},
            "base": {"sha": self.base, "ref": base_ref, "repo": {"full_name": "lightning-it/.github"}},
        }
        run = {
            "id": 77,
            "path": EVENT.PRODUCER,
            "event": "pull_request_target",
            "repository": {"full_name": "lightning-it/.github"},
            "head_repository": {"full_name": producer_head_repo or head_repo},
            "run_attempt": 1,
            "head_sha": self.head,
            "head_branch": "fix/final",
            "pull_requests": [],
            "status": state,
            "created_at": (self.now - dt.timedelta(seconds=delay)).isoformat(),
        }
        default_required = self.required_run()
        default_required["head_repository"]["full_name"] = head_repo
        default_required["pull_requests"][0]["head"]["repo"]["url"] = "https://api.github.com/repos/" + head_repo
        default_required["pull_requests"][0]["base"]["ref"] = base_ref
        inventories = {
            f"{prefix}/pulls?state=open": [{**pr, "id": 23 + i, "number": 23 + i} for i in range(pr_count)],
            f"{prefix}/actions/runs?event=pull_request_target&head_sha={self.head}": [run],
            f"{prefix}/actions/runs?head_sha={self.head}": [
                run,
                *(required if required is not None else [default_required]),
            ],
            f"{prefix}/actions/runs/77/attempts/1/jobs": [
                {"id": 78, "name": "Verify current revision policy", "status": "completed", "conclusion": "success"}
            ],
            f"{prefix}/commits/{self.head}/check-runs?filter=all": [
                {
                    "id": 79,
                    "name": "Current revision review",
                    "app": {"id": 15368, "slug": "github-actions"},
                    "status": "completed",
                    "conclusion": "success",
                    "output": {"summary": '{"producer_run_id":77}'},
                }
            ]
            if neutral
            else [],
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
            if inventory_transform and "per_page=100&page=" in route:
                inventory_route = route.rsplit("&per_page=100&page=", 1)[0]
                if inventory_route == route:
                    inventory_route = route.rsplit("?per_page=100&page=", 1)[0]
                rows = inventories[inventory_route]
                key = (
                    "workflow_runs"
                    if "/actions/runs?" in inventory_route
                    else "jobs"
                    if "/jobs" in inventory_route
                    else "check_runs"
                    if "/check-runs" in inventory_route
                    else None
                )
                response = {"total_count": len(rows), key: rows} if key else rows
                return inventory_transform(route, response)
            if route == f"{prefix}/actions/runs/77":
                return run
            if route.endswith("/attempts/1"):
                if original_required is not None:
                    return original_required
                run_id = int(route.split("/actions/runs/")[1].split("/")[0])
                original = next(item for item in (required or [default_required]) if item["id"] == run_id)
                return {
                    **original,
                    "run_attempt": 1,
                    "triggering_actor": original["actor"],
                    "conclusion": "failure",
                }
            if route == prefix:
                return {"default_branch": "develop"}
            if route.startswith(f"{prefix}/pulls/"):
                if final_head_repo is not None:
                    return {**pr, "head": {**pr["head"], "repo": {"full_name": final_head_repo}}}
                return {**pr, "head": {**pr["head"], "sha": self.base}} if drift else pr
            raise AssertionError(route)

        with (
            patch.object(EVENT, "api", side_effect=api),
            patch.object(
                EVENT,
                "pages",
                side_effect=EVENT.pages
                if inventory_transform
                else lambda route, key=None: inventories[
                    route.replace("/pulls/24/", "/pulls/23/").replace("/pulls/25/", "/pulls/23/")
                ],
            ),
            patch.dict(
                os.environ, LI219_EVENT_MODE="enabled", GITHUB_REF="refs/heads/develop", GITHUB_REF_PROTECTED="true"
            ),
        ):
            if uncertain:
                with self.assertRaises(TimeoutError):
                    EVENT.reconcile("lightning-it/.github", self.now)
            else:
                EVENT.reconcile("lightning-it/.github", self.now)
        return mutations

    def test_main_refresh_dispatch_uses_authenticated_main_base(self):
        calls = self.reconcile(base_ref="main")
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0][0].endswith("copilot-review-refresh.yml/dispatches"))
        self.assertEqual("main", calls[0][1]["ref"])

    def test_ambiguous_first_pr_stays_closed_and_later_pr_dispatches(self):
        prefix = "repos/lightning-it/.github"
        pulls = [
            {
                "id": number,
                "number": number,
                "draft": False,
                "state": "open",
                "user": {"login": "litroc", "type": "User"},
                "head": {"sha": head, "ref": f"fix/{number}", "repo": {"full_name": "lightning-it/.github"}},
                "base": {"sha": self.base, "ref": "develop", "repo": {"full_name": "lightning-it/.github"}},
            }
            for number, head in ((23, self.head), (24, "c" * 40))
        ]
        inventories = {f"{prefix}/pulls?state=open": pulls}
        for pr in pulls:
            head = pr["head"]["sha"]
            inventories[f"{prefix}/actions/runs?event=pull_request_target&head_sha={head}"] = {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 77 + pr["number"],
                        "path": EVENT.PRODUCER,
                        "event": "pull_request_target",
                        "repository": pr["base"]["repo"],
                        "head_repository": pr["head"]["repo"],
                        "head_sha": head,
                        "head_branch": pr["head"]["ref"],
                        "pull_requests": [],
                        "status": "completed",
                        "created_at": self.now.isoformat(),
                    }
                ],
            }
            checks = (
                [
                    {
                        "id": check_id,
                        "name": "Current revision review",
                        "app": {"id": 15368, "slug": "github-actions"},
                        "status": "completed",
                        "conclusion": "success",
                    }
                    for check_id in (79, 80)
                ]
                if pr["number"] == 23
                else []
            )
            inventories[f"{prefix}/commits/{head}/check-runs?filter=all"] = {
                "total_count": len(checks),
                "check_runs": checks,
            }
        inventories[f"{prefix}/pulls/24/reviews"] = [self.review(commit_id="c" * 40)]
        inventories[f"{prefix}/pulls/24/reviews/17/comments"] = []
        mutations = []

        def api(route, payload=None):
            if payload is not None:
                mutations.append((route, payload))
                return None
            if route == prefix:
                return {"default_branch": "develop"}
            if "/actions/workflows/" in route:
                return self.inventory_response([], route)
            if route == f"{prefix}/pulls/24":
                return pulls[1]
            inventory_route = re.sub(r"[?&]per_page=100&page=1$", "", route)
            return inventories[inventory_route]

        with (
            patch.object(EVENT, "api", side_effect=api),
            patch.dict(
                os.environ, LI219_EVENT_MODE="enabled", GITHUB_REF="refs/heads/develop", GITHUB_REF_PROTECTED="true"
            ),
            patch("builtins.print") as log,
        ):
            EVENT.reconcile("lightning-it/.github", self.now)
        self.assertEqual(
            [
                (
                    f"{prefix}/actions/workflows/{EVENT.REFRESH}/dispatches",
                    {
                        "ref": "develop",
                        "inputs": {
                            "pr_number": "24",
                            "expected_head": "c" * 40,
                            "expected_base": self.base,
                            "review_id": "17",
                        },
                    },
                )
            ],
            mutations,
        )
        log.assert_any_call("PR 23: ambiguous neutral evidence; required failure remains blocking")

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

    def test_completed_locator_cooldown_boundary_and_active_hold(self):
        expected = [
            (
                "repos/lightning-it/.github/actions/workflows/copilot-review-refresh.yml/dispatches",
                {
                    "ref": "develop",
                    "inputs": {
                        "pr_number": "23",
                        "expected_head": self.head,
                        "expected_base": self.base,
                        "review_id": "17",
                    },
                },
            )
        ]
        for age in (599, 600, 601):
            for status in ("completed", "queued", "in_progress"):
                with self.subTest(age=age, status=status):
                    locator = self.locator(
                        0,
                        pr=23,
                        status=status,
                        conclusion="failure" if status == "completed" else None,
                        created_at=(self.now - dt.timedelta(seconds=1200)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        updated_at=(self.now - dt.timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                    calls = self.reconcile(delay=1800, history=[locator])
                    self.assertEqual(expected if status == "completed" and age >= 600 else [], calls)

    def test_active_dispatch_is_deduplicated(self):
        run = {
            "path": ".github/workflows/copilot-review-refresh.yml",
            "event": "workflow_dispatch",
            "display_title": "bound",
            "status": "queued",
        }
        self.assertTrue(EVENT.recent_dispatch([run], EVENT.REFRESH, "bound"))
        self.assertFalse(EVENT.recent_dispatch([run], EVENT.REFRESH, "foreign"))

    def required_run(self):
        repo = "lightning-it/.github"
        api_url = f"https://api.github.com/repos/{repo}"
        return {
            "id": 88,
            "workflow_id": 999,
            "event": "pull_request_target",
            "created_at": "2026-10-05T17:00:00Z",
            "run_attempt": 1,
            "actor": {"login": "litroc"},
            "triggering_actor": {"login": "litroc"},
            "path": ".github/workflows/dot-github-current-revision-required.yml",
            "workflow_url": f"{api_url}/actions/required_workflows/999",
            "repository": {"full_name": repo},
            "head_repository": {"full_name": repo},
            "head_sha": self.head,
            "head_branch": "fix/final",
            "status": "completed",
            "conclusion": "failure",
            "name": "Protected dot-github current-revision verifier",
            "display_title": f"Cross-protect .github PR #23 opened {self.head}",
            "pull_requests": [
                {
                    "number": 23,
                    "url": f"{api_url}/pulls/23",
                    "head": {"sha": self.head, "ref": "fix/final", "repo": {"url": api_url}},
                    "base": {"sha": self.base, "ref": "develop", "repo": {"url": api_url}},
                }
            ],
        }

    def test_required_recovery_uses_unfiltered_native_authority_inventory(self):
        # The event-filtered inventory contains ONLY the producer. The no-event
        # inventory also contains the actual organization Required run.
        calls = self.reconcile(neutral=True)
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0][0].endswith("current-revision-rerun.yml/dispatches"))
        self.assertEqual("77", calls[0][1]["inputs"]["producer_run_id"])
        self.assertEqual([], self.reconcile(neutral=True, required=[]))
        run = self.required_run()
        run["conclusion"] = "success"
        self.assertEqual([], self.reconcile(neutral=True, required=[run]))

    def test_label_required_titles_reconcile_same_producer_without_review_request(self):
        for action in ("labeled", "unlabeled"):
            with self.subTest(action=action):
                run = self.required_run()
                run["display_title"] = f"Cross-protect .github PR #23 {action} {self.head}"
                calls = self.reconcile(neutral=True, required=[run])
                self.assertEqual(1, len(calls))
                self.assertTrue(calls[0][0].endswith("current-revision-rerun.yml/dispatches"))
                self.assertEqual("77", calls[0][1]["inputs"]["producer_run_id"])
                self.assertEqual("1", calls[0][1]["inputs"]["producer_run_attempt"])
                run["actor"] = {"login": "foreign"}
                self.assertEqual([], self.reconcile(neutral=True, required=[run]))

    def test_label_required_locator_keeps_exact_native_authority_for_all_pilots(self):
        import json

        for repo in EVENT.PILOTS:
            for action in ("labeled", "unlabeled"):
                with self.subTest(repo=repo, action=action):
                    run = json.loads(json.dumps(self.required_run()).replace("lightning-it/.github", repo))
                    central = repo == "lightning-it/.github"
                    prefix = "Cross-protect .github" if central else "Protected current revision"
                    if not central:
                        run["path"] = ".github/workflows/supplementary-current-revision-required.yml"
                        run["name"] = "Protected current-revision evidence verifier"
                    run["display_title"] = f"{prefix} PR #23 {action} {self.head}"
                    pr = {
                        "number": 23,
                        "head": {"sha": self.head, "ref": "fix/final", "repo": {"full_name": repo}},
                        "base": {"sha": self.base, "ref": "develop"},
                    }
                    self.assertTrue(EVENT.required_locator(run, repo, pr))
                    run["display_title"] = f"{prefix} PR #24 {action} {self.head}"
                    self.assertFalse(EVENT.required_locator(run, repo, pr))
                    run["display_title"] = f"{prefix} PR #23 converted_to_draft {self.head}"
                    self.assertFalse(EVENT.required_locator(run, repo, pr))

    def test_required_title_action_sets_match_triggers_and_actual_helper_selection(self):
        import ast
        import json
        import re
        import shutil
        import subprocess

        import yaml

        verifier = ast.parse((ROOT / "scripts/verify-dot-github-current-revision.py").read_text())
        action_set = next(
            node.value.args[0]
            for node in verifier.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "PRODUCER_ACTIONS" for t in node.targets)
        )
        actions = {node.value for node in action_set.elts}
        locator = ast.parse((ROOT / "scripts/review-event-reconcile.py").read_text())
        function = next(n for n in locator.body if isinstance(n, ast.FunctionDef) and n.name == "required_locator")
        action_tuple = next(n.iter for n in ast.walk(function) if isinstance(n, ast.comprehension))
        self.assertEqual(actions, {node.value for node in action_tuple.elts})
        outer = yaml.safe_load((ROOT / ".github/workflows/dot-github-current-revision-required.yml").read_text())
        self.assertEqual(actions, set(outer.get("on", outer.get(True))["pull_request_target"]["types"]))
        helper = yaml.safe_load((ROOT / ".github/workflows/current-revision-rerun.yml").read_text())
        scripts = [step.get("run", "") for job in helper["jobs"].values() for step in job.get("steps", [])]
        body = next(script for script in scripts if 'required_runs="$(jq -c' in script)
        start = body.index('required_runs="$(jq -c')
        end = body.index("\nrequired_run_count=", start)
        selection = body[start:end]
        self.assertEqual(
            actions, set(re.findall(r'\+ \(\$pr_number \| tostring\) \+ " ([a-z_]+) " \+ \$head_sha', selection))
        )
        repo = "lightning-it/ansible-collection-supplementary"
        for action in ("labeled", "unlabeled", "converted_to_draft"):
            for number in (23, 24):
                with self.subTest(action=action, number=number):
                    run = json.loads(json.dumps(self.required_run()).replace("lightning-it/.github", repo))
                    run["path"] = ".github/workflows/supplementary-current-revision-required.yml"
                    run["name"] = "Protected current-revision evidence verifier"
                    run["display_title"] = f"Protected current revision PR #{number} {action} {self.head}"
                    result = subprocess.run(  # noqa: S603 -- actual local readonly JQ selector, no transport or effect code.
                        [
                            shutil.which("bash") or "/bin/bash",
                            "-c",
                            "set -euo pipefail\n" + selection + '\nprintf "%s" "$required_runs"',
                        ],
                        env={
                            **os.environ,
                            "GITHUB_API_URL": "https://api.github.com",
                            "base_ref": "develop",
                            "EXPECTED_BASE": self.base,
                            "head_ref": "fix/final",
                            "head_repository": repo,
                            "EXPECTED_HEAD": self.head,
                            "REPOSITORY": repo,
                            "PR_NUMBER": "23",
                            "required_runs_pages": json.dumps([{"total_count": 1, "workflow_runs": [run]}]),
                        },
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertEqual([run] if action in actions and number == 23 else [], json.loads(result.stdout))

    def test_local_foreign_stale_or_ambiguous_runs_never_stand_in_for_required(self):
        for field, value in (
            ("workflow_url", "https://api.github.com/repos/lightning-it/.github/actions/workflows/999"),
            ("path", ".github/workflows/supplementary-current-revision-required.yml"),
            ("event", "push"),
            ("head_sha", self.base),
            ("head_branch", "foreign"),
            ("repository", {"full_name": "lightning-it/foreign"}),
            ("head_repository", {"full_name": "lightning-it/foreign"}),
            ("display_title", f"Cross-protect .github PR #24 opened {self.head}"),
            ("workflow_id", True),
            ("status", "in_progress"),
        ):
            with self.subTest(field=field):
                run = self.required_run()
                run[field] = value
                self.assertEqual([], self.reconcile(neutral=True, required=[run]))
        for side in ("base", "head"):
            run = self.required_run()
            run["pull_requests"][0][side]["sha"] = "c" * 40
            self.assertEqual([], self.reconcile(neutral=True, required=[run]))
        run = self.required_run()
        run["pull_requests"][0]["number"] = 24
        self.assertEqual([], self.reconcile(neutral=True, required=[run]))
        self.assertEqual([], self.reconcile(neutral=True, required=[self.required_run(), self.required_run()]))

    def test_other_pilots_bind_the_central_organization_required_path(self):
        for repo in ("lightning-it/shared-assets-lit", "lightning-it/ansible-collection-supplementary"):
            run = self.required_run()
            import json

            run = json.loads(json.dumps(run).replace("lightning-it/.github", repo))
            run["path"] = ".github/workflows/supplementary-current-revision-required.yml"
            run["name"] = "Protected current-revision evidence verifier"
            run["display_title"] = f"Protected current revision PR #23 opened {self.head}"
            pr = {
                "number": 23,
                "head": {"sha": self.head, "ref": "fix/final", "repo": {"full_name": repo}},
                "base": {"sha": self.base, "ref": "develop"},
            }
            self.assertTrue(EVENT.required_locator(run, repo, pr))
            run["workflow_url"] = run["workflow_url"].replace("required_workflows", "workflows")
            self.assertFalse(EVENT.required_locator(run, repo, pr))

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
        # Native filtered-search totals can be clipped independently of pages.
        return {
            "total_count": min(2500, len(selected)),
            "workflow_runs": selected[:1000][(page - 1) * 100 : page * 100],
        }

    def inventory(self, history, transform=None):
        routes = []

        def api(route, payload=None):
            self.assertIsNone(payload)
            routes.append(route)
            response = self.inventory_response(history, route)
            return transform(route, response) if transform else response

        with patch.object(EVENT, "api", side_effect=api):
            result = EVENT.dispatch_inventory("repos/lightning-it/.github", self.now)
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

    def test_clipped_parent_2500_retains_all_10080_disjoint_child_results(self):
        history = [self.locator(i, id=10000 + pr * 1008 + i, pr=pr) for pr in range(10) for i in range(1008)]
        result = self.inventory(history)
        self.assertEqual(10080, len(result))
        self.assertEqual({run["id"] for run in history}, {run["id"] for run in result})

    def test_large_history_reaches_real_caller_and_keeps_per_pr_event_dedup(self):
        history = [self.locator(i) for i in range(1008)]
        history.append(self.locator(0, id=99999, pr=24, status="in_progress"))
        calls = self.reconcile(history=history, pr_count=3, delay=86400)
        self.assertEqual(["23", "25"], [payload["inputs"]["pr_number"] for _unused_value_1, payload in calls])
        self.assertTrue(all(route.endswith("/dispatches") for route, _unused_value_2 in calls))

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


class KeyedInventoryTests(unittest.TestCase):
    def test_short_native_inventories_stop_real_reconcile_before_dispatch(self):
        caller = ReviewEventTests()
        for fragment in ("actions/runs?event=", "/check-runs?", "actions/runs?head_sha=", "/attempts/1/jobs?"):

            def corrupt(route, response, fragment=fragment):
                if fragment in route:
                    response["total_count"] += 1
                return response

            with self.subTest(fragment=fragment), self.assertRaisesRegex(ValueError, "incomplete inventory"):
                caller.reconcile(neutral=True, inventory_transform=corrupt)
        self.assertEqual(1, len(caller.reconcile(neutral=True, inventory_transform=lambda route, response: response)))

    def test_keyed_inventory_counts_lengths_duplicates_and_bound(self):
        for key in ("workflow_runs", "jobs", "check_runs"):
            rows = [{"id": index + 1} for index in range(101)]
            good = [{"total_count": 101, key: rows[:100]}, {"total_count": 101, key: rows[100:]}]
            cases = [[{"total_count": value, key: []}] for value in (True, -1, "0", None, 1000)]
            cases += [
                [good[0], {"total_count": 102, key: rows[100:]}],
                [{"total_count": 101, key: rows[:99]}],
                [good[0], {"total_count": 101, key: []}],
                [good[0], {"total_count": 101, key: rows[:1]}],
            ]
            for responses in cases:
                with (
                    self.subTest(key=key, responses=len(responses)),
                    patch.object(EVENT, "api", side_effect=responses) as get,
                ):
                    with self.assertRaises(ValueError):
                        EVENT.pages("repos/test/inventory", key)
                    self.assertLessEqual(get.call_count, 10)
            with patch.object(EVENT, "api", side_effect=good):
                self.assertEqual(rows, EVENT.pages("repos/test/inventory", key))
