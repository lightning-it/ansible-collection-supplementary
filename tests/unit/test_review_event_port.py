"""Canonical port invariants outside the central .github Required authority."""

import json
import os
import shutil
import subprocess
import unittest

from unit.review_event_contract_helpers import ROOT, shell_function


class EventPortTests(unittest.TestCase):
    def test_event_producer_attempt_and_complete_terminal_inventory(self):
        function = shell_function(ROOT / ".github/workflows/current-revision-rerun.yml", "validate_event_producer")
        for attempt in (1, 2):
            for conclusion in ("success", "failure"):
                producer = {
                    "id": 42,
                    "run_attempt": attempt,
                    "status": "completed",
                    "conclusion": conclusion,
                    "actor": {"login": "litroc"},
                    "triggering_actor": {"login": "litroc" if attempt == 1 else "github-actions[bot]"},
                }
                jobs = [
                    {
                        "total_count": 3,
                        "jobs": [
                            {
                                "id": 100 + index,
                                "name": name,
                                "run_id": 42,
                                "run_attempt": attempt,
                                "head_sha": "b" * 40,
                                "status": "completed",
                                "conclusion": result,
                            }
                            for index, (name, result) in enumerate(
                                (
                                    ("Verify current revision policy", "success"),
                                    ("Request protected verifier re-evaluation", conclusion),
                                    ("Inactive legacy handoff", "skipped"),
                                )
                            )
                        ],
                    }
                ]
                cases = [("valid", producer, jobs, True)]
                for name, target, key, value in (
                    ("stale attempt", "producer", "run_attempt", 3 - attempt),
                    ("in progress", "producer", "status", "in_progress"),
                    ("hidden job", "page", "total_count", 4),
                    ("fractional id", "job", "id", 100.5),
                    ("wrong head", "job", "head_sha", "c" * 40),
                    ("extra failure", "job", "conclusion", "failure"),
                ):
                    p, j = (json.loads(json.dumps(producer)), json.loads(json.dumps(jobs)))
                    {"producer": p, "page": j[0], "job": j[0]["jobs"][0]}[target][key] = value
                    cases.append((name, p, j, False))
                for name, p, j, valid in cases:
                    with self.subTest(attempt=attempt, conclusion=conclusion, case=name):
                        result = subprocess.run(  # noqa: S603 -- fixed local workflow fixture and stub transport.
                            [
                                shutil.which("bash") or "/bin/bash",
                                "-c",
                                function + '\nvalidate_event_producer "$PAYLOAD" "$JOBS"',
                            ],
                            env={
                                **os.environ,
                                "PAYLOAD": json.dumps(p),
                                "JOBS": json.dumps(j),
                                "EVENT_PRODUCER_RUN_ATTEMPT": str(attempt),
                                "producer_id": "42",
                                "author": "litroc",
                                "EXPECTED_HEAD": "b" * 40,
                            },
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        self.assertEqual(valid, result.returncode == 0, result.stderr)

    def test_terminal_markers_never_claim_or_post_and_later_valid_review_can_resume(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("markers", ROOT / "scripts/review_content_markers.py")
        markers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(markers)
        workflow = ROOT / ".github/workflows/copilot-review-refresh.yml"
        for marker in markers.FAILURE_MARKERS:
            for inline in (False, True):
                with self.subTest(marker=marker, inline=inline):
                    script = (
                        r"""set -euo pipefail
revalidate_refresh_state() { :; }
validate_refresh_owner_run() { :; }
assert_refresh_rerun_budget() { :; }
read_refresh_review_state() { printf '%s' '{"event_current":true,"incomplete":0,"unresolved":0}'; }
claim_review_operation() { printf C; }
gh() {
  if [[ "$*" == *'--method POST'* ]]; then printf P;
  else printf '%s' '{"status":"completed","run_attempt":1}'; fi
}
oa() {
  if [[ "$*" == *'/comments?'* ]]; then printf '%s' "$COMMENTS";
  elif [[ "$*" == *'/reviews?'* ]]; then printf '[[%s]]' "$REVIEW";
  else printf '%s' "$REVIEW"; fi
}
"""
                        + shell_function(workflow, "usable_current_review")
                        + "\n"
                        + shell_function(workflow, "rerun_owner_if_review_current")
                        + r"""
first="$(rerun_owner_if_review_current)"
test -z "$first"
REVIEW="$VALID_REVIEW"
COMMENTS='[[]]'
rerun_owner_if_review_current
"""
                    )
                    valid = {
                        "id": 17,
                        "commit_id": "b" * 40,
                        "body": "Review complete",
                        "user": {"login": "copilot-pull-request-reviewer[bot]"},
                        "state": "COMMENTED",
                    }
                    result = subprocess.run(  # noqa: S603 -- fixed local workflow fixture and stub transport.
                        [shutil.which("bash") or "/bin/bash", "-c", script],
                        capture_output=True,
                        text=True,
                        check=False,
                        env={
                            **os.environ,
                            "REVIEW": json.dumps(valid if inline else valid | {"body": marker}),
                            "VALID_REVIEW": json.dumps(valid),
                            "COMMENTS": json.dumps([[{"body": marker}]] if inline else [[]]),
                            "current_external_kind": "copilot",
                            "REPOSITORY": "lightning-it/shared-assets-lit",
                            "PR_NUMBER": "23",
                            "HEAD_SHA": "b" * 40,
                            "BASE_SHA": "a" * 40,
                            "owner_run_id": "77",
                            "refresh_expected_count": "0",
                            "refresh_expected_snapshot": "fixture",
                        },
                    )
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertTrue(result.stdout.startswith("CPRerun requested"), result.stdout)
