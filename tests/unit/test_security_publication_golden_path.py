from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "collection-publish.yml"


class SecurityPublicationGoldenPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.workflow = yaml.safe_load(cls.workflow_text)
        cls.publish = cls.workflow["jobs"]["publish"]
        cls.steps = {step.get("name"): step for step in cls.publish["steps"]}
        cls.step_names = [step.get("name") for step in cls.publish["steps"]]

    def test_security_classification_selects_exact_self_hosted_runner_labels(self) -> None:
        classification = self.workflow["jobs"]["security-classification"]
        self.assertEqual("${{ steps.runner.outputs.labels }}", classification["outputs"]["publish-runner"])
        runner = next(step for step in classification["steps"] if step.get("id") == "runner")
        self.assertIn('["self-hosted","linux","x64","incus"]', runner["run"])
        self.assertIn('["ubuntu-latest"]', runner["run"])
        self.assertEqual(
            "${{ fromJSON(needs.security-classification.outputs.publish-runner) }}",
            self.publish["runs-on"],
        )

    def test_normal_release_keeps_the_existing_approval_environment(self) -> None:
        environment = self.publish["environment"]["name"]
        self.assertIn("'mlx90-security-publish'", environment)
        self.assertIn("'ansible-collections'", environment)
        self.assertIn("lightning-it-release-automation[bot]", self.publish["if"])

    def test_release_validation_wait_covers_complete_ci_budget(self) -> None:
        environment = self.workflow["env"]
        attempts = 7 * int(environment["RELEASE_VALIDATION_WINDOW_ATTEMPTS"]) + int(
            environment["RELEASE_VALIDATION_FINAL_ATTEMPTS"]
        )
        budget = attempts * int(environment["RELEASE_VALIDATION_POLL_SECONDS"]) // 60
        required = int(environment["RELEASE_VALIDATION_WORST_CASE_MINUTES"]) + int(
            environment["RELEASE_VALIDATION_QUEUE_ALLOWANCE_MINUTES"]
        )
        self.assertGreaterEqual(budget, required)
        jobs = self.workflow["jobs"]
        reusable = yaml.safe_load((WORKFLOW_PATH.parent / "release-validation-window.yml").read_text())
        self.assertLessEqual(reusable["jobs"]["window"]["timeout-minutes"], 90)
        wait = reusable["jobs"]["window"]["steps"][0]["run"]
        predecessor = "security-classification"
        for index in range(1, 9):
            job_name = (
                "release-validation"
                if index == 8
                else ("release-validation-window" if index == 1 else f"release-validation-window-{index}")
            )
            job = jobs[job_name]
            self.assertEqual(predecessor, job["needs"])
            self.assertEqual("./.github/workflows/release-validation-window.yml", job["uses"])
            self.assertEqual("${{ inputs.release_sha }}", job["with"]["release_sha"])
            self.assertEqual(140 if index == 8 else 160, job["with"]["attempts"])
            self.assertEqual(index == 8, job["with"]["final_window"])
            if index > 1:
                for binding, output in (
                    ("prior_run_id", "ci-run-id"),
                    ("prior_run_attempt", "ci-run-attempt"),
                    ("prior_complete", "complete"),
                ):
                    self.assertEqual(f"${{{{ needs.{predecessor}.outputs.{output} }}}}", job["with"][binding])
            predecessor = job_name
        for exact_identity in (
            '.event == "push"',
            '.head_branch == "main"',
            ".head_sha == $sha",
        ):
            self.assertIn(exact_identity, wait)
        self.assertIn(".run_attempt == $run_attempt", wait)
        self.assertIn('test "$conclusion" = success', wait)
        self.assertIn('test "$gate_count" -eq 1', wait)
        self.assertEqual(["security-classification", "release-validation"], self.publish["needs"])
        self.assertNotIn("Wait for exact-SHA main Release Validation", self.step_names)
        download = self.steps["Download exact candidate and evidence from validated run"]
        self.assertEqual("${{ needs.release-validation.outputs.ci-run-id }}", download["env"]["CI_RUN_ID"])
        self.assertEqual("${{ needs.release-validation.outputs.ci-run-attempt }}", download["env"]["CI_RUN_ATTEMPT"])
        self.assertEqual(2, download["run"].count("scripts/verify-release-ci-run.sh"))
        validate = self.steps["Validate candidate, MANIFEST, evidence, and repository policy"]
        self.assertEqual("${{ needs.release-validation.outputs.ci-run-id }}", validate["env"]["CI_RUN_ID"])
        self.assertEqual("${{ needs.release-validation.outputs.ci-run-attempt }}", validate["env"]["CI_RUN_ATTEMPT"])
        for evidence in ("evidence_manifest", "publication", "security_receipt"):
            self.assertIn(f'{evidence}.get("workflow_attempt")', validate["run"])
        for name in (
            "Revalidate exact CI producer before external staging",
            "Revalidate exact CI producer before release publication",
            "Revalidate exact CI producer before Galaxy publication",
        ):
            self.assertIn(
                'scripts/verify-release-ci-run.sh "$RELEASE_SHA" "$CI_RUN_ID" "$CI_RUN_ATTEMPT"',
                self.steps[name]["run"],
            )

    def test_release_validation_window_rejects_changed_identity_and_failed_gate(self) -> None:
        reusable = yaml.safe_load((WORKFLOW_PATH.parent / "release-validation-window.yml").read_text())
        wait = reusable["jobs"]["window"]["steps"][0]["run"]
        stub = """#!/usr/bin/env python3
import json
import os
import sys

case = os.environ["STUB_CASE"]
sha = "a" * 40
run = {
    "id": 123, "run_attempt": 2 if case == "changed-attempt" else 1,
    "event": "push", "head_branch": "main",
    "head_sha": "b" * 40 if case == "changed-sha" else sha,
    "status": "completed", "conclusion": "success",
}
path = next(arg for arg in sys.argv[1:] if arg.startswith("repos/"))
if path.endswith("/jobs"):
    gate = {
        "name": "Collection / Release Validation", "run_attempt": 1,
        "status": "completed", "conclusion": "failure" if case == "failed-gate" else "success",
    }
    result = [{"jobs": [gate]}]
elif path.endswith("/runs"):
    matches = [run, {**run, "id": 124}] if case in {"ambiguous", "late-duplicate"} else [run]
    result = {"total_count": len(matches), "workflow_runs": matches}
else:
    result = run
print(json.dumps(result))
"""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            gh = bin_dir / "gh"
            gh.write_text(stub, encoding="utf-8")
            gh.chmod(0o755)
            for case in ("success", "changed-attempt", "changed-sha", "failed-gate", "ambiguous", "late-duplicate"):
                with self.subTest(case=case):
                    output = root / f"{case}.output"
                    environment = {
                        **os.environ,
                        "PATH": f"{bin_dir}:{os.environ['PATH']}",
                        "STUB_CASE": case,
                        "GITHUB_REPOSITORY": "lightning-it/ansible-collection-supplementary",
                        "GITHUB_OUTPUT": str(output),
                        "GH_TOKEN": "fixture",
                        "RELEASE_SHA": "a" * 40,
                        "PRIOR_RUN_ID": "" if case == "ambiguous" else "123",
                        "PRIOR_RUN_ATTEMPT": "" if case == "ambiguous" else "1",
                        "PRIOR_COMPLETE": "false",
                        "ATTEMPTS": "1",
                        "FINAL_WINDOW": "true",
                    }
                    result = subprocess.run(  # noqa: S603 -- fixed checked-in workflow with a local gh stub.
                        ["/bin/bash", "-e", "-c", wait],
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if case == "success":
                        self.assertEqual(0, result.returncode, result.stderr)
                        self.assertIn("ci-run-id=123", output.read_text(encoding="utf-8"))
                        self.assertIn("ci-run-attempt=1", output.read_text(encoding="utf-8"))
                        self.assertIn("complete=true", output.read_text(encoding="utf-8"))
                    else:
                        self.assertNotEqual(0, result.returncode, result.stdout)
                        self.assertFalse(output.exists())
                    publisher_check = subprocess.run(  # noqa: S603 -- fixed checked-in verifier with a local gh stub.
                        ["/bin/bash", str(ROOT / "scripts/verify-release-ci-run.sh"), "a" * 40, "123", "1"],
                        env=environment,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if case == "success":
                        self.assertEqual(0, publisher_check.returncode, publisher_check.stderr)
                    else:
                        self.assertNotEqual(0, publisher_check.returncode, publisher_check.stdout)

    def test_security_order_is_nexus_then_signed_modulix_then_galaxy(self) -> None:
        nexus = self.step_names.index("Stage exact Security candidate in native Nexus Galaxy v3")
        receipt = self.step_names.index("Require signed successful ModuLix validation receipt")
        finalize = self.step_names.index("Finalize immutable release attachments and notes")
        galaxy = self.step_names.index("Publish or verify validated artifact on Ansible Galaxy")
        self.assertLess(nexus, receipt)
        self.assertLess(receipt, finalize)
        self.assertLess(finalize, galaxy)

        for name in (
            "Stage exact Security candidate in native Nexus Galaxy v3",
            "Mint read-only release automation installation audit token",
            "Verify exact release automation installation and allowlist",
            "Mint exact ModuLix validation App token",
            "Require signed successful ModuLix validation receipt",
        ):
            self.assertEqual(
                "env.SECURITY_RELEASE == 'true' && env.GALAXY_REQUIRED == 'true'",
                self.steps[name]["if"],
            )
        self.assertNotIn(
            'test "$GALAXY_REQUIRED" = true',
            self.steps["Stage exact Security candidate in native Nexus Galaxy v3"]["run"],
        )

    def test_nexus_stage_is_native_v3_readback_and_fails_without_configuration(self) -> None:
        stage = self.steps["Stage exact Security candidate in native Nexus Galaxy v3"]
        self.assertEqual("${{ vars.NEXUS_GALAXY_REPOSITORY_URL }}", stage["env"]["NEXUS_GALAXY_REPOSITORY_URL"])
        self.assertEqual("${{ vars.NEXUS_GALAXY_REPOSITORY }}", stage["env"]["NEXUS_GALAXY_REPOSITORY"])
        self.assertEqual("${{ secrets.NEXUS_GALAXY_USERNAME }}", stage["env"]["NEXUS_GALAXY_USERNAME"])
        self.assertEqual("${{ secrets.NEXUS_GALAXY_PASSWORD }}", stage["env"]["NEXUS_GALAXY_PASSWORD"])
        self.assertIn("scripts/nexus-galaxy-v3-stage.py", stage["run"])
        self.assertNotIn("set -x", stage["run"])

        script = (ROOT / "scripts" / "nexus-galaxy-v3-stage.py").read_text(encoding="utf-8")
        self.assertIn("/api/v3/plugin/ansible/content/published/collections/artifacts/", script)
        self.assertIn("Nexus readback bytes differ", script)
        self.assertNotIn("print(password", script)

    def test_staged_release_handoff_is_bound_before_modulix_dispatch(self) -> None:
        stage = self.step_names.index("Stage exact Security candidate in native Nexus Galaxy v3")
        handoff = self.step_names.index("Create exact staged-release handoff")
        upload = self.step_names.index("Upload bound staged release")
        receipt = self.step_names.index("Require signed successful ModuLix validation receipt")
        self.assertLess(stage, handoff)
        self.assertLess(handoff, upload)
        self.assertLess(upload, receipt)
        step = self.steps["Create exact staged-release handoff"]
        self.assertEqual("env.SECURITY_RELEASE == 'true' && env.GALAXY_REQUIRED == 'true'", step["if"])
        for field in ("$GITHUB_RUN_ID", "$GITHUB_RUN_ATTEMPT", "$CI_RUN_ID", "$CI_RUN_ATTEMPT", "$RELEASE_SHA"):
            self.assertIn(field, step["run"])
        self.assertIn("scripts/release-stage-handoff.py create", step["run"])
        artifact = self.steps["Upload bound staged release"]
        self.assertEqual(step["if"], artifact["if"])
        self.assertIn("release-stage-handoff.json", artifact["with"]["path"])
        self.assertIn("dist/", artifact["with"]["path"])
        self.assertIn("incoming/", artifact["with"]["path"])
        self.assertEqual("error", artifact["with"]["if-no-files-found"])
        self.assertEqual("${{ steps.release-handoff.outputs.sha256 }}", self.publish["outputs"]["handoff-sha256"])

    def test_modulix_dispatch_is_exact_app_scoped_and_receipt_gated(self) -> None:
        audit_token = self.steps["Mint read-only release automation installation audit token"]
        self.assertEqual("read", audit_token["with"]["permission-actions"])
        self.assertNotIn("repositories", audit_token["with"])
        audit = self.steps["Verify exact release automation installation and allowlist"]["run"]
        self.assertIn(".id == 148019054", audit)
        self.assertIn('"checks": "read"', audit)
        self.assertIn('"pull_requests": "write"', audit)
        self.assertIn("lightning-it/shared-assets-lit", audit)
        self.assertIn("lightning-it/modulix-validation", audit)
        token = self.steps["Mint exact ModuLix validation App token"]
        self.assertEqual("modulix-validation", token["with"]["repositories"])
        self.assertEqual("write", token["with"]["permission-actions"])
        self.assertEqual("read", token["with"]["permission-contents"])
        self.assertNotIn("permission-administration", token["with"])
        self.assertNotIn("permission-environments", token["with"])
        self.assertNotIn("permission-secrets", token["with"])

        gate = self.steps["Require signed successful ModuLix validation receipt"]["run"]
        self.assertIn('test "$APP_INSTALLATION_ID" = 148019054', gate)
        self.assertIn("scripts/modulix-validation-receipt.py", gate)
        self.assertIn('--source-run-attempt "$GITHUB_RUN_ATTEMPT"', gate)
        self.assertNotIn("set -x", gate)

    def test_security_path_binds_both_app_login_and_numeric_actor_id(self) -> None:
        self.assertIn("github.actor == 'lightning-it-release-automation[bot]'", self.publish["if"])
        self.assertIn("github.actor_id == '307565056'", self.publish["if"])
        self.assertIn("github.actor_id == '307565056'", self.publish["environment"]["name"])

    def test_galaxy_cannot_publish_security_candidate_without_exact_receipt(self) -> None:
        galaxy = self.steps["Publish or verify validated artifact on Ansible Galaxy"]["run"]
        receipt_check = galaxy.index("MODULIX_VALIDATION_RECEIPT_SHA256")
        publish = galaxy.index("ansible-galaxy collection publish")
        readback = galaxy.index("galaxy_download_url")
        self.assertLess(receipt_check, publish)
        self.assertLess(publish, readback)
        self.assertIn(".decision.galaxyPublicationAuthorized == true", galaxy)
        self.assertIn(".request.candidate.sha256 == $digest", galaxy)

    def test_transition_noop_and_galaxy_first_path_are_absent(self) -> None:
        self.assertNotIn("Dispatch transitional central validation", self.step_names)
        self.assertNotIn("scripts/dispatch-transition-validation.py", self.workflow_text)
        self.assertNotIn("transition-noop", self.workflow_text)


if __name__ == "__main__":
    unittest.main()
