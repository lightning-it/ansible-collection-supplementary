"""Tests for exact App-authored Supplementary main promotions."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PROMOTION = load_module("security_main_promotion_tested", SCRIPTS / "security_main_promotion.py")
AUTHORIZATION = load_module(
    "main_promotion_authorization_tested",
    SCRIPTS / "main-promotion-authorization.py",
)
CONTRACT = PROMOTION.CONTRACT
GIT = shutil.which("git")
assert GIT is not None
VERSION = "3.2.4"
EVIDENCE_ID = "MLX90-KEYCLOAK-26.7.1-3.2.4"
PROFILE = "lit.supplementary/keycloak-26.7.1-security-v1"
CHECKED_AT = datetime(2026, 8, 8, 23, 0, tzinfo=UTC)


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


class SecurityMainPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        profiles = {
            "schemaVersion": 1,
            "profiles": {
                PROFILE: {
                    "description": "Exact Keycloak acceptance",
                    "releaseEligible": True,
                }
            },
        }
        profile_path = self.root / ".lit/security-release-profiles.json"
        profile_path.parent.mkdir(parents=True)
        profile_path.write_bytes(CONTRACT.canonical_document_bytes(profiles))
        role = self.root / "roles/keycloak_deploy/defaults/main.yml"
        role.parent.mkdir(parents=True)
        role.write_text("---\nimage: affected\n", encoding="utf-8")
        (self.root / "galaxy.yml").write_text("---\nversion: 3.2.3\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "protected main")
        self.base_sha = git(self.root, "rev-parse", "HEAD")

        metadata = {
            "schemaVersion": 1,
            "evidenceId": EVIDENCE_ID,
            "createdAt": "2026-08-08T22:30:00Z",
            "securityIdentifiers": ["CVE-2026-9793"],
            "affectedVersion": "3.2.3",
            "fixedVersion": VERSION,
            "consumers": [CONTRACT.CONSUMER_REPOSITORY],
            "acceptanceProfile": PROFILE,
            "validity": {
                "notBefore": "2026-08-08T22:30:00Z",
                "expiresAt": "2026-09-08T22:30:00Z",
                "revoked": False,
            },
        }
        self.metadata_raw = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()
        self.fragment_raw = b'---\nsecurity_fixes:\n  - "Exact Keycloak fix."\n'
        self._write_candidate_files()
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "candidate")
        self.candidate_sha = git(self.root, "rev-parse", "HEAD")
        receipt_path = f".lit/security-release-intakes/{VERSION}.json"
        candidate_diff = PROMOTION.candidate_diff_without_receipt(
            self.root,
            self.base_sha,
            self.candidate_sha,
            receipt_path,
        )
        candidate_digest = CONTRACT.sha256_bytes(candidate_diff)
        chain_id = CONTRACT.compute_chain_id(
            repository=CONTRACT.PRODUCER_REPOSITORY,
            repository_id=CONTRACT.PRODUCER_REPOSITORY_ID,
            base_sha=self.base_sha,
            candidate_head_sha=self.candidate_sha,
            candidate_diff_sha256=candidate_digest,
            evidence_id=EVIDENCE_ID,
            fixed_version=VERSION,
            acceptance_profile=PROFILE,
        )
        self.request = {
            "schemaVersion": 2,
            "event": "mlx90-security-release",
            "repository": CONTRACT.PRODUCER_REPOSITORY,
            "repositoryId": CONTRACT.PRODUCER_REPOSITORY_ID,
            "baseSha": self.base_sha,
            "candidateRef": "develop",
            "candidateBaseSha": self.base_sha,
            "candidateHeadSha": self.candidate_sha,
            "candidateDiffSha256": candidate_digest,
            "evidenceId": EVIDENCE_ID,
            "fixedVersion": VERSION,
            "acceptanceProfile": PROFILE,
            "metadataSha256": CONTRACT.sha256_bytes(self.metadata_raw),
            "chainId": chain_id,
            "issuedAt": "2026-08-08T22:30:00Z",
            "expiresAt": "2026-09-08T22:30:00Z",
            "humanActions": 0,
        }
        self.verified = {
            "schemaVersion": 2,
            "chainId": chain_id,
            "branch": f"security-release/{EVIDENCE_ID}",
            "baseSha": self.base_sha,
            "candidateBaseSha": self.base_sha,
            "candidateHeadSha": self.candidate_sha,
            "candidateDiffSha256": candidate_digest,
            "evidenceId": EVIDENCE_ID,
            "fixedVersion": VERSION,
            "metadataPath": f".lit/security-releases/{VERSION}.json",
            "metadataSha256": CONTRACT.sha256_bytes(self.metadata_raw),
            "acceptanceProfile": PROFILE,
            "changelogFragmentPath": "changelogs/fragments/keycloak-security.yml",
            "changelogFragmentSha256": CONTRACT.sha256_bytes(self.fragment_raw),
            "changedPaths": [
                f".lit/security-releases/{VERSION}.json",
                "changelogs/fragments/keycloak-security.yml",
                "roles/keycloak_deploy/defaults/main.yml",
            ],
            "humanActions": 0,
        }
        self.receipt = CONTRACT.build_intake_receipt(
            self.request,
            self.verified,
            checked_at=CHECKED_AT,
            workflow_run_id="123456",
            workflow_attempt="1",
            workflow_ref=(
                f"{CONTRACT.PRODUCER_REPOSITORY}/.github/workflows/security-release-intake.yml@refs/heads/main"
            ),
            workflow_event="workflow_dispatch",
            workflow_actor=CONTRACT.RELEASE_APP_LOGIN,
            workflow_triggering_actor=CONTRACT.RELEASE_APP_LOGIN,
            observed_automation=CONTRACT.RELEASE_APP_IDENTITY,
        )
        self.head_sha = self._materialize_head()
        self.base_root = self.root.parent / f"{self.root.name}-base"
        git(self.root, "worktree", "add", "-q", "--detach", str(self.base_root), self.base_sha)

    def _write_candidate_files(self) -> None:
        metadata = self.root / f".lit/security-releases/{VERSION}.json"
        metadata.parent.mkdir(parents=True, exist_ok=True)
        metadata.write_bytes(self.metadata_raw)
        fragment = self.root / "changelogs/fragments/keycloak-security.yml"
        fragment.parent.mkdir(parents=True, exist_ok=True)
        fragment.write_bytes(self.fragment_raw)
        (self.root / "roles/keycloak_deploy/defaults/main.yml").write_text(
            "---\nimage: fixed\n",
            encoding="utf-8",
        )

    def _materialize_head(self, *, app_identity: bool = True, extra_path: str = "") -> str:
        git(self.root, "switch", "-q", "--detach", self.base_sha)
        self._write_candidate_files()
        receipt = self.root / f".lit/security-release-intakes/{VERSION}.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_bytes(CONTRACT.canonical_document_bytes(self.receipt))
        if extra_path:
            path = self.root / extra_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unexpected\n", encoding="utf-8")
        if app_identity:
            git(self.root, "config", "user.name", CONTRACT.RELEASE_APP_LOGIN)
            git(self.root, "config", "user.email", CONTRACT.RELEASE_APP_EMAIL)
        else:
            git(self.root, "config", "user.name", "Human")
            git(self.root, "config", "user.email", "human@example.invalid")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", f"fix(security): {EVIDENCE_ID}")
        return git(self.root, "rev-parse", "HEAD")

    def verify(self, head_sha: str | None = None) -> PROMOTION.Promotion:
        return PROMOTION.verify_promotion(
            base_root=self.base_root,
            head_root=self.root,
            base_sha=self.base_sha,
            head_sha=head_sha or self.head_sha,
            head_ref=f"security-release/{EVIDENCE_ID}",
            checked_at=CHECKED_AT,
        )

    def test_exact_materialized_candidate_and_receipt_are_accepted(self) -> None:
        result = self.verify()
        self.assertEqual("security", result.mode)
        self.assertEqual(self.request["chainId"], result.chain_id)
        self.assertEqual(VERSION, result.version)

    def test_extra_materialized_path_is_rejected(self) -> None:
        head = self._materialize_head(extra_path="unexpected.txt")
        with self.assertRaisesRegex(PROMOTION.PromotionError, "differ from the verified candidate"):
            self.verify(head)

    def test_non_app_commit_is_rejected(self) -> None:
        head = self._materialize_head(app_identity=False)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "not the release App"):
            self.verify(head)

    def test_malformed_reserved_branch_is_rejected(self) -> None:
        with self.assertRaisesRegex(PROMOTION.PromotionError, "malformed"):
            PROMOTION.verify_promotion(
                base_root=self.base_root,
                head_root=self.root,
                base_sha=self.base_sha,
                head_sha=self.head_sha,
                head_ref="security-release/not-an-evidence-id",
                checked_at=CHECKED_AT,
            )

    def test_live_authorization_uses_verified_content_not_branch_name_only(self) -> None:
        pull = {
            "number": 42,
            "state": "open",
            "draft": False,
            "base": {"ref": "main", "sha": self.base_sha},
            "head": {
                "ref": f"security-release/{EVIDENCE_ID}",
                "sha": self.head_sha,
                "repo": {"full_name": CONTRACT.PRODUCER_REPOSITORY},
            },
            "user": {
                "login": CONTRACT.RELEASE_APP_LOGIN,
                "id": int(CONTRACT.RELEASE_APP_ACCOUNT_ID),
                "type": "Bot",
            },
        }
        result = AUTHORIZATION.classify(
            pull,
            CONTRACT.PRODUCER_REPOSITORY,
            self.base_sha,
            self.head_sha,
            base_root=self.base_root,
            head_root=self.root,
        )
        self.assertEqual("security", result.mode)
        pull["user"] = {"login": "human", "id": 1, "type": "User"}
        with self.assertRaisesRegex(AUTHORIZATION.AuthorizationError, "release App"):
            AUTHORIZATION.classify(
                pull,
                CONTRACT.PRODUCER_REPOSITORY,
                self.base_sha,
                self.head_sha,
                base_root=self.base_root,
                head_root=self.root,
            )


if __name__ == "__main__":
    unittest.main()
