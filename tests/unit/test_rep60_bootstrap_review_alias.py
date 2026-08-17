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
        self.assertIn("github.event.pull_request.user.login == 'litroc'", workflow)
        self.assertIn("agent/mlx90-exact-revision-codex-pilot-20260816", workflow)
        self.assertIn("github.event.pull_request.head.ref == 'develop'", workflow)
        self.assertIn(
            "types: [opened, synchronize, reopened, ready_for_review, edited]",
            workflow,
        )
        self.assertIn('test "${DEFAULT_BRANCH}" = develop', workflow)
        self.assertIn("branches/${DEFAULT_BRANCH}", workflow)
        self.assertIn('test "${WORKFLOW_SHA}" = "${EVENT_BASE}"', workflow)
        # pull_request_target is evaluated from the repository default branch.
        # For the only admitted main promotion, that protected default-branch
        # revision is also the exact develop PR head.
        self.assertIn('test "${WORKFLOW_SHA}" = "${EVENT_HEAD}"', workflow)
        self.assertIn(".merge_base_commit.sha == $base", workflow)

    def test_skipped_job_cannot_satisfy_required_alias(self) -> None:
        workflow = self.workflow
        self.assertIn("name: Publish protected bootstrap review alias", workflow)
        self.assertNotIn("name: Successful Copilot review\n    if:", workflow)
        self.assertIn("actions: read", workflow)
        self.assertIn("-f name='Successful Copilot review'", workflow)
        self.assertIn("checks: write", workflow)
        self.assertIn('external_id="rep60-bootstrap-alias:v2:${GITHUB_RUN_ID}:', workflow)

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
        self.assertIn("${GITHUB_SERVER_URL}/${REPOSITORY}/runs/${check_id}", workflow)
        self.assertNotIn('-f details_url="${check_url}"', workflow)

    def test_alias_rejects_competing_custom_checks(self) -> None:
        workflow = self.workflow
        self.assertIn("custom_aliases=", workflow)
        self.assertIn('select((.details_url // "") | startswith($prefix))', workflow)
        self.assertIn('test "$(jq \'length\' <<<"${custom_aliases}")" -eq 1', workflow)

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
        self.assertIn("conclusion=success", workflow)


if __name__ == "__main__":
    unittest.main()
