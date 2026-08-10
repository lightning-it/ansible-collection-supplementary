"""Regression tests for immutable, force-free release back-sync heads."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_release_back_sync.py"
SPEC = importlib.util.spec_from_file_location("release_back_sync_contract", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
GIT = shutil.which("git")
assert GIT is not None
VERSION = "3.2.4"
TAG = f"v{VERSION}"
EVIDENCE_ID = "MLX90-KEYCLOAK-26.7.1-3.2.4"
APP_NAME = "lightning-it-release-automation[bot]"
APP_EMAIL = "307565056+lightning-it-release-automation[bot]@users.noreply.github.com"


def git(root: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(variable, None)
    return subprocess.run(  # noqa: S603 -- fixed git binary and test-owned arguments.
        [GIT, *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    ).stdout.strip()


class ReleaseBackSyncContractTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        (self.root / "changelogs/fragments").mkdir(parents=True)
        (self.root / "CHANGELOG.rst").write_text("v3.2.3\n=======\n", encoding="utf-8")
        (self.root / "galaxy.yml").write_text("---\nversion: 3.2.3\n", encoding="utf-8")
        (self.root / "changelogs/changelog.yaml").write_text("---\nreleases: {}\n", encoding="utf-8")
        (self.root / "changelogs/.plugin-cache.yaml").write_text("---\ncache: {}\n", encoding="utf-8")
        (self.root / "changelogs/fragments/security.yml").write_text(
            '{"security_fixes":["Exact fix."]}\n',
            encoding="utf-8",
        )
        (self.root / "roles/example").mkdir(parents=True)
        (self.root / "roles/example/main.yml").write_text("---\nfixed: true\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "develop base")
        self.develop_base = git(self.root, "rev-parse", "HEAD")

        git(self.root, "switch", "-q", "-c", "main-fixture")
        metadata_path = self.root / f".lit/security-releases/{VERSION}.json"
        metadata_path.parent.mkdir(parents=True)
        metadata_path.write_text(
            json.dumps({"evidenceId": EVIDENCE_ID}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        intake_path = self.root / f".lit/security-release-intakes/{VERSION}.json"
        intake_path.parent.mkdir(parents=True)
        intake_path.write_text(
            json.dumps({"request": {"evidenceId": EVIDENCE_ID}}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        git(self.root, "add", ".lit")
        git(self.root, "commit", "-q", "-m", "security intake")
        self.main_base = git(self.root, "rev-parse", "HEAD")

        git(self.root, "switch", "-q", "-c", "release-fixture")
        (self.root / "CHANGELOG.rst").write_text(
            "v3.2.4\n=======\n\nSecurity release.\n\nv3.2.3\n=======\n",
            encoding="utf-8",
        )
        (self.root / "galaxy.yml").write_text("---\nversion: 3.2.4\n", encoding="utf-8")
        (self.root / "changelogs/changelog.yaml").write_text(
            "---\nreleases:\n  3.2.4: {}\n",
            encoding="utf-8",
        )
        (self.root / "changelogs/.plugin-cache.yaml").write_text(
            "---\ncache:\n  version: 3.2.4\n",
            encoding="utf-8",
        )
        (self.root / "changelogs/fragments/security.yml").unlink()
        receipt = {
            "release_mode": "security",
            "chain_id": "sha256:" + "a" * 64,
            "security": {"evidence_id": EVIDENCE_ID},
            "fragments": [{"path": "security.yml"}],
        }
        (self.root / "changelogs/release-preparation.json").write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", f"chore(release): prepare v{VERSION}")
        release_head = git(self.root, "rev-parse", "HEAD")

        git(self.root, "switch", "-q", "main-fixture")
        git(self.root, "merge", "-q", "--no-ff", release_head, "-m", f"Release v{VERSION}")
        self.release_sha = git(self.root, "rev-parse", "HEAD")
        self.head_sha = self._make_back_sync()

    def _app_identity(self) -> None:
        git(self.root, "config", "user.name", APP_NAME)
        git(self.root, "config", "user.email", APP_EMAIL)

    def _make_back_sync(self, *, extra_path: str = "", app_identity: bool = True) -> str:
        git(self.root, "switch", "-q", "--detach", self.develop_base)
        if app_identity:
            self._app_identity()
        else:
            git(self.root, "config", "user.name", "Human")
            git(self.root, "config", "user.email", "human@example.invalid")
        git(
            self.root,
            "merge",
            "-q",
            "--no-ff",
            self.release_sha,
            "-m",
            f"chore: sync {TAG} release back to develop",
        )
        if extra_path:
            path = self.root / extra_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unauthorized\n", encoding="utf-8")
            git(self.root, "add", extra_path)
            git(self.root, "commit", "-q", "--amend", "--no-edit")
        return git(self.root, "rev-parse", "HEAD")

    def verify(self, *, head_sha: str | None = None, evidence_id: str = EVIDENCE_ID) -> None:
        MODULE.verify(
            root=self.root,
            develop_tip=self.develop_base,
            release_sha=self.release_sha,
            head_sha=head_sha or self.head_sha,
            tag=TAG,
            security_version=VERSION,
            evidence_id=evidence_id,
        )

    def test_exact_app_authored_back_sync_is_accepted(self) -> None:
        self.verify()

    def test_non_release_path_is_rejected(self) -> None:
        malicious = self._make_back_sync(extra_path="unexpected.txt")
        with self.assertRaisesRegex(MODULE.BackSyncError, "non-release path"):
            self.verify(head_sha=malicious)

    def test_non_app_commit_is_rejected(self) -> None:
        human = self._make_back_sync(app_identity=False)
        with self.assertRaisesRegex(MODULE.BackSyncError, "not the release App"):
            self.verify(head_sha=human)

    def test_security_evidence_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.BackSyncError, "evidenceId differs"):
            self.verify(evidence_id="MLX90-OTHER-EVIDENCE")

    def test_first_parent_must_remain_on_current_develop_ancestry(self) -> None:
        git(self.root, "switch", "-q", "--orphan", "unrelated")
        for path in list(self.root.iterdir()):
            if path.name != ".git":
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        (self.root / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
        git(self.root, "add", "unrelated.txt")
        git(self.root, "commit", "-q", "-m", "unrelated")
        unrelated = git(self.root, "rev-parse", "HEAD")
        with self.assertRaisesRegex(MODULE.BackSyncError, "not an ancestor"):
            MODULE.verify(
                root=self.root,
                develop_tip=unrelated,
                release_sha=self.release_sha,
                head_sha=self.head_sha,
                tag=TAG,
                security_version=VERSION,
                evidence_id=EVIDENCE_ID,
            )


if __name__ == "__main__":
    unittest.main()
