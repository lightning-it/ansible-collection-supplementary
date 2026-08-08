from __future__ import annotations

import importlib.util
from argparse import Namespace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "classify-security-release.py"
SPEC = importlib.util.spec_from_file_location("security_release_classifier", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CHECKED_AT = datetime(2026, 8, 8, tzinfo=timezone.utc)
EVIDENCE_ID = "MLX90-GHSA-VJJF-WC74-GP86-3.2.2"


def args(**overrides):
    values = {
        "event_kind": "version",
        "base_sha": "1" * 40,
        "head_sha": "2" * 40,
        "base_ref": "",
        "head_ref": "",
        "ref": "",
        "commit_message": "",
        "version": "",
        "evidence_id": "",
    }
    values.update(overrides)
    return Namespace(**values)


class SecurityReleaseClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        metadata_root = self.root / ".lit" / "security-releases"
        metadata_root.mkdir(parents=True)
        (self.root / ".lit" / "security-release-profiles.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "profiles": {
                        "lit.supplementary/fix-v1": {
                            "description": "fixture",
                            "releaseEligible": True,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        self.metadata = {
            "schemaVersion": 1,
            "evidenceId": EVIDENCE_ID,
            "createdAt": "2026-08-04T11:31:48Z",
            "securityIdentifiers": ["GHSA-vjjf-wc74-gp86"],
            "affectedVersion": "3.1.0",
            "fixedVersion": "3.2.2",
            "consumers": ["lightning-it/container-ee-wunder-ansible-ubi9"],
            "acceptanceProfile": "lit.supplementary/fix-v1",
            "validity": {
                "notBefore": "2026-08-04T11:31:48Z",
                "expiresAt": "2026-09-03T11:31:48Z",
                "revoked": False,
            },
        }
        (metadata_root / "3.2.2.json").write_text(
            json.dumps(self.metadata), encoding="utf-8"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_exact_version_classifies_only_real_metadata(self):
        result = MODULE.classify(
            args(event_kind="version", version="3.2.2", evidence_id=EVIDENCE_ID),
            self.root,
            CHECKED_AT,
        )
        self.assertTrue(result.security_release)
        self.assertEqual(EVIDENCE_ID, result.evidence_id)
        self.assertFalse(
            MODULE.classify(
                args(event_kind="version", version="3.2.3"),
                self.root,
                CHECKED_AT,
            ).security_release
        )

    def test_claimed_evidence_mismatch_and_expiry_fail_closed(self):
        with self.assertRaisesRegex(MODULE.ClassificationError, "does not match"):
            MODULE.classify(
                args(event_kind="version", version="3.2.2", evidence_id="MLX90-OTHER"),
                self.root,
                CHECKED_AT,
            )
        with self.assertRaisesRegex(MODULE.ClassificationError, "not currently valid"):
            MODULE.classify(
                args(event_kind="version", version="3.2.2"),
                self.root,
                datetime(2026, 10, 1, tzinfo=timezone.utc),
            )

    def test_normal_develop_and_unrelated_main_events_stay_manual(self):
        self.assertFalse(
            MODULE.classify(
                args(event_kind="pull_request", base_ref="develop", head_ref="release/v3.2.2"),
                self.root,
                CHECKED_AT,
            ).security_release
        )
        with mock.patch.object(MODULE, "changed_security_versions", return_value=[]):
            self.assertFalse(
                MODULE.classify(
                    args(event_kind="push", ref="refs/heads/main", commit_message="feat: normal"),
                    self.root,
                    CHECKED_AT,
                ).security_release
            )

    def test_release_pr_and_security_branch_are_evidence_bound(self):
        release = MODULE.classify(
            args(event_kind="pull_request", base_ref="main", head_ref="release/v3.2.2"),
            self.root,
            CHECKED_AT,
        )
        self.assertTrue(release.security_release)
        with mock.patch.object(MODULE, "changed_security_versions", return_value=["3.2.2"]):
            security = MODULE.classify(
                args(
                    event_kind="pull_request",
                    base_ref="main",
                    head_ref=f"security-release/{EVIDENCE_ID}",
                ),
                self.root,
                CHECKED_AT,
            )
        self.assertTrue(security.security_release)

    def test_main_push_classifies_metadata_or_release_prepare_only(self):
        with mock.patch.object(MODULE, "changed_security_versions", return_value=["3.2.2"]):
            promoted = MODULE.classify(
                args(event_kind="push", ref="refs/heads/main"),
                self.root,
                CHECKED_AT,
            )
        self.assertTrue(promoted.security_release)
        with mock.patch.object(MODULE, "changed_security_versions", return_value=[]):
            prepared = MODULE.classify(
                args(
                    event_kind="push",
                    ref="refs/heads/main",
                    commit_message="Merge pull request #1\n\nchore(release): prepare v3.2.2",
                ),
                self.root,
                CHECKED_AT,
            )
        self.assertTrue(prepared.security_release)


if __name__ == "__main__":
    unittest.main()
