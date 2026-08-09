"""Tests for the protected-head MLX-90 Security request dispatcher."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/security-release-dispatch.py"
WORKFLOW = ROOT / ".github/workflows/security-release-dispatch.yml"
SPEC = importlib.util.spec_from_file_location("security_request_dispatch", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
REPOSITORY = "lightning-it/ansible-collection-supplementary"
VERSION = "3.2.4"
EVIDENCE_ID = "MLX90-KEYCLOAK-26.7.1-3.2.4"
PROFILE = "lit.supplementary/keycloak-26.7.1-security-v1"
NOW = datetime(2026, 8, 8, 23, 0, tzinfo=UTC)
GIT = shutil.which("git")
assert GIT is not None


def git(root: Path, *args: str) -> str:
    environment = os.environ.copy()
    for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(variable, None)
    return subprocess.run(  # noqa: S603 -- fixed git binary and test-owned arguments.
        [GIT, *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    ).stdout.strip()


class SecurityReleaseRequestDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Test")
        git(self.root, "config", "user.email", "test@example.invalid")
        (self.root / ".lit").mkdir()
        (self.root / ".lit/security-release-profiles.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "profiles": {
                        PROFILE: {
                            "description": "Exact Keycloak acceptance",
                            "releaseEligible": True,
                        }
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        product = self.root / "roles/keycloak_deploy/defaults/main.yml"
        product.parent.mkdir(parents=True)
        product.write_text("---\nkeycloak_deploy_image: affected\n", encoding="utf-8")
        inventory = self.root / "meta/source-dependencies.yml"
        inventory.parent.mkdir(parents=True)
        inventory.write_text("---\ncontainer_images: []\n", encoding="utf-8")
        (self.root / "galaxy.yml").write_text(
            "---\nversion: 3.2.3\n",
            encoding="utf-8",
        )
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "base")
        self.base = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/main", self.base)

        product.write_text("---\nkeycloak_deploy_image: fixed\n", encoding="utf-8")
        inventory.write_text(
            "---\ncontainer_images:\n  - reference: fixed@sha256:example\n",
            encoding="utf-8",
        )
        metadata = self.root / f".lit/security-releases/{VERSION}.json"
        metadata.parent.mkdir()
        metadata.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "evidenceId": EVIDENCE_ID,
                    "createdAt": "2026-08-08T22:30:00Z",
                    "securityIdentifiers": ["CVE-2026-9793"],
                    "affectedVersion": "3.2.3",
                    "fixedVersion": VERSION,
                    "consumers": ["lightning-it/container-ee-wunder-ansible-ubi9"],
                    "acceptanceProfile": PROFILE,
                    "validity": {
                        "notBefore": "2026-08-08T22:30:00Z",
                        "expiresAt": "2026-09-08T22:30:00Z",
                        "revoked": False,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        fragment = self.root / "changelogs/fragments/keycloak-security.yml"
        fragment.parent.mkdir(parents=True)
        fragment.write_text("---\nsecurity_fixes:\n  - Keycloak fix.\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "Security candidate")
        self.head = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/develop", self.head)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_candidate_builds_a_valid_human_actions_zero_request(self) -> None:
        envelope = MODULE.build_envelope(
            self.root,
            REPOSITORY,
            self.base,
            self.head,
            NOW,
        )
        self.assertIs(envelope["dispatch"], True)
        request = envelope["request"]
        self.assertEqual(self.base, request["baseSha"])
        self.assertEqual(self.head, request["candidateHeadSha"])
        self.assertEqual(EVIDENCE_ID, request["evidenceId"])
        self.assertEqual(0, request["humanActions"])

    def test_ordinary_develop_change_does_not_mint_a_dispatch_request(self) -> None:
        git(self.root, "checkout", "-q", self.base)
        product = self.root / "roles/keycloak_deploy/defaults/main.yml"
        product.write_text("---\nkeycloak_deploy_image: ordinary\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "ordinary change")
        head = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/develop", head)
        self.assertEqual(
            {"dispatch": False},
            MODULE.build_envelope(self.root, REPOSITORY, self.base, head, NOW),
        )

    def test_controller_workflow_relays_to_main_and_is_least_privilege(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_run:", workflow)
        self.assertIn("workflows: [Collection CI]", workflow)
        self.assertIn("branches: [develop]", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("source_run_id:", workflow)
        self.assertNotIn("source-run-id", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertIn("github.event.workflow_run.event == 'push'", workflow)
        self.assertIn("gh workflow run security-release-dispatch.yml", workflow)
        self.assertIn("--ref main", workflow)
        self.assertIn("github.event_name == 'workflow_dispatch'", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn('(.name == "Collection CI")', workflow)
        self.assertIn(
            '(.path == ".github/workflows/collection-ci.yml")', workflow
        )
        self.assertEqual(2, workflow.count("ref: ${{ github.sha }}"))
        self.assertNotIn("ref: ${{ github.event.workflow_run.head_sha }}", workflow)
        self.assertNotIn("ref: ${{ needs.classify.outputs.source-sha }}", workflow)
        self.assertIn("needs.classify.outputs['source-sha']", workflow)
        self.assertIn('test "$(git rev-parse HEAD)" = "$CONTROLLER_SHA"', workflow)
        self.assertIn('test "$(git rev-parse origin/develop)" = "$SOURCE_SHA"', workflow)
        self.assertIn("needs.classify.outputs.dispatch == 'true'", workflow)
        self.assertIn("environment: mlx90-security-release-evidence", workflow)
        self.assertIn("permission-contents: write", workflow)
        self.assertIn('test "$APP_INSTALLATION_ID" = 148019054', workflow)
        self.assertIn(".client_payload.humanActions == 0", workflow)
        self.assertNotIn("permission-actions", workflow)
        self.assertNotIn("permission-pull-requests", workflow)
        self.assertLess(
            workflow.index("Reconstruct exact validated request before token access"),
            workflow.index("Mint repository-scoped release automation App token"),
        )


if __name__ == "__main__":
    unittest.main()
