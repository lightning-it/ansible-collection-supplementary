import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rep60-bootstrap-app-rearm.yml"


class Rep60BootstrapAppRearmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_controller_is_temporary_manual_and_protected_develop_owned(self) -> None:
        workflow = self.workflow
        self.assertIn("Temporary REP-60 bootstrap controller", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("github.ref == 'refs/heads/develop'", workflow)
        self.assertIn("github.actor == 'litroc'", workflow)
        self.assertIn("github.triggering_actor == 'litroc'", workflow)
        self.assertIn("environment: ansible-collection-runtime-protected", workflow)
        self.assertNotIn("environment: ansible-collection-release-prepare", workflow)
        self.assertIn('test "${GITHUB_SHA}" = "${EXPECTED_HEAD}"', workflow)
        self.assertIn(".path == $workflow", workflow)
        self.assertIn('.head_branch == "develop"', workflow)
        self.assertIn(".head_sha == $head", workflow)
        self.assertIn(".actor.login == $actor", workflow)
        self.assertIn(".triggering_actor.login == $actor", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertNotIn("actions/checkout", workflow)

    def test_app_token_is_repo_scoped_and_only_rearms_the_exact_pr(self) -> None:
        workflow = self.workflow
        self.assertIn("actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1", workflow)
        self.assertIn("repositories: ${{ github.event.repository.name }}", workflow)
        self.assertIn("permission-contents: read", workflow)
        self.assertIn("permission-pull-requests: write", workflow)
        self.assertNotIn("pull-requests: read", workflow)
        self.assertIn("readonly pr_number=777", workflow)
        self.assertIn("readonly expected_base=01afb46890e6d7ac6008e8ed478aa6af91e1b19b", workflow)
        self.assertIn("readonly expected_author='lightning-it-release-automation[bot]'", workflow)
        self.assertEqual(3, workflow.count("verify_pr_binding "))
        self.assertLess(workflow.index("-f state=closed"), workflow.index("-f state=open"))

    def test_rearm_is_fail_closed_and_deduplicated(self) -> None:
        workflow = self.workflow
        self.assertIn("git/ref/heads/develop", workflow)
        self.assertIn("commits/${EXPECTED_HEAD}/check-runs?per_page=100", workflow)
        self.assertIn(".app.id == 15368", workflow)
        self.assertIn('.name == "Current revision review"', workflow)
        self.assertIn('.name == "Protected current-revision verifier"', workflow)
        self.assertIn("endswith($suffix)", workflow)
        self.assertIn("already has a current-head REP-60 controller result", workflow)
        self.assertIn("verify_pr_binding open", workflow)
        self.assertIn("verify_pr_binding closed", workflow)
        self.assertNotIn("continue-on-error", workflow)

    def test_controller_has_no_ai_or_candidate_execution_path(self) -> None:
        workflow = self.workflow.lower()
        self.assertNotIn("openai/", workflow)
        self.assertNotIn("copilot", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("--admin", workflow)
        self.assertNotIn("gh pr merge", workflow)


if __name__ == "__main__":
    unittest.main()
