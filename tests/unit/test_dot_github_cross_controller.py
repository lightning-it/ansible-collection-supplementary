from __future__ import annotations

import copy
import importlib.util
import io
import json
import shutil
import subprocess
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify-dot-github-current-revision.py"
WORKFLOW = ROOT / ".github" / "workflows" / "dot-github-current-revision-required.yml"
RERUN_WORKFLOWS = (ROOT / ".github/workflows/current-revision-rerun.yml",)

SPEC = importlib.util.spec_from_file_location("dot_github_verifier", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

BASE = "443c9e7eee49b85545468b11217be3c6735d6f37"
HEAD = "041878621fa8e3c1d8f2c90f055038ef46eb7927"
SOURCE = "3" * 40
PR_NUMBER = 248
RUN_ID = 32388453605
CHECK_ID = 96488599818
WORKFLOW_ID = 335885126
SERVER = "https://github.com"
API = "https://api.github.com"
TARGET = "lightning-it/.github"
SOURCE_REPOSITORY = "lightning-it/ansible-collection-supplementary"
CHECK_PATH = (
    f"repos/{TARGET}/commits/{HEAD}/check-runs"
    "?check_name=Protected%20current-revision%20verifier&filter=all&per_page=100"
)
PR_PATH = f"repos/{TARGET}/pulls/{PR_NUMBER}"


class SourceBindingTests(unittest.TestCase):
    def test_workflow_ref_is_derived_from_the_single_source_repository(self) -> None:
        self.assertEqual(MODULE.SOURCE_REPOSITORY, SOURCE_REPOSITORY)
        self.assertEqual(
            MODULE.SOURCE_WORKFLOW_REF,
            f"{SOURCE_REPOSITORY}/{MODULE.SOURCE_WORKFLOW_PATH}@refs/heads/main",
        )


class FakeClient:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: dict[str, int] = {}
        self.api_url = API

    def metadata_revision(self, number: int) -> Any:
        return self.get(f"metadata/{number}")

    def get(self, path: str) -> Any:
        if path not in self.responses:
            raise AssertionError(f"unexpected API path: {path}")
        count = self.calls.get(path, 0)
        self.calls[path] = count + 1
        response = self.responses[path]
        if isinstance(response, ResponseSequence):
            return copy.deepcopy(response.values[min(count, len(response.values) - 1)])
        return copy.deepcopy(response)


class ResponseSequence:
    def __init__(self, *values: Any) -> None:
        self.values = values


def valid_environment(*, action: str = "opened", base: str = BASE) -> dict[str, str]:
    return {
        "REPOSITORY": TARGET,
        "EVENT_ACTION": action,
        "EVENT_UPDATED_AT": "2026-10-07T00:00:00Z",
        "EVENT_TITLE_JSON": json.dumps(valid_pr()["title"]),
        "EVENT_BODY_JSON": json.dumps(valid_pr()["body"]),
        "EVENT_LABELS_JSON": json.dumps(valid_pr()["labels"]),
        "EVENT_BASE": base,
        "EVENT_HEAD": HEAD,
        "EVENT_HEAD_REPOSITORY": TARGET,
        "EVENT_HEAD_REPOSITORY_OWNER": "lightning-it",
        "EVENT_HEAD_REF": valid_pr()["head"]["ref"],
        "EVENT_BASE_REF": "develop",
        "EVENT_AUTHOR": "lightning-it-shared-assets-sync[bot]",
        "EVENT_AUTHOR_TYPE": "Bot",
        "EVENT_SENDER": "lightning-it-shared-assets-sync[bot]",
        "PR_NUMBER": str(PR_NUMBER),
        "GITHUB_SERVER_URL": SERVER,
        "WORKFLOW_REF": MODULE.SOURCE_WORKFLOW_REF,
        "WORKFLOW_SHA": SOURCE,
    }


def valid_pr(*, head: str = HEAD) -> dict[str, Any]:
    return {
        "number": PR_NUMBER,
        "title": "ordinary human change",
        "body": None,
        "labels": [],
        "state": "open",
        "draft": False,
        "base": {"ref": "develop", "sha": BASE, "repo": {"full_name": TARGET}},
        "head": {
            "ref": "chore/sync-repository-quality-.github-32388411388-1",
            "sha": head,
            "repo": {"full_name": TARGET, "owner": {"login": "lightning-it"}},
        },
        "user": {"login": "lightning-it-shared-assets-sync[bot]", "type": "Bot"},
    }


def valid_check(*, conclusion: str = "success") -> dict[str, Any]:
    return {
        "id": CHECK_ID,
        "name": MODULE.RESERVATION_NAME,
        "status": "completed",
        "conclusion": conclusion,
        "head_sha": HEAD,
        "external_id": (f"rep60-required-workflow:v3:{RUN_ID}:{PR_NUMBER}:{BASE}:{HEAD}"),
        "details_url": f"{SERVER}/{TARGET}/runs/{CHECK_ID}",
        "app": {"id": 15368, "slug": "github-actions"},
        "output": {
            "summary": f"PR #{PR_NUMBER}; base {BASE}; head {HEAD}; producer {SERVER}/{TARGET}/actions/runs/42."
        },
    }


def valid_neutral():
    return {
        "id": 123,
        "name": "Current revision review",
        "head_sha": HEAD,
        "status": "completed",
        "conclusion": "success",
        "app": {"id": 15368, "slug": "github-actions"},
        "details_url": f"{SERVER}/{TARGET}/runs/123",
        "external_id": f"mlx90-current-revision:copilot:v6:{PR_NUMBER}:42:{BASE}:{HEAD}",
        "output": {
            "title": "Current revision review passed",
            "summary": json.dumps(
                {
                    "schema": 4,
                    "pull_request_number": PR_NUMBER,
                    "base_sha": BASE,
                    "head_sha": HEAD,
                    "controller_sha": SOURCE,
                    "review_path": "applicable Copilot or governed automation exemption",
                    "producer_run_id": 42,
                    "run_url": f"{SERVER}/{TARGET}/actions/runs/42",
                }
            ),
        },
    }


def valid_responses(*, action: str = "opened") -> dict[str, Any]:
    check = valid_check()
    return {
        f"repos/{SOURCE_REPOSITORY}": {
            "full_name": SOURCE_REPOSITORY,
            "visibility": "public",
            "archived": False,
            "disabled": False,
        },
        f"repos/{SOURCE_REPOSITORY}/branches/main": {
            "name": "main",
            "protected": True,
            "commit": {"sha": SOURCE},
        },
        f"repos/{SOURCE_REPOSITORY}/compare/{SOURCE}...{SOURCE}": {
            "status": "identical",
            "ahead_by": 0,
            "behind_by": 0,
            "base_commit": {"sha": SOURCE},
            "merge_base_commit": {"sha": SOURCE},
        },
        (f"repos/{SOURCE_REPOSITORY}/contents/{MODULE.SOURCE_WORKFLOW_PATH}?ref={SOURCE}"): {
            "type": "file",
            "sha": "4" * 40,
        },
        (f"repos/{SOURCE_REPOSITORY}/contents/scripts/verify-dot-github-current-revision.py?ref={SOURCE}"): {
            "type": "file",
            "sha": "5" * 40,
        },
        f"repos/{TARGET}": {
            "full_name": TARGET,
            "default_branch": "develop",
            "archived": False,
            "disabled": False,
        },
        PR_PATH: valid_pr(),
        f"metadata/{PR_NUMBER}": None,
        f"repos/{TARGET}/commits/{HEAD}/check-runs?check_name=Current%20revision%20review&filter=all&per_page=100": {
            "total_count": 1,
            "check_runs": [valid_neutral()],
        },
        CHECK_PATH: {"total_count": 1, "check_runs": [check]},
        f"repos/{TARGET}/actions/runs/{RUN_ID}": {
            "id": RUN_ID,
            "created_at": "2026-10-07T00:00:00Z",
            "event": "pull_request_target",
            "path": MODULE.TARGET_VERIFIER_PATH,
            "status": "completed",
            "conclusion": "success",
            "repository": {"full_name": TARGET},
            "head_repository": {"full_name": TARGET, "owner": {"login": "lightning-it"}},
            "head_sha": HEAD,
            "head_branch": valid_pr()["head"]["ref"],
            "pull_requests": [],
            "actor": {"login": "lightning-it-shared-assets-sync[bot]"},
            "triggering_actor": {"login": "lightning-it-shared-assets-sync[bot]"},
            "run_attempt": 1,
            "display_title": (f"Protected current revision PR #{PR_NUMBER} {action} {HEAD}"),
            "html_url": f"{SERVER}/{TARGET}/actions/runs/{RUN_ID}",
            "workflow_id": WORKFLOW_ID,
            "workflow_url": (f"{API}/repos/{TARGET}/actions/workflows/{WORKFLOW_ID}"),
        },
        f"repos/{TARGET}/actions/workflows/{WORKFLOW_ID}": {
            "id": WORKFLOW_ID,
            "path": MODULE.TARGET_VERIFIER_PATH,
            "state": "active",
        },
        f"repos/{TARGET}/actions/runs/{RUN_ID}/attempts/1/jobs?per_page=100": {
            "total_count": 1,
            "jobs": [
                {
                    "name": MODULE.TARGET_VERIFIER_NAME,
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        },
    }


class DotGitHubCrossControllerTests(unittest.TestCase):
    def test_accepts_one_exact_successful_protected_verifier(self) -> None:
        client = FakeClient(valid_responses())
        MODULE.verify(client, valid_environment(), attempts=1, sleep=lambda _: None)
        self.assertEqual(client.calls[PR_PATH], 2)
        self.assertEqual(client.calls[CHECK_PATH], 2)

    def test_accepts_ready_for_review_after_draft_is_cleared(self) -> None:
        client = FakeClient(valid_responses(action="ready_for_review"))
        MODULE.verify(
            client,
            valid_environment(action="ready_for_review"),
            attempts=1,
            sleep=lambda _: None,
        )

    def test_accepts_an_edited_event_only_when_live_base_is_unchanged(self) -> None:
        client = FakeClient(valid_responses(action="edited"))
        MODULE.verify(
            client,
            valid_environment(action="edited"),
            attempts=1,
            sleep=lambda _: None,
        )

        with self.assertRaisesRegex(MODULE.VerificationError, "live base SHA"):
            MODULE.verify(
                FakeClient(valid_responses(action="edited")),
                valid_environment(action="edited", base="6" * 40),
                attempts=1,
                sleep=lambda _: None,
            )

    def test_waits_for_a_failed_reservation_to_be_reproved(self) -> None:
        responses = valid_responses()
        failed = valid_check(conclusion="failure")
        successful = valid_check()
        responses[CHECK_PATH] = ResponseSequence(
            {"total_count": 1, "check_runs": [failed]},
            {"total_count": 1, "check_runs": [successful]},
            {"total_count": 1, "check_runs": [successful]},
        )
        sleeps: list[float] = []
        MODULE.verify(
            FakeClient(responses),
            valid_environment(),
            attempts=2,
            sleep=sleeps.append,
        )
        self.assertEqual(sleeps, [10])

    def test_waits_for_the_bound_producer_run_to_complete(self) -> None:
        responses = valid_responses()
        producer_path = f"repos/{TARGET}/actions/runs/{RUN_ID}"
        pending = copy.deepcopy(responses[producer_path])
        pending["status"] = "in_progress"
        pending["conclusion"] = None
        responses[producer_path] = ResponseSequence(
            pending,
            responses[producer_path],
        )
        sleeps: list[float] = []

        MODULE.verify(
            FakeClient(responses),
            valid_environment(),
            attempts=2,
            sleep=sleeps.append,
        )

        self.assertEqual(sleeps, [2])

    def test_rejects_a_completed_unsuccessful_bound_producer(self) -> None:
        responses = valid_responses()
        producer = responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]
        producer["conclusion"] = "failure"

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "verifier run conclusion",
        ):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(),
                attempts=1,
                sleep=lambda _: None,
            )

    def test_rejects_a_bound_producer_that_never_completes(self) -> None:
        responses = valid_responses()
        producer = responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]
        producer["status"] = "in_progress"
        producer["conclusion"] = None

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "protected verifier run did not complete",
        ):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(),
                attempts=2,
                sleep=lambda _: None,
            )

    def test_rejects_an_unknown_bound_producer_status_immediately(self) -> None:
        responses = valid_responses()
        producer = responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]
        producer["status"] = "unknown"
        producer["conclusion"] = None
        sleeps: list[float] = []

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "verifier run status is invalid: 'unknown'",
        ):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(),
                attempts=2,
                sleep=sleeps.append,
            )

        self.assertEqual(sleeps, [])

    def test_rejects_duplicate_exact_reservations(self) -> None:
        responses = valid_responses()
        check = valid_check()
        responses[CHECK_PATH] = {"total_count": 2, "check_runs": [check, check]}
        with self.assertRaisesRegex(MODULE.VerificationError, "ambiguous"):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(),
                attempts=1,
                sleep=lambda _: None,
            )

    def test_rejects_a_reservation_for_the_same_head_on_an_old_base(self) -> None:
        responses = valid_responses(action="edited")
        responses[CHECK_PATH]["check_runs"][0]["external_id"] = (
            f"rep60-required-workflow:v3:{RUN_ID}:{PR_NUMBER}:{'6' * 40}:{HEAD}"
        )
        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "did not become successful",
        ):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(action="edited"),
                attempts=1,
                sleep=lambda _: None,
            )

    def test_rejects_candidate_or_wrong_producer_workflow(self) -> None:
        responses = valid_responses()
        responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]["path"] = ".github/workflows/candidate.yml"
        with self.assertRaisesRegex(MODULE.VerificationError, "verifier path"):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(),
                attempts=1,
                sleep=lambda _: None,
            )

    def test_rest_run_head_is_the_pr_head_not_runner_github_sha(self) -> None:
        responses = valid_responses()
        producer_path = f"repos/{TARGET}/actions/runs/{RUN_ID}"
        producer = responses[producer_path]
        self.assertEqual(RUN_ID, 32388453605)
        self.assertEqual(producer["head_sha"], HEAD)
        self.assertEqual(producer["pull_requests"], [])
        MODULE.verify(
            FakeClient(responses),
            valid_environment(),
            attempts=1,
            sleep=lambda _: None,
        )

        responses = valid_responses()
        responses[producer_path]["head_sha"] = BASE
        with self.assertRaisesRegex(MODULE.VerificationError, "verifier run head"):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(),
                attempts=1,
                sleep=lambda _: None,
            )

    def test_rejects_a_required_workflow_url_for_the_local_verifier(self) -> None:
        responses = valid_responses()
        responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]["workflow_url"] = (
            f"{API}/repos/{TARGET}/actions/required_workflows/{WORKFLOW_ID}"
        )
        with self.assertRaisesRegex(MODULE.VerificationError, "workflow URL"):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(),
                attempts=1,
                sleep=lambda _: None,
            )

    def test_accepts_the_single_protected_actions_reproof_attempt(self) -> None:
        responses = valid_responses()
        producer = responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]
        producer["run_attempt"] = 2
        producer["triggering_actor"] = {"login": "github-actions[bot]"}
        responses.pop(f"repos/{TARGET}/actions/runs/{RUN_ID}/attempts/1/jobs?per_page=100")
        responses[f"repos/{TARGET}/actions/runs/{RUN_ID}/attempts/2/jobs?per_page=100"] = {
            "total_count": 1,
            "jobs": [
                {
                    "name": MODULE.TARGET_VERIFIER_NAME,
                    "status": "completed",
                    "conclusion": "success",
                }
            ],
        }
        MODULE.verify(
            FakeClient(responses),
            valid_environment(),
            attempts=1,
            sleep=lambda _: None,
        )

    def test_rejects_live_head_drift_after_verification(self) -> None:
        responses = valid_responses()
        responses[PR_PATH] = ResponseSequence(valid_pr(), valid_pr(head="6" * 40))
        with self.assertRaisesRegex(MODULE.VerificationError, "live head SHA"):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(),
                attempts=1,
                sleep=lambda _: None,
            )

    def test_rejects_an_unprotected_source_branch(self) -> None:
        responses = valid_responses()
        responses[f"repos/{SOURCE_REPOSITORY}/branches/main"]["protected"] = False
        with self.assertRaisesRegex(MODULE.VerificationError, "branch protection"):
            MODULE.verify(
                FakeClient(responses),
                valid_environment(),
                attempts=1,
                sleep=lambda _: None,
            )

    def test_http_failures_preserve_status_reason_and_path(self) -> None:
        client = MODULE.GitHubClient("test-token", "https://api.github.test")
        failure = urllib.error.HTTPError(
            "https://api.github.test/repos/lightning-it/.github",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(),
        )
        with (
            mock.patch.object(MODULE.urllib.request, "urlopen", side_effect=failure),
            self.assertRaisesRegex(
                MODULE.VerificationError,
                r"repos/lightning-it/\.github: HTTP 503 Service Unavailable",
            ),
        ):
            client.get("repos/lightning-it/.github")

    def test_check_query_is_derived_from_the_reservation_constant(self) -> None:
        responses = valid_responses()
        client = FakeClient(responses)
        MODULE.matching_reservations(client, PR_NUMBER, BASE, HEAD)
        self.assertIn(CHECK_PATH, client.calls)

    def test_every_rerun_consumer_has_an_unambiguous_v3_v2_cutover(
        self,
    ) -> None:
        expected_pattern = "^rep60-required-workflow:v3:([1-9][0-9]*):${PR_NUMBER}:${EXPECTED_BASE}:${EXPECTED_HEAD}$"
        expected_v2_pattern = "^rep60-required-workflow:v2:([1-9][0-9]*):${PR_NUMBER}:${EXPECTED_HEAD}$"
        for path in RERUN_WORKFLOWS:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertIn(expected_pattern, source)
                self.assertIn(expected_v2_pattern, source)
                self.assertIn(
                    "Protected verifier evidence is malformed, unsupported, or version-ambiguous.",
                    source,
                )
                self.assertIn(
                    "actions/runs?head_sha=${EXPECTED_HEAD}",
                    source,
                )
                self.assertNotIn("actions/runs?event=pull_request_target", source)
                self.assertIn('select(.event == "pull_request_target")', source)
                self.assertIn(
                    'if [ "${required_run_count}" -ne 1 ]; then',
                    source,
                )
                self.assertNotIn(
                    "for reservation_attempt in",
                    source,
                )
                self.assertNotIn(
                    "Protected verifier evidence did not materialize in time.",
                    source,
                )
                self.assertIn(
                    'reservation_count="$(jq \'length\' <<<"${matching_reservations}")"',
                    source,
                )
                self.assertIn(
                    'test "${reservation_count}" -le 1',
                    source,
                )
                self.assertIn(
                    'test "${reservation_run_id}" = "${run_id}"',
                    source,
                )
                self.assertIn(
                    "Protected verifier reservation is absent; the unique protected run owns bootstrap re-evaluation.",
                    source,
                )
                self.assertIn('same_head_reservations="$(jq -c', source)
                self.assertIn("all(.[];", source)
                self.assertIn('--arg pr "${PR_NUMBER}"', source)
                same_head = source.index('same_head_reservations="$(jq -c')
                validated = source.index("all(.[];", same_head)
                matched = source.index('matching_reservations="$(jq -c', validated)
                counted = source.index('reservation_count="$(jq \'length\' <<<"${matching_reservations}")"')
                self.assertLess(same_head, validated)
                self.assertLess(validated, matched)
                self.assertLess(matched, counted)
                self.assertNotIn("candidate_external_id", source)
                self.assertNotIn("v3_count", source)
                self.assertNotIn("v2_count", source)

    def test_rerun_reservation_filter_accepts_foreign_pr_evidence_only_when_valid(
        self,
    ) -> None:
        jq = shutil.which("jq")
        self.assertIsNotNone(jq)
        assert jq is not None
        source = RERUN_WORKFLOWS[0].read_text(encoding="utf-8")
        validation_start = '          if ! jq -e \\\n              --arg head "${EXPECTED_HEAD}" \''
        validation_end = '\n              \' <<<"${same_head_reservations}" >/dev/null; then'
        matching_start = (
            '          matching_reservations="$(jq -c \\\n'
            '            --arg base "${EXPECTED_BASE}" \\\n'
            '            --arg head "${EXPECTED_HEAD}" \\\n'
            '            --arg pr "${PR_NUMBER}" \''
        )
        matching_end = '\n            \' <<<"${same_head_reservations}")"'

        self.assertIn(validation_start, source)
        self.assertIn(validation_end, source)
        self.assertIn(matching_start, source)
        self.assertIn(matching_end, source)
        validation_program = source.split(validation_start, 1)[1].split(validation_end, 1)[0]
        matching_program = source.split(matching_start, 1)[1].split(matching_end, 1)[0]

        current = {"external_id": (f"rep60-required-workflow:v3:{RUN_ID}:{PR_NUMBER}:{BASE}:{HEAD}")}
        foreign = {"external_id": (f"rep60-required-workflow:v3:{RUN_ID + 1}:1544:{BASE}:{HEAD}")}
        inventory = [current, foreign]

        validated = subprocess.run(  # noqa: S603 -- Fixed jq program extracted from the checked-in protected workflow.
            [jq, "-e", "--arg", "head", HEAD, validation_program],
            input=json.dumps(inventory),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, validated.returncode, validated.stderr)
        matched = subprocess.run(  # noqa: S603 -- Fixed jq program extracted from the checked-in protected workflow.
            [
                jq,
                "-c",
                "--arg",
                "base",
                BASE,
                "--arg",
                "head",
                HEAD,
                "--arg",
                "pr",
                str(PR_NUMBER),
                matching_program,
            ],
            input=json.dumps(inventory),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, matched.returncode, matched.stderr)
        self.assertEqual([current], json.loads(matched.stdout))

        for malformed_external_id in (
            "malformed",
            f"rep60-required-workflow:v3:{RUN_ID}:1544:{BASE}:{'f' * 40}",
        ):
            with self.subTest(external_id=malformed_external_id):
                rejected = subprocess.run(  # noqa: S603 -- Fixed jq program extracted from the checked-in protected workflow.
                    [jq, "-e", "--arg", "head", HEAD, validation_program],
                    input=json.dumps([current, {"external_id": malformed_external_id}]),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertNotEqual(0, rejected.returncode)

        duplicated = subprocess.run(  # noqa: S603 -- Fixed jq program extracted from the checked-in protected workflow.
            [
                jq,
                "-c",
                "--arg",
                "base",
                BASE,
                "--arg",
                "head",
                HEAD,
                "--arg",
                "pr",
                str(PR_NUMBER),
                matching_program,
            ],
            input=json.dumps([current, current]),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, duplicated.returncode, duplicated.stderr)
        self.assertEqual(2, len(json.loads(duplicated.stdout)))

    def test_rerun_waits_for_a_terminal_required_workflow_result(self) -> None:
        canonical = RERUN_WORKFLOWS[0].read_text(encoding="utf-8")
        terminal_probe = (
            "            if jq -e '\n"
            '                .status == "completed"\n'
            '                and (.conclusion | type) == "string"\n'
            '              \' <<<"${run}" >/dev/null; then'
        )
        for path in RERUN_WORKFLOWS:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertEqual(canonical, source)
                self.assertIn(
                    "for verifier_attempt in $(seq 1 40); do",
                    source,
                )
                self.assertIn(terminal_probe, source)
                self.assertIn(
                    'if [ "${verifier_attempt}" -eq 40 ]; then',
                    source,
                )
                self.assertIn(
                    "Protected verifier did not reach a terminal conclusion in time.",
                    source,
                )
                self.assertIn(
                    'case "${verifier_conclusion}" in',
                    source,
                )
                self.assertIn(
                    "Protected verifier ended with unsupported conclusion ${verifier_conclusion}.",
                    source,
                )
                self.assertNotIn(
                    'if [ "$(jq -r .status <<<"${run}")" = completed ]; then',
                    source,
                )

    def test_rerun_binds_non_local_required_workflow_path_to_api_url(self) -> None:
        canonical = RERUN_WORKFLOWS[0].read_text(encoding="utf-8")
        for path in RERUN_WORKFLOWS:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertEqual(canonical, source)
                self.assertIn(
                    "An organization Required Workflow is reported in the target",
                    source,
                )
                self.assertIn(
                    '.path == ".github/workflows/supplementary-current-revision-required.yml"',
                    source,
                )
                self.assertIn(
                    '"/actions/required_workflows/" + (.workflow_id | tostring)',
                    source,
                )

    def test_workflow_is_read_only_and_never_checks_out_candidate_code(self) -> None:
        source = WORKFLOW.read_text(encoding="utf-8")
        document = yaml.safe_load(source)
        trigger = document.get("on", document.get(True))
        self.assertEqual(
            trigger,
            {
                "pull_request_target": {
                    "types": [
                        "opened",
                        "synchronize",
                        "reopened",
                        "ready_for_review",
                        "edited",
                        "labeled",
                        "unlabeled",
                    ]
                }
            },
        )
        job = document["jobs"]["verify-dot-github-current-revision"]
        self.assertEqual(job["if"], "github.repository == 'lightning-it/.github'")
        self.assertEqual(
            job["permissions"],
            {
                "actions": "read",
                "checks": "read",
                "contents": "read",
                "pull-requests": "read",
            },
        )
        checkout = job["steps"][0]
        self.assertRegex(checkout["uses"], r"@(?:[0-9a-f]{40})$")
        self.assertEqual(
            checkout["with"]["repository"],
            "lightning-it/ansible-collection-supplementary",
        )
        self.assertEqual(checkout["with"]["ref"], "${{ github.workflow_sha }}")
        self.assertFalse(checkout["with"]["persist-credentials"])
        self.assertEqual(
            job["steps"][1]["env"]["EVENT_HEAD_REPOSITORY"], "${{ github.event.pull_request.head.repo.full_name }}"
        )
        self.assertEqual(
            job["steps"][1]["env"]["EVENT_HEAD_REPOSITORY_OWNER"],
            "${{ github.event.pull_request.head.repo.owner.login }}",
        )
        for field, expression in {
            "EVENT_UPDATED_AT": "${{ github.event.pull_request.updated_at }}",
            "EVENT_TITLE_JSON": "${{ toJson(github.event.pull_request.title) }}",
            "EVENT_BODY_JSON": "${{ toJson(github.event.pull_request.body) }}",
            "EVENT_LABELS_JSON": "${{ toJson(github.event.pull_request.labels) }}",
        }.items():
            self.assertEqual(job["steps"][1]["env"][field], expression)
        self.assertNotIn("github.event.pull_request", json.dumps(checkout))
        self.assertNotIn("copilot", source.lower())
        self.assertNotIn("codex", source.lower())


class AuthenticatedCoreForkTests(unittest.TestCase):
    def fixture(self, branch="develop", associated=False):
        environment = valid_environment()
        environment.update(
            EVENT_HEAD_REPOSITORY="contributor/core-fork",
            EVENT_HEAD_REPOSITORY_OWNER="contributor",
            EVENT_HEAD_REF="feature/fork",
            EVENT_BASE_REF=branch,
            EVENT_AUTHOR="contributor",
            EVENT_AUTHOR_TYPE="User",
            EVENT_SENDER="contributor",
        )
        responses = valid_responses()
        pr = responses[PR_PATH]
        pr["base"]["ref"] = branch
        pr["head"].update(
            ref="feature/fork", repo={"full_name": "contributor/core-fork", "owner": {"login": "contributor"}}
        )
        pr["user"] = {"login": "contributor", "type": "User"}
        producer = responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]
        producer.update(
            head_branch="feature/fork",
            head_repository=copy.deepcopy(pr["head"]["repo"]),
            actor={"login": "contributor"},
            triggering_actor={"login": "contributor"},
        )
        if associated:
            producer["pull_requests"] = [
                {
                    "number": PR_NUMBER,
                    "url": f"{API}/repos/{TARGET}/pulls/{PR_NUMBER}",
                    "base": {"sha": BASE, "ref": branch, "repo": {"url": f"{API}/repos/{TARGET}"}},
                    "head": {"sha": HEAD, "ref": "feature/fork", "repo": {"url": f"{API}/repos/contributor/core-fork"}},
                }
            ]
        return environment, responses

    def test_core_fork_develop_and_main_bind_both_native_reads(self):
        for branch in ("develop", "main"):
            for associated in (False, True):
                with self.subTest(branch=branch, associated=associated):
                    env, responses = self.fixture(branch, associated)
                    client = FakeClient(responses)
                    MODULE.verify(client, env, attempts=1, sleep=lambda _: None)
                    self.assertEqual(2, client.calls[PR_PATH])
                    self.assertEqual(2, client.calls[CHECK_PATH])

    def test_missing_malformed_or_mismatched_event_identity_stops_before_reads(self):
        for key, value in (
            ("EVENT_HEAD_REPOSITORY", None),
            ("EVENT_HEAD_REPOSITORY", "wrong"),
            ("EVENT_HEAD_REPOSITORY", "../fork"),
            ("EVENT_HEAD_REPOSITORY_OWNER", None),
            ("EVENT_HEAD_REPOSITORY_OWNER", "other"),
            ("EVENT_HEAD_REF", ""),
            ("EVENT_BASE_REF", "feature"),
            ("EVENT_AUTHOR", None),
            ("EVENT_AUTHOR_TYPE", "Bot"),
            ("EVENT_AUTHOR_TYPE", "Organization"),
        ):
            with self.subTest(key=key, value=value):
                env, responses = self.fixture()
                if value is None:
                    env.pop(key)
                else:
                    env[key] = value
                client = FakeClient(responses)
                with self.assertRaises(MODULE.VerificationError):
                    MODULE.verify(client, env, attempts=1, sleep=lambda _: None)
                self.assertEqual({}, client.calls)

    def test_pre_and_post_verification_identity_drift_is_closed(self):
        changes = {
            "another fork same SHA/ref": lambda p: p["head"]["repo"].update(
                full_name="another/core-fork", owner={"login": "another"}
            ),
            "missing owner": lambda p: p["head"]["repo"].pop("owner"),
            "mismatched owner": lambda p: p["head"]["repo"]["owner"].update(login="another"),
            "head ref": lambda p: p["head"].update(ref="same-sha-new-branch"),
            "base ref": lambda p: p["base"].update(ref="main"),
            "author": lambda p: p["user"].update(login="another"),
            "number": lambda p: p.update(number=PR_NUMBER + 1),
        }
        for label, change in changes.items():
            for final in (False, True):
                with self.subTest(change=label, final=final):
                    env, responses = self.fixture()
                    original = responses[PR_PATH]
                    changed = copy.deepcopy(original)
                    change(changed)
                    responses[PR_PATH] = ResponseSequence(original, changed) if final else changed
                    client = FakeClient(responses)
                    with self.assertRaises(MODULE.VerificationError):
                        MODULE.verify(client, env, attempts=1, sleep=lambda _: None)
                    self.assertEqual(2 if final else 1, client.calls[PR_PATH])

    def test_native_producer_identity_and_recorded_fork_tuple_are_required(self):
        changes = {
            "wrong base repository": lambda p: p["repository"].update(full_name="another/.github"),
            "wrong fork repository": lambda p: p["head_repository"].update(full_name="another/core-fork"),
            "missing owner": lambda p: p["head_repository"].pop("owner"),
            "wrong owner": lambda p: p["head_repository"]["owner"].update(login="another"),
            "wrong recorded fork": lambda p: p["pull_requests"][0]["head"]["repo"].update(
                url=f"{API}/repos/another/core-fork"
            ),
            "wrong recorded base": lambda p: p["pull_requests"][0]["base"]["repo"].update(
                url=f"{API}/repos/another/.github"
            ),
            "wrong recorded ref": lambda p: p["pull_requests"][0]["head"].update(ref="another"),
            "wrong recorded PR": lambda p: p["pull_requests"][0].update(number=PR_NUMBER + 1),
            "ambiguous association": lambda p: p["pull_requests"].append(copy.deepcopy(p["pull_requests"][0])),
        }
        for label, change in changes.items():
            with self.subTest(change=label):
                env, responses = self.fixture(associated=True)
                change(responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"])
                with self.assertRaises(MODULE.VerificationError):
                    MODULE.verify(FakeClient(responses), env, attempts=1, sleep=lambda _: None)


if __name__ == "__main__":
    unittest.main()


class OrdinaryHumanPublisherABITests(unittest.TestCase):
    def test_actual_eight_key_publisher_accepts_default_controller_distinct_from_base(self):
        summary = json.loads(valid_neutral()["output"]["summary"])
        self.assertEqual(
            set(summary),
            {
                "schema",
                "base_sha",
                "head_sha",
                "controller_sha",
                "pull_request_number",
                "producer_run_id",
                "review_path",
                "run_url",
            },
        )
        self.assertNotEqual(summary["controller_sha"], summary["base_sha"])
        client = FakeClient(valid_responses(action="edited"))
        MODULE.verify(client, valid_environment(action="edited"), attempts=1, sleep=lambda _: None)
        self.assertEqual(client.calls[PR_PATH], 2)
        self.assertEqual(client.calls[f"metadata/{PR_NUMBER}"], 2)

    def test_human_summary_rejects_missing_immutable_binding_and_fabricated_extensions(self):
        key = f"repos/{TARGET}/commits/{HEAD}/check-runs?check_name=Current%20revision%20review&filter=all&per_page=100"
        for field in ("head_sha", "base_sha", "controller_sha", "producer_run_id", "review_path"):
            with self.subTest(missing=field):
                responses = valid_responses()
                check = responses[key]["check_runs"][0]
                summary = json.loads(check["output"]["summary"])
                del summary[field]
                check["output"]["summary"] = json.dumps(summary)
                with self.assertRaises(MODULE.VerificationError):
                    MODULE.verify(FakeClient(responses), valid_environment(), attempts=1, sleep=lambda _: None)
        for field, value in (("controller_sha", "invalid"), ("head_repository", TARGET), ("review_path", "")):
            with self.subTest(field=field):
                responses = valid_responses()
                check = responses[key]["check_runs"][0]
                summary = json.loads(check["output"]["summary"])
                summary[field] = value
                check["output"]["summary"] = json.dumps(summary)
                with self.assertRaises(MODULE.VerificationError):
                    MODULE.verify(FakeClient(responses), valid_environment(), attempts=1, sleep=lambda _: None)

    def test_actual_renovate_extension_retains_mutable_metadata_and_identity_binding(self):
        key = f"repos/{TARGET}/commits/{HEAD}/check-runs?check_name=Current%20revision%20review&filter=all&per_page=100"
        check = valid_neutral()
        summary = json.loads(check["output"]["summary"])
        summary.update(
            controller_ref="develop",
            head_repository=TARGET,
            pull_request_last_edited_at=None,
            pull_request_labels_sha256=MODULE.labels_digest([]),
            review_id=None,
            review_path="deterministic policy-bound Renovate exemption",
        )
        check["output"]["title"] = "Current revision Renovate exemption passed"
        check["external_id"] = f"mlx90-current-revision:renovate:v6:{PR_NUMBER}:42:{BASE}:{HEAD}"
        check["output"]["summary"] = json.dumps(summary)
        pr = valid_pr()
        pr["_metadata_revision"] = None

        def validate(candidate):
            return MODULE.validate_neutral_metadata(
                FakeClient({key: {"total_count": 1, "check_runs": [candidate]}}),
                valid_check(),
                pr,
                PR_NUMBER,
                BASE,
                HEAD,
                SERVER,
            )

        self.assertEqual(validate(check), check)
        for field, value in (
            ("pull_request_last_edited_at", "2026-10-06T23:59:59Z"),
            ("pull_request_labels_sha256", "0" * 64),
            ("head_repository", "contributor/core-fork"),
            ("review_id", 42),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(check)
                invalid_summary = dict(summary, **{field: value})
                changed["output"]["summary"] = json.dumps(invalid_summary)
                with self.assertRaises(MODULE.VerificationError):
                    validate(changed)
        for field, value in (
            ("title", "Current revision review passed"),
            ("external_id", valid_neutral()["external_id"]),
        ):
            with self.subTest(check_field=field):
                changed = copy.deepcopy(check)
                if field == "title":
                    changed["output"][field] = value
                else:
                    changed[field] = value
                with self.assertRaises(MODULE.VerificationError):
                    validate(changed)


class MutableEventBindingTests(unittest.TestCase):
    def label_fixture(self, action):
        environment = valid_environment(action=action)
        responses = valid_responses(action=action)
        labels = [{"name": "review-current"}] if action == "labeled" else []
        responses[PR_PATH]["labels"] = labels
        responses[PR_PATH]["user"] = {"login": "litroc", "type": "User"}
        environment.update(
            EVENT_LABELS_JSON=json.dumps(labels), EVENT_AUTHOR="litroc", EVENT_AUTHOR_TYPE="User", EVENT_SENDER="litroc"
        )
        run = responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]
        run["actor"] = {"login": "litroc"}
        run["triggering_actor"] = {"login": "litroc"}
        return environment, responses

    def test_authenticated_labeled_and_unlabeled_events_bind_both_live_reads(self):
        for action in ("labeled", "unlabeled"):
            with self.subTest(action=action):
                environment, responses = self.label_fixture(action)
                client = FakeClient(responses)
                MODULE.verify(client, environment, attempts=1, sleep=lambda _: None)
                self.assertEqual(2, client.calls[PR_PATH])
                self.assertEqual(2, client.calls[f"metadata/{PR_NUMBER}"])

    def test_maintainer_label_sender_is_separate_from_contributor_author_and_rerun_actor(self):
        for action in ("labeled", "unlabeled"):
            for attempt in (1, 2):
                with self.subTest(action=action, attempt=attempt):
                    environment, responses = self.label_fixture(action)
                    environment.update(EVENT_AUTHOR="contributor", EVENT_SENDER="maintainer")
                    responses[PR_PATH]["user"]["login"] = "contributor"
                    run = responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]
                    run.update(
                        actor={"login": "maintainer"},
                        triggering_actor={"login": "maintainer" if attempt == 1 else "github-actions[bot]"},
                        run_attempt=attempt,
                    )
                    if attempt == 2:
                        jobs = responses.pop(f"repos/{TARGET}/actions/runs/{RUN_ID}/attempts/1/jobs?per_page=100")
                        responses[f"repos/{TARGET}/actions/runs/{RUN_ID}/attempts/2/jobs?per_page=100"] = jobs
                    MODULE.verify(FakeClient(responses), environment, attempts=1, sleep=lambda _: None)
                    for sender in (None, "another", "contributor"):
                        with self.subTest(sender=sender), self.assertRaises(MODULE.VerificationError):
                            MODULE.verify(
                                FakeClient(responses),
                                {**environment, "EVENT_SENDER": sender},
                                attempts=1,
                                sleep=lambda _: None,
                            )
                    run["triggering_actor"] = {"login": "another"}
                    with self.assertRaises(MODULE.VerificationError):
                        MODULE.verify(FakeClient(responses), environment, attempts=1, sleep=lambda _: None)

    def test_label_event_rejects_old_action_time_and_labels_drift_at_either_read(self):
        for action in ("labeled", "unlabeled"):
            for defect in ("action", "creation", "first-labels", "second-labels"):
                with self.subTest(action=action, defect=defect):
                    environment, responses = self.label_fixture(action)
                    run = responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]
                    if defect == "action":
                        run["display_title"] = f"Protected current revision PR #{PR_NUMBER} edited {HEAD}"
                    elif defect == "creation":
                        run["created_at"] = "2026-10-06T23:59:59Z"
                    else:
                        original = copy.deepcopy(responses[PR_PATH])
                        changed = copy.deepcopy(original)
                        changed["labels"] = [{"name": "later-label"}]
                        responses[PR_PATH] = (
                            changed if defect == "first-labels" else ResponseSequence(original, changed)
                        )
                    with self.assertRaises(MODULE.VerificationError):
                        MODULE.verify(FakeClient(responses), environment, attempts=1, sleep=lambda _: None)

    def test_rejects_mutable_metadata_and_label_drift_at_either_read(self):
        for field, value in (("title", "new title"), ("body", "new body"), ("labels", [{"name": "new"}])):
            for read in (1, 2):
                with self.subTest(field=field, read=read):
                    responses = valid_responses()
                    changed = valid_pr()
                    changed[field] = value
                    responses[PR_PATH] = changed if read == 1 else ResponseSequence(valid_pr(), changed)
                    with self.assertRaises(MODULE.VerificationError):
                        MODULE.verify(FakeClient(responses), valid_environment(), attempts=1, sleep=lambda _: None)

    def test_rejects_metadata_revision_changed_then_reverted_text(self):
        responses = valid_responses()
        responses[f"metadata/{PR_NUMBER}"] = ResponseSequence(None, "2026-10-07T00:00:01Z")
        with self.assertRaisesRegex(MODULE.VerificationError, "final metadata revision"):
            MODULE.verify(FakeClient(responses), valid_environment(), attempts=1, sleep=lambda _: None)

    def test_repeated_edited_events_cannot_reuse_older_action_or_same_action_run(self):
        for action in ("edited",):
            for defect in ("action", "creation"):
                with self.subTest(action=action, defect=defect):
                    responses = valid_responses(action=action)
                    run = responses[f"repos/{TARGET}/actions/runs/{RUN_ID}"]
                    if defect == "action":
                        run["display_title"] = f"Protected current revision PR #{PR_NUMBER} opened {HEAD}"
                    else:
                        run["created_at"] = "2026-10-06T23:59:59Z"
                    with self.assertRaises(MODULE.VerificationError):
                        MODULE.verify(
                            FakeClient(responses), valid_environment(action=action), attempts=1, sleep=lambda _: None
                        )

    def test_current_edited_event_accepts_exact_schema4_publisher(self):
        for action in ("edited",):
            client = FakeClient(valid_responses(action=action))
            MODULE.verify(client, valid_environment(action=action), attempts=1, sleep=lambda _: None)
            self.assertEqual(client.calls[PR_PATH], 2)
            self.assertEqual(client.calls[f"metadata/{PR_NUMBER}"], 2)

    def test_neutral_publisher_wrong_producer_or_ambiguity_rejected(self):
        key = f"repos/{TARGET}/commits/{HEAD}/check-runs?check_name=Current%20revision%20review&filter=all&per_page=100"
        for field, value in (("producer_run_id", 43),):
            with self.subTest(field=field):
                responses = valid_responses()
                check = responses[key]["check_runs"][0]
                summary = json.loads(check["output"]["summary"])
                summary[field] = value
                check["output"]["summary"] = json.dumps(summary)
                with self.assertRaises(MODULE.VerificationError):
                    MODULE.verify(FakeClient(responses), valid_environment(), attempts=1, sleep=lambda _: None)
        responses = valid_responses()
        responses[key]["check_runs"].append(valid_neutral())
        responses[key]["total_count"] = 2
        with self.assertRaisesRegex(MODULE.VerificationError, "ambiguous"):
            MODULE.verify(FakeClient(responses), valid_environment(), attempts=1, sleep=lambda _: None)

    def test_sorted_labels_use_existing_utf8_compact_contract(self):
        self.assertEqual(
            MODULE.labels_digest([{"name": "z"}, {"name": "ä"}]), MODULE.labels_digest([{"name": "ä"}, {"name": "z"}])
        )
        with self.assertRaises(MODULE.VerificationError):
            MODULE.labels_digest([{"name": "z"}, {"name": "z"}])
