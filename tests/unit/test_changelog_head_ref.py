"""Executable regression tests for detached release-head recovery."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "resolve-changelog-head-ref.sh"
GIT = shutil.which("git")
BASH = shutil.which("bash")
if GIT is None or BASH is None:
    raise RuntimeError("git and bash are required for changelog-head-ref tests")


def isolated_git_environment() -> dict[str, str]:
    """Detach temporary repositories from a linked-worktree controller environment."""
    environment = os.environ.copy()
    for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        environment.pop(variable, None)
    return environment


class ChangelogHeadRefTests(unittest.TestCase):
    def test_synthetic_integration_uses_the_checked_out_head_tree(self) -> None:
        resolver = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('integration_tree="$(git rev-parse "HEAD^{tree}")"', resolver)
        self.assertNotIn(
            'integration_tree="$(git rev-parse "${integration_commit[0]}^{tree}")"',
            resolver,
        )

    def test_changelog_policy_uses_the_tested_resolver(self) -> None:
        policy = (ROOT / "scripts" / "devtools-changelog-check.sh").read_text(encoding="utf-8")
        self.assertIn(
            'head_ref="$(bash scripts/resolve-changelog-head-ref.sh "$head_ref")"',
            policy,
        )

    def test_release_pr_changelog_policy_requires_same_repo_release_app_identity(self) -> None:
        policy = (ROOT / "scripts" / "devtools-changelog-check.sh").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "wunder-devtools-ee.sh").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "collection-ci.yml").read_text(encoding="utf-8")
        changelog_workflow = (ROOT / ".github" / "workflows" / "changelog.yml").read_text(encoding="utf-8")

        self.assertIn('case "${GITHUB_EVENT_NAME:-}" in', policy)
        self.assertIn('[ "${GITHUB_HEAD_REPOSITORY:-}" = "${GITHUB_REPOSITORY:-}" ]', policy)
        self.assertIn('release_pr_author="${GITHUB_PR_AUTHOR:-${PR_AUTHOR:-}}"', policy)
        self.assertIn('[ "$release_pr_author" = "lightning-it-release-automation[bot]" ]', policy)
        self.assertIn("is_trusted_release_branch", policy)
        self.assertIn("A release-shaped branch name alone grants no privilege.", policy)
        self.assertIn('[[ "$head_ref" == release/v* ]] && [ "$base_ref" = main ]', policy)
        self.assertIn('[[ "$head_ref" == backsync/release-* ]] && [ "$base_ref" = develop ]', policy)
        self.assertLess(
            policy.index('if grep -E "$generated_re"'),
            policy.index("if has_label skip-changelog"),
        )
        for variable in (
            "GITHUB_EVENT_NAME",
            "GITHUB_REPOSITORY",
            "GITHUB_HEAD_REPOSITORY",
            "GITHUB_PR_AUTHOR",
            "PR_AUTHOR",
        ):
            with self.subTest(variable=variable):
                self.assertIn(f"${{{variable}:+-e {variable}}}", runner)
        self.assertIn("github.event.pull_request.head.repo.full_name", workflow)
        self.assertIn("github.event.pull_request.user.login", workflow)
        self.assertIn("steps.release-push.outputs.head_repository || ''", workflow)
        self.assertIn("steps.release-push.outputs.author || ''", workflow)
        self.assertIn(
            "GITHUB_HEAD_REPOSITORY: ${{ github.event.pull_request.head.repo.full_name }}", changelog_workflow
        )
        self.assertIn("GITHUB_PR_AUTHOR: ${{ github.event.pull_request.user.login }}", changelog_workflow)

        self.assertIn("Bind a release push to its unique merged Release App PR", workflow)
        self.assertIn('"repos/${GITHUB_REPOSITORY}/commits/${SOURCE_SHA}/pulls"', workflow)
        self.assertIn("--paginate", workflow)
        self.assertIn("--slurp", workflow)
        self.assertIn(".[][]", workflow)
        self.assertIn("github.event_name == 'push' && github.ref_name", workflow)
        for exact_binding in (
            ".merge_commit_sha == $merge",
            ".base.ref == $base",
            ".head.ref == $head_ref",
            ".head.sha == $head",
            ".head.repo.full_name == $repo",
            ".user.login == $author",
        ):
            with self.subTest(exact_binding=exact_binding):
                self.assertIn(exact_binding, workflow)

    def test_generated_changelog_authorization_matrix_is_enforced_behaviorally(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repository = Path(temporary.name)
        scripts = repository / "scripts"
        scripts.mkdir()
        shutil.copy2(ROOT / "scripts" / "devtools-changelog-check.sh", scripts)
        shutil.copy2(ROOT / "scripts" / "resolve-changelog-head-ref.sh", scripts)
        (scripts / "wunder-devtools-ee.sh").write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n"
            'test "$1" = bash\ntest "$2" = -lc\n'
            "body=${3//\\/workspace/$PWD}\n"
            "body=${body//antsibull-changelog lint/true}\n"
            'exec bash -c "$body"\n',
            encoding="utf-8",
        )
        (repository / "changelogs").mkdir()
        (repository / "changelogs" / "changelog.yaml").write_text("releases: {}\n", encoding="utf-8")
        self.git(repository, "init", "--quiet")
        self.git(repository, "config", "user.name", "LI test")
        self.git(repository, "config", "user.email", "li-test@invalid")
        self.git(repository, "add", ".")
        self.git(repository, "commit", "--quiet", "-m", "base")
        base = self.git(repository, "rev-parse", "HEAD")
        (repository / "changelogs" / "changelog.yaml").write_text(
            "releases:\n  3.3.1:\n    changes: []\n", encoding="utf-8"
        )
        self.git(repository, "commit", "--quiet", "-am", "generated changelog")
        head = self.git(repository, "rev-parse", "HEAD")

        def policy_result(
            *,
            head_ref: str,
            base_ref: str,
            head_repository: str = "lightning-it/ansible-collection-supplementary",
            labels: str = "[]",
            event_name: str = "pull_request",
            ref_name: str = "",
            compare_base: str = base,
            compare_head: str = head,
        ) -> subprocess.CompletedProcess[str]:
            environment = isolated_git_environment()
            environment.update(
                {
                    "BASE_SHA": compare_base,
                    "HEAD_SHA": compare_head,
                    "GITHUB_EVENT_NAME": event_name,
                    "GITHUB_REPOSITORY": "lightning-it/ansible-collection-supplementary",
                    "GITHUB_HEAD_REPOSITORY": head_repository,
                    "GITHUB_HEAD_REF": head_ref,
                    "GITHUB_BASE_REF": base_ref,
                    "GITHUB_REF_NAME": ref_name,
                    "GITHUB_PR_AUTHOR": "lightning-it-release-automation[bot]",
                    "LABELS_JSON": labels,
                    "HOME": str(repository),
                }
            )
            return subprocess.run(  # noqa: S603 - fixed shell and repository-owned script
                [BASH, "scripts/devtools-changelog-check.sh"],
                cwd=repository,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(0, policy_result(head_ref="release/v3.3.1", base_ref="main").returncode)
        self.assertEqual(
            0,
            policy_result(head_ref="backsync/release-v3.3.1-to-develop", base_ref="develop").returncode,
        )
        self.assertNotEqual(0, policy_result(head_ref="release/v3.3.1", base_ref="develop").returncode)
        self.assertNotEqual(
            0,
            policy_result(head_ref="backsync/release-v3.3.1-to-develop", base_ref="main").returncode,
        )
        self.assertNotEqual(
            0,
            policy_result(head_ref="release/v3.3.1", base_ref="main", head_repository="fork/repository").returncode,
        )
        self.assertNotEqual(
            0,
            policy_result(head_ref="release/v3.3.1", base_ref="main", head_repository="").returncode,
        )
        self.assertNotEqual(
            0,
            policy_result(head_ref="release/v3.3.1", base_ref="develop", labels='["skip-changelog"]').returncode,
        )
        self.assertEqual(0, policy_result(head_ref="develop", base_ref="main").returncode)
        self.assertNotEqual(
            0,
            policy_result(head_ref="develop", base_ref="main", head_repository="fork/repository").returncode,
        )
        self.assertNotEqual(
            0,
            policy_result(head_ref="develop", base_ref="main", head_repository="").returncode,
        )
        for unsupported_event in ("workflow_dispatch", "schedule"):
            with self.subTest(event=unsupported_event):
                self.assertNotEqual(
                    0,
                    policy_result(
                        head_ref="release/v3.3.1",
                        base_ref="main",
                        event_name=unsupported_event,
                    ).returncode,
                )
                self.assertNotEqual(
                    0,
                    policy_result(
                        head_ref="develop",
                        base_ref="main",
                        event_name=unsupported_event,
                    ).returncode,
                )

        (repository / "changelogs" / "release-preparation.json").write_text(
            '{"next_version":"3.3.1"}\n', encoding="utf-8"
        )
        self.git(repository, "add", "changelogs/release-preparation.json")
        self.git(repository, "commit", "--quiet", "-m", "correct release preparation receipt")
        receipt_head = self.git(repository, "rev-parse", "HEAD")
        self.assertEqual(
            0,
            policy_result(
                head_ref="fix/release-receipt",
                base_ref="develop",
                compare_base=head,
                compare_head=receipt_head,
            ).returncode,
        )
        self.assertEqual(
            0,
            policy_result(
                head_ref="",
                base_ref="",
                event_name="push",
                ref_name="develop",
                compare_base=head,
                compare_head=receipt_head,
            ).returncode,
        )

        candidate_tree = self.git(repository, "rev-parse", f"{head}^{{tree}}")
        release_merge = self.git(
            repository,
            "commit-tree",
            candidate_tree,
            "-p",
            base,
            "-p",
            head,
            "-m",
            "Merge pull request #1001 from lightning-it/release/v3.3.1",
        )
        backsync_merge = self.git(
            repository,
            "commit-tree",
            candidate_tree,
            "-p",
            base,
            "-p",
            head,
            "-m",
            "Merge pull request #1002 from lightning-it/backsync/release-v3.3.1-to-develop",
        )
        promotion_merge = self.git(
            repository,
            "commit-tree",
            candidate_tree,
            "-p",
            base,
            "-p",
            head,
            "-m",
            "chore(release): promote develop to main (#1003)",
        )
        self.git(repository, "update-ref", "refs/remotes/origin/develop", head)

        for merge_commit, canonical_target, wrong_target in (
            (release_merge, "main", "develop"),
            (backsync_merge, "develop", "main"),
            (promotion_merge, "main", "develop"),
        ):
            with self.subTest(merge_commit=merge_commit, target=canonical_target):
                self.git(repository, "checkout", "--quiet", "--detach", merge_commit)
                self.assertEqual(
                    0,
                    policy_result(
                        head_ref="",
                        base_ref="",
                        event_name="push",
                        ref_name=canonical_target,
                        compare_head=merge_commit,
                    ).returncode,
                )
                self.assertNotEqual(
                    0,
                    policy_result(
                        head_ref="",
                        base_ref="",
                        event_name="push",
                        ref_name=wrong_target,
                        compare_head=merge_commit,
                    ).returncode,
                )

        policy = (ROOT / "scripts" / "devtools-changelog-check.sh").read_text(encoding="utf-8")
        self.assertIn('export GITHUB_BASE_REF="${GITHUB_REF_NAME:-}"', policy)

    def git(self, repository: Path, *arguments: str) -> str:
        result = subprocess.run(  # noqa: S603 - fixed executable and test-owned arguments
            [GIT, *arguments],
            cwd=repository,
            env=isolated_git_environment(),
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def synthetic_repository(
        self,
        subject: str = "Synthetic pull-request integration",
        *,
        matching_tree: bool = True,
    ) -> tuple[Path, str, str]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repository = Path(temporary.name)
        self.git(repository, "init", "--quiet")
        self.git(repository, "config", "user.name", "LI test")
        self.git(repository, "config", "user.email", "li-test@invalid")
        (repository / "fixture.txt").write_text("base\n", encoding="utf-8")
        self.git(repository, "add", "fixture.txt")
        self.git(repository, "commit", "--quiet", "-m", "base")
        base = self.git(repository, "rev-parse", "HEAD")
        (repository / "fixture.txt").write_text("candidate\n", encoding="utf-8")
        self.git(repository, "commit", "--quiet", "-am", "candidate")
        candidate = self.git(repository, "rev-parse", "HEAD")
        if matching_tree:
            tree = self.git(repository, "rev-parse", f"{candidate}^{{tree}}")
        else:
            (repository / "fixture.txt").write_text("integration-only\n", encoding="utf-8")
            self.git(repository, "add", "fixture.txt")
            tree = self.git(repository, "write-tree")
            self.git(repository, "reset", "--quiet", "--hard", candidate)
        integration = self.git(
            repository,
            "commit-tree",
            tree,
            "-p",
            base,
            "-p",
            candidate,
            "-m",
            subject,
        )
        self.git(repository, "checkout", "--quiet", "--detach", integration)
        return repository, base, candidate

    def resolve(self, repository: Path, value: str = "HEAD") -> str:
        result = subprocess.run(  # noqa: S603 - fixed executable and test-owned arguments
            [BASH, str(SCRIPT), value],
            cwd=repository,
            env=isolated_git_environment(),
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_exact_candidate_release_ref_is_recovered(self) -> None:
        repository, _base, candidate = self.synthetic_repository()
        self.git(repository, "branch", "backsync/release-v3.3.0-to-develop", candidate)
        self.assertEqual("backsync/release-v3.3.0-to-develop", self.resolve(repository))

    def test_exact_local_release_ref_is_recovered(self) -> None:
        repository, _base, candidate = self.synthetic_repository()
        self.git(repository, "branch", "release/v3.3.0", candidate)
        self.assertEqual("release/v3.3.0", self.resolve(repository))

    def test_missing_release_ref_remains_detached(self) -> None:
        repository, _base, _candidate = self.synthetic_repository()
        self.assertEqual("HEAD", self.resolve(repository))

    def test_remote_tracking_release_ref_remains_detached(self) -> None:
        repository, _base, candidate = self.synthetic_repository()
        self.git(repository, "update-ref", "refs/remotes/origin/release/v3.3.0", candidate)
        self.assertEqual("HEAD", self.resolve(repository))

    def test_mismatched_synthetic_tree_remains_detached(self) -> None:
        repository, _base, candidate = self.synthetic_repository(matching_tree=False)
        self.git(repository, "branch", "backsync/release-v3.3.0-to-develop", candidate)
        self.assertEqual("HEAD", self.resolve(repository))

    def test_multiple_candidate_release_refs_remain_detached(self) -> None:
        repository, _base, candidate = self.synthetic_repository()
        self.git(repository, "branch", "release/v3.3.0", candidate)
        self.git(repository, "branch", "backsync/release-v3.3.0-to-develop", candidate)
        self.assertEqual("HEAD", self.resolve(repository))

    def test_release_ref_on_base_parent_is_not_accepted(self) -> None:
        repository, base, _candidate = self.synthetic_repository()
        self.git(repository, "branch", "release/v3.3.0", base)
        self.assertEqual("HEAD", self.resolve(repository))

    def test_github_merge_subject_remains_supported(self) -> None:
        repository, _base, _candidate = self.synthetic_repository(
            "Merge pull request #990 from lightning-it/release/v3.3.0"
        )
        self.assertEqual("release/v3.3.0", self.resolve(repository))

    def test_single_parent_with_github_release_merge_subject_remains_detached(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repository = Path(temporary.name)
        self.git(repository, "init", "--quiet")
        self.git(repository, "config", "user.name", "LI test")
        self.git(repository, "config", "user.email", "li-test@invalid")
        (repository / "fixture.txt").write_text("crafted\n", encoding="utf-8")
        self.git(repository, "add", "fixture.txt")
        self.git(
            repository,
            "commit",
            "--quiet",
            "-m",
            "Merge pull request #990 from lightning-it/release/v3.3.0",
        )
        self.assertEqual("HEAD", self.resolve(repository))

    def test_github_release_merge_with_mismatched_tree_remains_detached(self) -> None:
        repository, _base, _candidate = self.synthetic_repository(
            "Merge pull request #990 from lightning-it/release/v3.3.0",
            matching_tree=False,
        )
        self.assertEqual("HEAD", self.resolve(repository))

    def test_github_backsync_merge_subject_remains_supported(self) -> None:
        repository, _base, _candidate = self.synthetic_repository(
            "Merge pull request #991 from lightning-it/backsync/release-v3.3.0-to-develop"
        )
        self.assertEqual("backsync/release-v3.3.0-to-develop", self.resolve(repository))

    def test_exact_remote_develop_parent_and_tree_recovers_promotion(self) -> None:
        repository, base, candidate = self.synthetic_repository("chore(release): promote develop to main (#1003)")
        self.git(repository, "update-ref", "refs/remotes/origin/develop", candidate)
        self.assertEqual("develop", self.resolve(repository))

        self.git(repository, "update-ref", "refs/remotes/origin/develop", base)
        self.assertEqual("HEAD", self.resolve(repository))

    def test_malformed_github_release_merge_subject_remains_detached(self) -> None:
        repository, _base, _candidate = self.synthetic_repository(
            "Merge pull request #992 from lightning-it/release/v3.3"
        )
        self.assertEqual("HEAD", self.resolve(repository))

    def test_malformed_github_backsync_merge_subject_remains_detached(self) -> None:
        repository, _base, _candidate = self.synthetic_repository(
            "Merge pull request #993 from lightning-it/backsync/release-v3.3.0"
        )
        self.assertEqual("HEAD", self.resolve(repository))

    def test_malformed_local_candidate_ref_remains_detached(self) -> None:
        repository, _base, candidate = self.synthetic_repository()
        self.git(repository, "branch", "release/v03.3.0", candidate)
        self.assertEqual("HEAD", self.resolve(repository))

    def test_exact_direct_release_ref_is_accepted(self) -> None:
        repository, _base, _candidate = self.synthetic_repository()
        self.assertEqual("release/v3.3.0", self.resolve(repository, "release/v3.3.0"))

    def test_noncanonical_direct_release_ref_is_rejected(self) -> None:
        repository, _base, _candidate = self.synthetic_repository()
        with self.assertRaises(subprocess.CalledProcessError):
            self.resolve(repository, "release/v03.3.0")

    def test_noncanonical_direct_backsync_ref_is_rejected(self) -> None:
        repository, _base, _candidate = self.synthetic_repository()
        with self.assertRaises(subprocess.CalledProcessError):
            self.resolve(repository, "backsync/release-v3.3-to-develop")

    def test_attached_head_is_unchanged(self) -> None:
        repository, _base, _candidate = self.synthetic_repository()
        self.assertEqual("feature/example", self.resolve(repository, "feature/example"))


if __name__ == "__main__":
    unittest.main()
