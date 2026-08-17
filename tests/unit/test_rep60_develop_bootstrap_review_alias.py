import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rep60-develop-bootstrap-review-alias.yml"


class Rep60DevelopBootstrapReviewAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_controller_is_base_owned_and_bounded_to_the_single_pr(self) -> None:
        workflow = self.workflow
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("branches: [develop]", workflow)
        self.assertIn("types: [labeled]", workflow)
        self.assertIn('[ "${PR_NUMBER}" != 759 ]', workflow)
        self.assertIn("agent/mlx90-exact-revision-codex-pilot-20260816", workflow)
        self.assertIn("fix(mlx90): enforce pipeline-only current-revision review", workflow)
        self.assertIn('[ "${EVENT_LABEL}" != ci ]', workflow)
        self.assertIn('test "${EVENT_BASE}" = "${WORKFLOW_SHA}"', workflow)

    def test_protected_run_and_live_pr_are_bound_before_and_after_review(self) -> None:
        workflow = self.workflow
        self.assertIn("actions/runs/${GITHUB_RUN_ID}", workflow)
        self.assertIn('.event == "pull_request_target"', workflow)
        self.assertIn('.name == "REP-60 protected develop bootstrap alias"', workflow)
        self.assertIn(".path == $path", workflow)
        self.assertIn(".actor.login == $actor", workflow)
        self.assertIn(".triggering_actor.login == $actor", workflow)
        self.assertIn("verify_pr_binding", workflow)
        self.assertEqual(2, workflow.count('verify_pr_binding "'))

    def test_only_a_real_current_head_copilot_review_can_publish(self) -> None:
        workflow = self.workflow
        self.assertIn(".commit_id == $head", workflow)
        self.assertIn("No acceptable Copilot review exists for exact head", workflow)
        self.assertIn("jq 'length'", workflow)
        self.assertIn("reviewThreads(first:100,after:$after)", workflow)
        self.assertIn("select(.isResolved == false)", workflow)
        self.assertIn('test "${unresolved}" -eq 0', workflow)
        self.assertIn("review_id", workflow)
        self.assertNotIn("openai/", workflow)
        self.assertNotIn("copilot-requests", workflow)

    def test_legacy_alias_is_a_deduplicated_custom_check(self) -> None:
        workflow = self.workflow
        self.assertIn("checks: write", workflow)
        self.assertIn("check_name='Successful Copilot review'", workflow)
        self.assertIn("rep60-develop-bootstrap:v1:", workflow)
        self.assertIn(".app.id == 15368", workflow)
        self.assertIn(".external_id == $external_id", workflow)
        self.assertIn("Multiple protected bootstrap checks", workflow)
        self.assertIn("producer_run_id", workflow)
        self.assertIn("producer_run_url", workflow)
        self.assertIn("workflow_sha", workflow)

    def test_controller_never_checks_out_or_executes_candidate_code(self) -> None:
        workflow = self.workflow.lower()
        self.assertNotIn("actions/checkout", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("workflow_dispatch", workflow)


if __name__ == "__main__":
    unittest.main()
