"""Tests for the canonical MLX-90 Security release contract."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = str(ROOT / "scripts")
sys.path.insert(0, SCRIPTS)
try:
    import security_release_contract as CONTRACT  # noqa: E402
finally:
    sys.path.remove(SCRIPTS)

VERSION = "3.2.4"
EVIDENCE_ID = "MLX90-KEYCLOAK-26.7.1-3.2.4"
PROFILE = "lit.supplementary/keycloak-26.7.1-security-v1"
NOW = datetime(2026, 8, 8, 23, 0, tzinfo=UTC)


class SecurityReleaseContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        profiles = self.root / ".lit/security-release-profiles.json"
        profiles.parent.mkdir(parents=True)
        profiles.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "profiles": {
                        PROFILE: {
                            "description": "Exact Keycloak acceptance",
                            "releaseEligible": True,
                        }
                    },
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.metadata = {
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
        self.metadata_raw = (json.dumps(self.metadata, indent=2, sort_keys=True) + "\n").encode()
        candidate_digest = "sha256:" + "c" * 64
        chain_id = CONTRACT.compute_chain_id(
            repository=CONTRACT.PRODUCER_REPOSITORY,
            repository_id=CONTRACT.PRODUCER_REPOSITORY_ID,
            base_sha="a" * 40,
            candidate_head_sha="b" * 40,
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
            "baseSha": "a" * 40,
            "candidateRef": "develop",
            "candidateBaseSha": "a" * 40,
            "candidateHeadSha": "b" * 40,
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
        fragment = b'{"security_fixes":["Keycloak fix."]}\n'
        self.verified = {
            "schemaVersion": 2,
            "chainId": chain_id,
            "branch": f"security-release/{EVIDENCE_ID}",
            "baseSha": "a" * 40,
            "candidateBaseSha": "a" * 40,
            "candidateHeadSha": "b" * 40,
            "candidateDiffSha256": candidate_digest,
            "evidenceId": EVIDENCE_ID,
            "fixedVersion": VERSION,
            "metadataPath": f".lit/security-releases/{VERSION}.json",
            "metadataSha256": CONTRACT.sha256_bytes(self.metadata_raw),
            "acceptanceProfile": PROFILE,
            "changelogFragmentPath": "changelogs/fragments/keycloak-security.yml",
            "changelogFragmentSha256": CONTRACT.sha256_bytes(fragment),
            "changedPaths": [
                f".lit/security-releases/{VERSION}.json",
                "changelogs/fragments/keycloak-security.yml",
                "roles/keycloak_deploy/defaults/main.yml",
            ],
            "humanActions": 0,
        }
        self.fragment_raw = fragment

    def _receipt(self, *, checked_at: datetime = NOW) -> dict[str, object]:
        return CONTRACT.build_intake_receipt(
            self.request,
            self.verified,
            checked_at=checked_at,
            workflow_run_id="123456",
            workflow_attempt="1",
            workflow_ref=(
                f"{CONTRACT.PRODUCER_REPOSITORY}/.github/workflows/security-release-intake.yml@refs/heads/main"
            ),
            workflow_event="repository_dispatch",
            workflow_actor=CONTRACT.RELEASE_APP_LOGIN,
            observed_automation=CONTRACT.RELEASE_APP_IDENTITY,
        )

    def _write_binding(self) -> dict[str, object]:
        metadata_path = self.root / f".lit/security-releases/{VERSION}.json"
        metadata_path.parent.mkdir(parents=True)
        metadata_path.write_bytes(self.metadata_raw)
        receipt = self._receipt()
        receipt_path = self.root / f".lit/security-release-intakes/{VERSION}.json"
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_bytes(CONTRACT.canonical_document_bytes(receipt))
        fragment_path = self.root / self.verified["changelogFragmentPath"]
        fragment_path.parent.mkdir(parents=True)
        fragment_path.write_bytes(self.fragment_raw)
        return receipt

    def test_chain_id_uses_one_canonical_exact_binding(self) -> None:
        binding = CONTRACT.chain_binding(
            repository=CONTRACT.PRODUCER_REPOSITORY,
            repository_id=CONTRACT.PRODUCER_REPOSITORY_ID,
            base_sha="a" * 40,
            candidate_head_sha="b" * 40,
            candidate_diff_sha256="sha256:" + "c" * 64,
            evidence_id=EVIDENCE_ID,
            fixed_version=VERSION,
            acceptance_profile=PROFILE,
        )
        expected = (
            "sha256:" + hashlib.sha256(json.dumps(binding, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
        )
        self.assertEqual(expected, self.request["chainId"])
        reordered = dict(reversed(list(binding.items())))
        self.assertEqual(expected, CONTRACT.canonical_sha256(reordered))

    def test_request_and_receipt_are_exact_duplicate_safe_and_app_bound(self) -> None:
        CONTRACT.validate_request(self.request, CONTRACT.PRODUCER_REPOSITORY, NOW)
        receipt = self._receipt()
        CONTRACT.verify_intake_receipt(receipt, checked_at=NOW)
        self.assertEqual(CONTRACT.RELEASE_APP_IDENTITY, receipt["automation"])

        mutations = (
            lambda value: value["automation"].__setitem__("installationId", "1"),
            lambda value: value["controller"].__setitem__("actor", "human"),
            lambda value: value.__setitem__("unknown", True),
            lambda value: value["request"].__setitem__("chainId", "sha256:" + "0" * 64),
            lambda value: value["request"].__setitem__("schemaVersion", 2.0),
            lambda value: value["request"].__setitem__("humanActions", False),
            lambda value: value["controller"].__setitem__("runId", 123456),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                tampered = copy.deepcopy(receipt)
                mutate(tampered)
                with self.assertRaises(CONTRACT.ContractError):
                    CONTRACT.verify_intake_receipt(tampered, checked_at=NOW)

        after_expiry = datetime(2026, 9, 8, 22, 30, tzinfo=UTC)
        with self.assertRaisesRegex(CONTRACT.ContractError, "not currently valid"):
            CONTRACT.verify_intake_receipt(receipt, checked_at=after_expiry)
        with self.assertRaisesRegex(CONTRACT.ContractError, "not currently valid"):
            self._receipt(checked_at=after_expiry)

        with self.assertRaisesRegex(CONTRACT.ContractError, "duplicate JSON key"):
            CONTRACT.load_json_bytes(b'{"schemaVersion":2,"schemaVersion":2}', "receipt")
        with self.assertRaisesRegex(CONTRACT.ContractError, "fields mismatch"):
            request = copy.deepcopy(self.request)
            request["unknown"] = True
            CONTRACT.validate_request(request, CONTRACT.PRODUCER_REPOSITORY, NOW)
        for field, invalid in (("schemaVersion", 2.0), ("humanActions", False)):
            with self.subTest(result_field=field, invalid=invalid):
                verified = copy.deepcopy(self.verified)
                verified[field] = invalid
                with self.assertRaises(CONTRACT.ContractError):
                    CONTRACT.validate_intake_result(self.request, verified)
        with self.assertRaisesRegex(CONTRACT.ContractError, "observed release automation"):
            observed = dict(CONTRACT.RELEASE_APP_IDENTITY)
            observed["installationId"] = "1"
            CONTRACT.build_intake_receipt(
                self.request,
                self.verified,
                checked_at=NOW,
                workflow_run_id="123456",
                workflow_attempt="1",
                workflow_ref=(
                    f"{CONTRACT.PRODUCER_REPOSITORY}/.github/workflows/security-release-intake.yml@refs/heads/main"
                ),
                workflow_event="repository_dispatch",
                workflow_actor=CONTRACT.RELEASE_APP_LOGIN,
                observed_automation=observed,
            )

    def test_security_fragment_and_consumer_are_exact(self) -> None:
        valid = b'{"security_fixes":["Fixed exact vulnerability."]}\n'
        self.assertEqual(
            {"security_fixes": ["Fixed exact vulnerability."]},
            CONTRACT.validate_security_fragment(valid, "fragment"),
        )
        for invalid in (
            b"---\nsecurity_fixes:\n  - YAML is not canonical JSON.\n",
            b'{"bugfixes":["not Security"]}',
            b'{"security_fixes":[]}',
            b'{"security_fixes":["one"],"security_fixes":["two"]}',
        ):
            with self.subTest(invalid=invalid), self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_security_fragment(invalid, "fragment")

        CONTRACT.validate_metadata_payload(
            self.metadata,
            expected_evidence_id=EVIDENCE_ID,
            expected_version=VERSION,
            expected_profile=PROFILE,
            checked_at=NOW,
        )
        metadata = copy.deepcopy(self.metadata)
        metadata["consumers"] = [CONTRACT.CONSUMER_REPOSITORY, "example/other"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "exact MLX-90 consumer"):
            CONTRACT.validate_metadata_payload(
                metadata,
                expected_evidence_id=EVIDENCE_ID,
                expected_version=VERSION,
                expected_profile=PROFILE,
                checked_at=NOW,
            )

    def test_immutable_markers_reject_receipts_and_existing_metadata_in_candidate(
        self,
    ) -> None:
        metadata_path = f".lit/security-releases/{VERSION}.json"
        valid = [
            ("A", metadata_path),
            ("A", "changelogs/fragments/keycloak-security.yml"),
            ("M", "roles/keycloak_deploy/defaults/main.yml"),
        ]
        CONTRACT.validate_immutable_marker_changes(valid, VERSION)
        invalid = (
            valid + [("M", ".lit/security-releases/3.2.2.json")],
            [("M", metadata_path)],
            valid + [("A", f".lit/security-release-intakes/{VERSION}.json")],
            valid + [("M", ".lit/security-release-profiles.json")],
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(CONTRACT.ContractError):
                CONTRACT.validate_immutable_marker_changes(changes, VERSION)

    def test_binding_fails_closed_for_partial_or_tampered_markers(self) -> None:
        metadata_path = self.root / f".lit/security-releases/{VERSION}.json"
        metadata_path.parent.mkdir(parents=True)
        metadata_path.write_bytes(self.metadata_raw)
        with self.assertRaisesRegex(CONTRACT.ContractError, "partial Security marker"):
            CONTRACT.load_security_binding(self.root, VERSION, checked_at=NOW)

        receipt = self._receipt()
        receipt_path = self.root / f".lit/security-release-intakes/{VERSION}.json"
        receipt_path.parent.mkdir(parents=True)
        receipt_path.write_bytes(CONTRACT.canonical_document_bytes(receipt))
        fragment_path = self.root / self.verified["changelogFragmentPath"]
        with self.assertRaisesRegex(CONTRACT.ContractError, "changelog fragment must be"):
            CONTRACT.load_security_binding(self.root, VERSION, checked_at=NOW)
        fragment_path.parent.mkdir(parents=True)
        fragment_path.write_bytes(self.fragment_raw)
        binding = CONTRACT.load_security_binding(self.root, VERSION, checked_at=NOW)
        assert binding is not None
        self.assertEqual(self.request["chainId"], binding["chain_id"])
        self.assertEqual(
            CONTRACT.sha256_bytes(receipt_path.read_bytes()),
            binding["intake_receipt_sha256"],
        )

        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CONTRACT.ContractError, "not canonical JSON"):
            CONTRACT.load_security_binding(self.root, VERSION, checked_at=NOW)
        receipt_path.write_bytes(CONTRACT.canonical_document_bytes(receipt))

        fragment_path.write_bytes(b'{"security_fixes":["Changed fix."]}\n')
        with self.assertRaisesRegex(CONTRACT.ContractError, "fragment digest differs"):
            CONTRACT.load_security_binding(self.root, VERSION, checked_at=NOW)
        fragment_path.write_bytes(self.fragment_raw)

        receipt_path.unlink()
        receipt_path.symlink_to(fragment_path)
        with self.assertRaisesRegex(CONTRACT.ContractError, "receipt must be a regular non-symlink"):
            CONTRACT.load_security_binding(self.root, VERSION, checked_at=NOW)
        receipt_path.unlink()
        receipt_path.write_bytes(CONTRACT.canonical_document_bytes(receipt))

        metadata = copy.deepcopy(self.metadata)
        metadata["fixedVersion"] = "3.2.5"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(CONTRACT.ContractError, "digest differs"):
            CONTRACT.load_security_binding(self.root, VERSION, checked_at=NOW)

    def test_binding_rejects_oversized_files_before_parsing(self) -> None:
        self._write_binding()
        metadata_path = self.root / f".lit/security-releases/{VERSION}.json"
        receipt_path = self.root / f".lit/security-release-intakes/{VERSION}.json"
        fragment_path = self.root / self.verified["changelogFragmentPath"]
        profiles_path = self.root / ".lit/security-release-profiles.json"

        for path, limit, label in (
            (metadata_path, CONTRACT.MAX_JSON_BYTES, "Security metadata exceeds"),
            (receipt_path, CONTRACT.MAX_JSON_BYTES, "Security intake receipt exceeds"),
            (
                fragment_path,
                CONTRACT.MAX_SECURITY_FRAGMENT_BYTES,
                "Security changelog fragment exceeds",
            ),
        ):
            original = path.read_bytes()
            with self.subTest(path=path):
                path.write_bytes(b"x" * (limit + 1))
                with self.assertRaisesRegex(CONTRACT.ContractError, label):
                    CONTRACT.load_security_binding(self.root, VERSION, checked_at=NOW)
                path.write_bytes(original)

        profiles_path.write_bytes(b"x" * (CONTRACT.MAX_JSON_BYTES + 1))
        with self.assertRaisesRegex(CONTRACT.ContractError, "profile registry exceeds"):
            CONTRACT.load_json_file(profiles_path, "profile registry")

    def test_bounded_read_fails_closed_without_nofollow_support(self) -> None:
        profiles_path = self.root / ".lit/security-release-profiles.json"
        with patch.object(CONTRACT.os, "O_NOFOLLOW", None):
            with self.assertRaisesRegex(CONTRACT.ContractError, "cannot prove non-symlink reads"):
                CONTRACT.load_json_file(profiles_path, "profile registry")

    def test_request_metadata_profile_and_pending_marker_contracts_are_exact(
        self,
    ) -> None:
        metadata = copy.deepcopy(self.metadata)
        for field, value, message in (
            ("issuedAt", "2026-08-08T22:31:00Z", "issuedAt differs"),
            ("expiresAt", "2026-09-09T22:30:00Z", "expiresAt differs"),
        ):
            with self.subTest(field=field):
                request = copy.deepcopy(self.request)
                request[field] = value
                with self.assertRaisesRegex(CONTRACT.ContractError, message):
                    CONTRACT.validate_request_metadata_binding(request, metadata)

        profiles = CONTRACT.load_json_file(
            self.root / ".lit/security-release-profiles.json",
            "profile registry",
        )
        CONTRACT.validate_profile_registry(profiles, PROFILE)
        profiles["profiles"][PROFILE]["unknown"] = True
        with self.assertRaisesRegex(CONTRACT.ContractError, "fields mismatch"):
            CONTRACT.validate_profile_registry(profiles, PROFILE)

        self._write_binding()
        self.assertIsNotNone(
            CONTRACT.load_release_security_binding(
                self.root,
                "3.2.3",
                VERSION,
                checked_at=NOW,
            )
        )
        self.assertIsNone(
            CONTRACT.load_release_security_binding(
                self.root,
                VERSION,
                "3.2.5",
                checked_at=NOW,
            )
        )
        future = self.root / ".lit/security-releases/3.2.6.json"
        future.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(CONTRACT.ContractError, "does not match"):
            CONTRACT.load_release_security_binding(
                self.root,
                VERSION,
                "3.2.5",
                checked_at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
