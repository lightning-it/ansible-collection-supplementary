from __future__ import annotations

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
        attempts = int(environment["RELEASE_VALIDATION_WINDOW_ONE_ATTEMPTS"]) + int(
            environment["RELEASE_VALIDATION_WINDOW_TWO_ATTEMPTS"]
        )
        budget = attempts * int(environment["RELEASE_VALIDATION_POLL_SECONDS"]) // 60
        required = int(environment["RELEASE_VALIDATION_WORST_CASE_MINUTES"]) + int(
            environment["RELEASE_VALIDATION_QUEUE_ALLOWANCE_MINUTES"]
        )
        self.assertGreaterEqual(budget, required)
        jobs = self.workflow["jobs"]
        self.assertLessEqual(jobs["release-validation-window"]["timeout-minutes"], 360)
        self.assertLessEqual(jobs["release-validation"]["timeout-minutes"], 360)
        final_wait = jobs["release-validation"]["steps"][0]["run"]
        self.assertIn('test "$EARLY_RUN_ID" = "$run_id"', final_wait)
        self.assertIn('test "$conclusion" = success', final_wait)
        self.assertIn('test "$gate_count" -eq 1', final_wait)
        self.assertEqual(["security-classification", "release-validation"], self.publish["needs"])
        self.assertNotIn("Wait for exact-SHA main Release Validation", self.step_names)
        download = self.steps["Download exact candidate and evidence from validated run"]
        self.assertEqual("${{ needs.release-validation.outputs.ci-run-id }}", download["env"]["CI_RUN_ID"])

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
