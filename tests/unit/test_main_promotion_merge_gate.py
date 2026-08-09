"""Regression tests for the stable protected-main promotion result."""

from __future__ import annotations

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
