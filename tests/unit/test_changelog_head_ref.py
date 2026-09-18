"""Executable regression tests for detached release-head recovery."""

from __future__ import annotations

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


class ChangelogHeadRefTests(unittest.TestCase):
    def test_changelog_policy_uses_the_tested_resolver(self) -> None:
        policy = (ROOT / "scripts" / "devtools-changelog-check.sh").read_text(encoding="utf-8")
        self.assertIn(
            'head_ref="$(bash scripts/resolve-changelog-head-ref.sh "$head_ref")"',
            policy,
        )

    def git(self, repository: Path, *arguments: str) -> str:
        result = subprocess.run(  # noqa: S603 - fixed executable and test-owned arguments
            [GIT, *arguments],
            cwd=repository,
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

    def test_github_backsync_merge_subject_remains_supported(self) -> None:
        repository, _base, _candidate = self.synthetic_repository(
            "Merge pull request #991 from lightning-it/backsync/release-v3.3.0-to-develop"
        )
        self.assertEqual("backsync/release-v3.3.0-to-develop", self.resolve(repository))

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
