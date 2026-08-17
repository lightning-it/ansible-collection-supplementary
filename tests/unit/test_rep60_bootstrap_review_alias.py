import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rep60-bootstrap-protected-review-alias.yml"


class Rep60BootstrapReviewAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_alias_is_protected_and_narrowly_scoped(self) -> None:
        workflow = self.workflow
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("branches: [main]", workflow)
        self.assertIn(
            "types: [opened, synchronize, reopened, ready_for_review, edited]",
            workflow,
        )
        self.assertIn('test "${DEFAULT_BRANCH}" = develop', workflow)
        self.assertIn("branches/${DEFAULT_BRANCH}", workflow)
        # pull_request_target is evaluated from the repository default branch.
        # For the only admitted main promotion, that protected default-branch
        # revision is also the exact develop PR head.
        self.assertIn('test "${WORKFLOW_SHA}" = "${EVENT_HEAD}"', workflow)
        self.assertIn(".merge_base_commit.sha == $base", workflow)

    def test_skipped_job_cannot_satisfy_required_alias(self) -> None:
        workflow = self.workflow
        self.assertIn("name: Successful Copilot review", workflow)
        self.assertNotIn("    if:", workflow)
        self.assertIn("actions: read", workflow)
        self.assertNotIn("checks: write", workflow)
        self.assertNotIn("check-runs", workflow)

    def test_alias_is_bound_to_the_current_protected_run(self) -> None:
        workflow = self.workflow
        self.assertIn("actions/runs/${GITHUB_RUN_ID}", workflow)
        self.assertIn("repos/${REPOSITORY}/actions/runs/${GITHUB_RUN_ID}", workflow)
        self.assertIn('.event == "pull_request_target"', workflow)
        self.assertIn('.name == "REP-60 protected bootstrap review alias"', workflow)
        self.assertIn(
            '.path == ".github/workflows/rep60-bootstrap-protected-review-alias.yml"',
            workflow,
        )
        self.assertIn(".head_sha == $sha", workflow)
        self.assertIn(".run_attempt == $attempt", workflow)
        self.assertNotIn('test "${GITHUB_RUN_ATTEMPT}" -le', workflow)

    def test_alias_is_a_native_protected_job_not_a_custom_check(self) -> None:
        workflow = self.workflow
        self.assertNotIn("custom_aliases=", workflow)
        self.assertNotIn("external_id=", workflow)
        self.assertNotIn("--method POST", workflow)
        self.assertIn('test "${EVENT_BASE_REF}" = main', workflow)
        self.assertIn('test "${EVENT_HEAD_REF}" = develop', workflow)

    def test_alias_never_runs_candidate_code_or_ai(self) -> None:
        workflow = self.workflow.lower()
        self.assertNotIn("actions/checkout", workflow)
        self.assertNotIn("openai/", workflow)
        self.assertNotIn("copilot-requests", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("contents: write", workflow)

    def test_current_head_review_and_post_binding_are_required(self) -> None:
        workflow = self.workflow
        self.assertIn(".commit_id == $head", workflow)
        self.assertIn("reviewThreads(first:100,after:$after)", workflow)
        self.assertIn("select(.isResolved == false)", workflow)
        self.assertIn('test "${unresolved}" -eq 0', workflow)
        self.assertIn("post_pr=", workflow)
        self.assertIn(".head.sha == $head", workflow)
        self.assertIn("Protected bootstrap alias accepted exact head", workflow)


if __name__ == "__main__":
    unittest.main()
