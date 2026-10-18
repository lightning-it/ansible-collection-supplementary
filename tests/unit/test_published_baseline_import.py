"""Published bytes may be imported by an ordinary reviewed human PR, never an App exemption."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("published_baseline_import", ROOT / "scripts/verify_release_back_sync.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
APP_NAME = "lightning-it-release-automation[bot]"
APP_EMAIL = "307565056+lightning-it-release-automation[bot]@users.noreply.github.com"
BRANCH = "reconcile/release-v3.2.4-to-develop"


def git(root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        environment.pop(variable, None)
    return subprocess.run(  # noqa: S603 -- fixed Git and test-owned revisions.
        [shutil.which("git") or "/usr/bin/git", *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    ).stdout.strip()


class PublishedBaselineImportTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Human")
        git(self.root, "config", "user.email", "human@example.invalid")
        (self.root / "changelogs/fragments").mkdir(parents=True)
        (self.root / "galaxy.yml").write_text("version: 3.2.3\n", encoding="utf-8")
        for path in MODULE.GENERATED_PATHS - {"galaxy.yml"}:
            (self.root / path).write_text("{}\n", encoding="utf-8")
        self.consumed = "changelogs/fragments/consumed.yml"
        (self.root / self.consumed).write_text("bugfixes: [Published fix]\n", encoding="utf-8")
        scripts = self.root / "scripts"
        scripts.mkdir()
        for name in ("verify_release_back_sync.py", "devtools-changelog-check.sh", "resolve-changelog-head-ref.sh"):
            shutil.copy2(ROOT / "scripts" / name, scripts)
        (scripts / "wunder-devtools-ee.sh").write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\ntest "$1" = bash\ntest "$2" = -lc\n'
            'body=${3//\\/workspace/$PWD}\nbody=${body//antsibull-changelog lint/true}\nexec bash -c "$body"\n',
            encoding="utf-8",
        )
        self.commit("base")
        self.base = git(self.root, "rev-parse", "HEAD")
        self.receipt = {
            "schema_version": 2,
            "repository": MODULE.REPOSITORY,
            "repository_id": "1103407173",
            "base_sha": self.base,
            "current_version": "3.2.3",
            "next_version": "3.2.4",
            "release_mode": "normal",
            "security": None,
            "chain_id": None,
            "preparer": {"login": APP_NAME, "account_id": "307565056", "email": APP_EMAIL},
            "workflow": {
                "event": "push",
                "git_ref": "refs/heads/main",
                "run_attempt": "1",
                "run_id": "123",
                "path": ".github/workflows/release-prepare.yml",
                "source_sha": self.base,
                "ref": f"{MODULE.REPOSITORY}/.github/workflows/release-prepare.yml@refs/heads/main",
            },
            "fragments": [
                {"path": "consumed.yml", "sha256": hashlib.sha256((self.root / self.consumed).read_bytes()).hexdigest()}
            ],
        }
        git(self.root, "switch", "-q", "-c", "develop-fixture")
        self.unconsumed = "changelogs/fragments/unconsumed.yml"
        (self.root / self.unconsumed).write_text("bugfixes: [Unreleased fix]\n", encoding="utf-8")
        self.commit("new Develop work")
        self.develop = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/develop", self.develop)
        self.make_release()

    def commit(self, message: str) -> None:
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)

    def make_release(self, *, raw_receipt: str | None = None) -> None:
        git(self.root, "checkout", "-q", "--detach", self.base)
        git(self.root, "config", "user.name", APP_NAME)
        git(self.root, "config", "user.email", APP_EMAIL)
        for path in MODULE.GENERATED_PATHS:
            content = "version: 3.2.4\n" if path == "galaxy.yml" else "published 3.2.4\n"
            if path == "changelogs/release-preparation.json":
                content = raw_receipt if raw_receipt is not None else json.dumps(self.receipt)
            (self.root / path).write_text(content, encoding="utf-8")
        (self.root / self.consumed).unlink()
        self.commit("chore(release): prepare v3.2.4")
        preparation = git(self.root, "rev-parse", "HEAD")
        git(self.root, "checkout", "-q", "--detach", self.base)
        git(self.root, "merge", "-q", "--no-ff", preparation, "-m", "Release v3.2.4")
        self.main = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/main", self.main)
        git(self.root, "tag", "-f", "v3.2.4", self.main)
        git(self.root, "checkout", "-q", "--detach", self.develop)
        git(self.root, "config", "user.name", "Human")
        git(self.root, "config", "user.email", "human@example.invalid")
        git(self.root, "merge", "-q", "--no-ff", self.main, "-m", "Import already published baseline")
        # A real code correction can accompany the release import. It is not App-reviewed.
        (self.root / "scripts/ordinary-correction.py").write_text(
            "# Ordinary code review required.\n", encoding="utf-8"
        )
        (self.root / "changelogs/fragments/import-guard.yml").write_text("bugfixes: [Import guard]\n", encoding="utf-8")
        self.commit("Preserve ordinary reviewed code changes")
        self.head = git(self.root, "rev-parse", "HEAD")
        git(self.root, "branch", "-f", BRANCH, self.head)

    def verify(self, *, check_worktree: bool = False, merged_push: bool = False) -> None:
        MODULE.verify_published_baseline_import(
            root=self.root,
            develop_tip=self.develop,
            release_sha=self.main,
            head_sha=self.head,
            tag="v3.2.4",
            branch=BRANCH,
            check_worktree=check_worktree,
            merged_push=merged_push,
        )

    def test_real_published_bytes_and_ordinary_code_are_accepted_without_app_exemption(self) -> None:
        self.verify(check_worktree=True)
        with self.assertRaises(MODULE.BackSyncError):
            MODULE.verify(
                root=self.root, develop_tip=self.develop, release_sha=self.main, head_sha=self.head, tag="v3.2.4"
            )

    def test_missing_or_wrong_tag_and_wrong_protected_main_are_rejected(self) -> None:
        git(self.root, "tag", "-d", "v3.2.4")
        with self.assertRaises(MODULE.BackSyncError):
            self.verify()
        git(self.root, "tag", "v3.2.4", self.base)
        with self.assertRaisesRegex(MODULE.BackSyncError, "ref mismatch"):
            self.verify()
        git(self.root, "tag", "-f", "v3.2.4", self.main)
        git(self.root, "update-ref", "refs/remotes/origin/main", self.base)
        with self.assertRaisesRegex(MODULE.BackSyncError, "ref mismatch"):
            self.verify()

    def test_version_rollback_and_equal_develop_version_are_rejected(self) -> None:
        for version in ("3.2.4", "3.2.5"):
            with self.subTest(version=version):
                git(self.root, "checkout", "-q", "--detach", self.develop)
                (self.root / "galaxy.yml").write_text(f"version: {version}\n", encoding="utf-8")
                self.commit("Develop version")
                current = git(self.root, "rev-parse", "HEAD")
                git(self.root, "update-ref", "refs/remotes/origin/develop", current)
                with self.assertRaisesRegex(MODULE.BackSyncError, "must advance"):
                    MODULE.verify_published_baseline_import(
                        root=self.root,
                        develop_tip=current,
                        release_sha=self.main,
                        head_sha=self.head,
                        tag="v3.2.4",
                        branch=BRANCH,
                    )

    def test_each_release_file_blob_and_mode_are_bound(self) -> None:
        original = self.head
        for path in sorted(MODULE.GENERATED_PATHS):
            for mode in ("content", "executable", "symlink"):
                with self.subTest(path=path, mode=mode):
                    git(self.root, "reset", "-q", "--hard", original)
                    local = self.root / path
                    if mode == "content":
                        local.write_text("arbitrary edit\n", encoding="utf-8")
                    elif mode == "executable":
                        local.chmod(0o755)
                    else:
                        local.unlink()
                        local.symlink_to("/dev/null")
                    self.commit("Tamper release path")
                    self.head = git(self.root, "rev-parse", "HEAD")
                    with self.assertRaises(MODULE.BackSyncError):
                        self.verify()

    def test_another_generated_changelog_is_not_covered_by_the_import(self) -> None:
        (self.root / "CHANGELOG.md").write_text("Arbitrary generated changelog\n", encoding="utf-8")
        self.commit("Unpublished generated file")
        self.head = git(self.root, "rev-parse", "HEAD")
        with self.assertRaisesRegex(MODULE.BackSyncError, "unpublished generated"):
            self.verify()

    def test_consumed_and_unconsumed_fragment_changes_are_rejected(self) -> None:
        original = self.head
        for action in ("delete", "edit", "mode", "restore-consumed", "unknown-delete"):
            with self.subTest(action=action):
                git(self.root, "reset", "-q", "--hard", original)
                local = self.root / self.unconsumed
                if action in {"delete", "unknown-delete"}:
                    local.unlink()
                elif action == "edit":
                    local.write_text("changed\n", encoding="utf-8")
                elif action == "mode":
                    local.chmod(0o755)
                else:
                    (self.root / self.consumed).write_text("restored\n", encoding="utf-8")
                self.commit("Tamper fragment")
                self.head = git(self.root, "rev-parse", "HEAD")
                with self.assertRaises(MODULE.BackSyncError):
                    self.verify()

    def test_foreign_missing_duplicate_and_wrong_digest_receipts_are_rejected(self) -> None:
        valid = json.loads(json.dumps(self.receipt))
        for defect in ("foreign", "missing", "duplicate-fragment", "digest", "duplicate-key"):
            with self.subTest(defect=defect):
                self.receipt = json.loads(json.dumps(valid))
                raw = None
                if defect == "foreign":
                    self.receipt["repository"] = "foreign/repository"
                elif defect == "missing":
                    self.receipt.pop("fragments")
                elif defect == "duplicate-fragment":
                    self.receipt["fragments"] *= 2
                elif defect == "digest":
                    self.receipt["fragments"][0]["sha256"] = "0" * 64
                else:
                    raw = json.dumps(self.receipt)[:-1] + ',"repository":"foreign/repository"}'
                self.make_release(raw_receipt=raw)
                with self.assertRaises(MODULE.BackSyncError):
                    self.verify()

    def test_uncommitted_generated_and_fragment_edits_are_rejected(self) -> None:
        for path in ("galaxy.yml", self.unconsumed):
            with self.subTest(path=path):
                original = (self.root / path).read_bytes()
                (self.root / path).write_text("uncommitted edit\n", encoding="utf-8")
                with self.assertRaisesRegex(MODULE.BackSyncError, "uncommitted"):
                    self.verify(check_worktree=True)
                (self.root / path).write_bytes(original)

    def test_consumed_fragment_modified_on_develop_cannot_be_silently_deleted(self) -> None:
        git(self.root, "checkout", "-q", "--detach", self.develop)
        (self.root / self.consumed).write_text("bugfixes: [Unpublished alteration]\n", encoding="utf-8")
        self.commit("Alter an old fragment")
        self.develop = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/develop", self.develop)
        candidate_tree = git(self.root, "rev-parse", f"{self.head}^{{tree}}")
        self.head = git(
            self.root, "commit-tree", candidate_tree, "-p", self.develop, "-p", self.main, "-m", "Candidate fixture"
        )
        with self.assertRaisesRegex(MODULE.BackSyncError, "consumed fragment changed on Develop"):
            self.verify()

    def test_one_parent_main_and_missing_main_receipt_are_rejected(self) -> None:
        tree = git(self.root, "rev-parse", f"{self.main}^{{tree}}")
        self.main = git(self.root, "commit-tree", tree, "-p", self.base, "-m", "Not a release merge")
        git(self.root, "update-ref", "refs/remotes/origin/main", self.main)
        git(self.root, "tag", "-f", "v3.2.4", self.main)
        self.head = git(self.root, "commit-tree", tree, "-p", self.develop, "-p", self.main, "-m", "Candidate fixture")
        with self.assertRaisesRegex(MODULE.BackSyncError, "two-parent release merge"):
            self.verify()
        self.make_release()
        git(self.root, "checkout", "-q", "--detach", f"{self.main}^2")
        (self.root / "changelogs/release-preparation.json").unlink()
        git(self.root, "add", "-A")
        git(self.root, "config", "user.name", APP_NAME)
        git(self.root, "config", "user.email", APP_EMAIL)
        git(self.root, "commit", "-q", "--amend", "--no-edit")
        preparation = git(self.root, "rev-parse", "HEAD")
        missing_tree = git(self.root, "rev-parse", "HEAD^{tree}")
        self.main = git(self.root, "commit-tree", missing_tree, "-p", self.base, "-p", preparation, "-m", "Release")
        git(self.root, "update-ref", "refs/remotes/origin/main", self.main)
        git(self.root, "tag", "-f", "v3.2.4", self.main)
        self.head = git(self.root, "commit-tree", missing_tree, "-p", self.develop, "-p", self.main, "-m", "Import")
        with self.assertRaisesRegex(MODULE.BackSyncError, "release files are missing"):
            self.verify()

    def test_new_fragment_symlink_and_worktree_parent_symlink_are_rejected(self) -> None:
        local = self.root / "changelogs/fragments/import-guard.yml"
        local.unlink()
        local.symlink_to("unconsumed.yml")
        self.commit("Unsafe new fragment mode")
        unsafe = git(self.root, "rev-parse", "HEAD")
        original = self.head
        self.head = unsafe
        with self.assertRaisesRegex(MODULE.BackSyncError, "regular non-executable"):
            self.verify()
        git(self.root, "reset", "-q", "--hard", original)
        self.head = original
        fragments = self.root / "changelogs/fragments"
        moved = self.root / "fragment-storage"
        fragments.rename(moved)
        fragments.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(MODULE.BackSyncError, "unsafe import working-tree mode"):
            self.verify(check_worktree=True)

    def policy(
        self,
        *,
        author: str = "litroc",
        repository: str = MODULE.REPOSITORY,
        base: str = "develop",
        event: str = "pull_request",
        branch: str = BRANCH,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            environment.pop(variable, None)
        environment.update(
            {
                "BASE_SHA": self.develop,
                "HEAD_SHA": self.head,
                "GITHUB_EVENT_NAME": event,
                "GITHUB_REPOSITORY": MODULE.REPOSITORY,
                "GITHUB_HEAD_REPOSITORY": repository,
                "GITHUB_HEAD_REF": branch,
                "GITHUB_BASE_REF": base,
                "GITHUB_PR_AUTHOR": author,
                "LABELS_JSON": "[]",
                "HOME": str(self.root),
            }
        )
        return subprocess.run(  # noqa: S603 -- fixed shell and test-owned repository script.
            [shutil.which("bash") or "/bin/bash", "scripts/devtools-changelog-check.sh"],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_native_personal_same_repo_pr_boundary_and_no_app_early_return(self) -> None:
        accepted = self.policy()
        self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
        self.assertIn("ordinary code and current-head human review", accepted.stdout)
        self.assertNotIn("Release and release back-sync PRs manage", accepted.stdout)
        for arguments in (
            {"author": APP_NAME},
            {"author": "other"},
            {"author": ""},
            {"repository": "foreign/repo"},
            {"repository": ""},
            {"base": "main"},
            {"event": "push"},
            {"event": "workflow_dispatch"},
        ):
            with self.subTest(arguments=arguments):
                self.assertNotEqual(self.policy(**arguments).returncode, 0)
        self.assertEqual(self.policy(event="", author="", base="").returncode, 0)

    def make_push(self) -> dict[str, object]:
        candidate = self.head
        tree = git(self.root, "rev-parse", f"{candidate}^{{tree}}")
        self.head = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.develop,
            "-p",
            candidate,
            "-m",
            f"Merge pull request #42 from lightning-it/{BRANCH}",
        )
        git(self.root, "update-ref", "refs/remotes/origin/develop", self.head)
        git(self.root, "checkout", "-q", "--detach", self.head)
        return {
            "merged_at": "2026-10-18T00:00:00Z",
            "merge_commit_sha": self.head,
            "base": {"ref": "develop", "sha": self.develop, "repo": {"full_name": MODULE.REPOSITORY}},
            "head": {"ref": BRANCH, "sha": candidate, "repo": {"full_name": MODULE.REPOSITORY}},
            "user": {"login": "litroc"},
        }

    def test_existing_native_push_step_binds_the_actual_personal_merge_and_rejects_bad_relationships(self) -> None:
        pr = self.make_push()
        self.verify(check_worktree=True, merged_push=True)
        workflow = yaml.safe_load((ROOT / ".github/workflows/collection-ci.yml").read_text(encoding="utf-8"))
        step = next(item for item in workflow["jobs"]["lint-sanity"]["steps"] if item.get("id") == "release-push")
        native_step = self.root / "bind-push.sh"
        native_step.write_text(step["run"], encoding="utf-8")
        fixture = self.root / "associated-prs.json"
        output = self.root / "native-output"
        binaries = self.root / "fixture-bin"
        binaries.mkdir()
        gh = binaries / "gh"
        gh.write_text(
            '#!/bin/bash\nset -eu\ntest "$*" = "api -H Accept: application/vnd.github+json --paginate --slurp '
            'repos/${GITHUB_REPOSITORY}/commits/${SOURCE_SHA}/pulls"\ncat "$PR_FIXTURE"\n',
            encoding="utf-8",
        )
        gh.chmod(0o755)
        environment = os.environ.copy()
        for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
            environment.pop(variable, None)
        environment.update(
            {
                "SOURCE_SHA": self.head,
                "TARGET_REF": "develop",
                "PUSH_BEFORE": self.develop,
                "GITHUB_REPOSITORY": MODULE.REPOSITORY,
                "GITHUB_OUTPUT": str(output),
                "PR_FIXTURE": str(fixture),
                "PATH": f"{binaries}:{environment['PATH']}",
            }
        )

        def result(prs: list[object]) -> subprocess.CompletedProcess[str]:
            fixture.write_text(json.dumps([prs]), encoding="utf-8")
            output.write_text("", encoding="utf-8")
            return subprocess.run(  # noqa: S603 -- actual repository step with offline test-owned GitHub fixture.
                [shutil.which("bash") or "/bin/bash", str(native_step)],
                cwd=self.root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

        accepted = result([pr])
        self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
        self.assertEqual(
            output.read_text(encoding="utf-8"),
            f"author=litroc\nhead_repository={MODULE.REPOSITORY}\nimport_head_ref={BRANCH}\n",
        )
        guarded = self.policy(event="push")
        self.assertEqual(guarded.returncode, 0, guarded.stderr + guarded.stdout)
        for field, replacement in (
            ("merged_at", None),
            ("merge_commit_sha", self.base),
            ("user.login", APP_NAME),
            ("base.sha", self.base),
            ("base.ref", "main"),
            ("head.sha", self.base),
            ("head.ref", "fix/not-import"),
            ("head.repo.full_name", "foreign/repo"),
            ("base.repo.full_name", "foreign/repo"),
        ):
            with self.subTest(field=field):
                bad = json.loads(json.dumps(pr))
                owner = bad
                parts = field.split(".")
                for part in parts[:-1]:
                    owner = owner[part]
                owner[parts[-1]] = replacement
                self.assertNotEqual(result([bad]).returncode, 0)
        self.assertNotEqual(result([]).returncode, 0)
        self.assertNotEqual(result([pr, pr]).returncode, 0)
        environment["PUSH_BEFORE"] = self.base
        self.assertNotEqual(result([pr]).returncode, 0)
        environment["PUSH_BEFORE"] = self.develop
        git(self.root, "update-ref", "refs/remotes/origin/develop", self.develop)
        self.assertNotEqual(result([pr]).returncode, 0)
        with self.assertRaisesRegex(MODULE.BackSyncError, "ref mismatch"):
            self.verify(merged_push=True)

    def test_postmerge_tree_cannot_add_unreviewed_changes(self) -> None:
        pr = self.make_push()
        (self.root / "unreviewed.txt").write_text("added during merge\n", encoding="utf-8")
        git(self.root, "add", "unreviewed.txt")
        git(self.root, "commit", "-q", "--amend", "--no-edit")
        self.head = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/develop", self.head)
        self.assertNotEqual(pr["merge_commit_sha"], self.head)
        with self.assertRaisesRegex(MODULE.BackSyncError, "reviewed PR head tree"):
            self.verify(merged_push=True)

    def test_offline_synthetic_integration_recovers_only_the_exact_local_import_ref(self) -> None:
        candidate = self.head
        tree = git(self.root, "rev-parse", f"{candidate}^{{tree}}")
        self.head = git(
            self.root,
            "commit-tree",
            tree,
            "-p",
            self.develop,
            "-p",
            candidate,
            "-m",
            "Synthetic pull-request integration",
        )
        git(self.root, "checkout", "-q", "--detach", self.head)
        accepted = self.policy(event="", branch="", author="", base="")
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
        git(self.root, "branch", "reconcile/release-v3.2.5-to-develop", candidate)
        self.assertNotEqual(self.policy(event="", branch="", author="", base="").returncode, 0)


if __name__ == "__main__":
    unittest.main()
