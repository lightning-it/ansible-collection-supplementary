"""Regression tests for the stable protected-main promotion result."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "main-promotion-authorization.yml"
FINAL_JOB_ID = "merge-gate"
FINAL_JOB_NAME = "Main promotion merge gate"
FINAL_STEP = {
    "name": "Require successful protected authorization",
    "env": {
        "AUTHORIZE_RESULT": "${{ needs.authorize.result }}",
        "CLASSIFY_RESULT": "${{ needs.classify.result }}",
    },
    "run": ('set -euo pipefail\ntest "$CLASSIFY_RESULT" = success\ntest "$AUTHORIZE_RESULT" = success\n'),
}


def load_workflow() -> dict[str, Any]:
    """Load the workflow as one mapping."""

    payload = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError("main-promotion workflow is not a YAML mapping")
    return payload


class MainPromotionMergeGateTests(unittest.TestCase):
    """Keep the required context stable, deterministic, and fail-closed."""

    def test_final_gate_has_the_exact_protected_contract(self) -> None:
        jobs = load_workflow()["jobs"]
        gate = jobs[FINAL_JOB_ID]

        self.assertEqual(gate["name"], FINAL_JOB_NAME)
        self.assertEqual(gate["if"], "${{ always() }}")
        self.assertEqual(gate["needs"], ["classify", "authorize"])
        self.assertEqual(gate["permissions"], {})
        self.assertEqual(gate["steps"], [FINAL_STEP])
        self.assertEqual(
            sum(job.get("name") == FINAL_JOB_NAME for job in jobs.values() if isinstance(job, dict)),
            1,
        )

    def test_normal_promotion_still_uses_the_classified_human_environment(
        self,
    ) -> None:
        jobs = load_workflow()["jobs"]

        self.assertEqual(jobs["authorize"]["needs"], "classify")
        self.assertEqual(
            jobs["authorize"]["environment"],
            {"name": "${{ needs.classify.outputs.environment }}"},
        )
        self.assertEqual(
            jobs["classify"]["outputs"]["environment"],
            "${{ steps.classify.outputs.environment }}",
        )

    def test_policy_root_bootstrap_is_limited_to_exact_normal_develop(self) -> None:
        jobs = load_workflow()["jobs"]
        for job_name, step_name in (
            ("classify", "Classify exact live pull request"),
            ("authorize", "Revalidate exact live state after authorization"),
        ):
            with self.subTest(job=job_name):
                steps = jobs[job_name]["steps"]
                command = next(step["run"] for step in steps if step["name"] == step_name)
                self.assertIn(
                    "grep -Fq 'parser.add_argument(\"--base-root\"'",
                    command,
                )
                self.assertIn(
                    "policy_root_args=(--base-root policy --head-root candidate)",
                    command,
                )
                self.assertIn('and (.head.ref == "develop")', command)
                self.assertIn("and (.head.repo.full_name == $repo)", command)
                self.assertIn('"${policy_root_args[@]}"', command)

    def test_workflow_enforces_the_exact_release_team_environment_contract(self) -> None:
        jobs = load_workflow()["jobs"]
        jq = shutil.which("jq")
        if jq is None:
            self.fail("jq is required for the environment-contract regression test")
        payloads = (
            (self.normal_environment(), True),
            (self.normal_environment(prevent_self_review=True), False),
            (self.normal_environment(team_id=1), False),
            (self.normal_environment(reviewer_type="User"), False),
        )
        for job_name, step_name in (
            ("classify", "Classify exact live pull request"),
            ("authorize", "Revalidate exact live state after authorization"),
        ):
            with self.subTest(job=job_name):
                command = next(step["run"] for step in jobs[job_name]["steps"] if step["name"] == step_name)
                predicate = self.jq_environment_predicate(command)
                for payload, expected_success in payloads:
                    result = subprocess.run(  # noqa: S603 -- fixed jq binary and workflow-owned predicate.
                        [jq, "-e", predicate],
                        check=False,
                        input=json.dumps(payload),
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode == 0, expected_success, result.stderr)

    @staticmethod
    def normal_environment(
        *,
        prevent_self_review: bool = False,
        team_id: int = 15545798,
        reviewer_type: str = "BusinessTeam",
    ) -> dict[str, Any]:
        return {
            "name": "normal-release-promotion-approval",
            "can_admins_bypass": False,
            "protection_rules": [
                {
                    "type": "required_reviewers",
                    "prevent_self_review": prevent_self_review,
                    "reviewers": [{"type": reviewer_type, "reviewer": {"id": team_id}}],
                }
            ],
        }

    @staticmethod
    def jq_environment_predicate(command: str) -> str:
        environment_name = '(.name == "normal-release-promotion-approval")'
        condition_start = command.index(environment_name)
        predicate_start = command.rfind("jq -e '\n", 0, condition_start)
        if predicate_start < 0:
            raise AssertionError("workflow is missing the normal-environment jq predicate")
        predicate_start += len("jq -e '\n")
        predicate_end = command.index("' live-environment.json >/dev/null", condition_start)
        return command[predicate_start:predicate_end]

    def test_final_gate_succeeds_only_when_both_upstreams_succeed(self) -> None:
        command = FINAL_STEP["run"]
        bash = shutil.which("bash")
        if bash is None:
            self.fail("bash is required for the final-gate regression test")
        for classify_result in ("success", "failure", "cancelled", "skipped"):
            for authorize_result in ("success", "failure", "cancelled", "skipped"):
                with self.subTest(
                    classify_result=classify_result,
                    authorize_result=authorize_result,
                ):
                    environment = {
                        **os.environ,
                        "CLASSIFY_RESULT": classify_result,
                        "AUTHORIZE_RESULT": authorize_result,
                    }
                    result = subprocess.run(  # noqa: S603 -- fixed shell and test-owned command.
                        [bash, "-c", command],
                        check=False,
                        env=environment,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        result.returncode == 0,
                        classify_result == authorize_result == "success",
                    )


if __name__ == "__main__":
    unittest.main()
