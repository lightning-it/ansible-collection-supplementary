"""Tests for reviewed changelog impact and stable release version selection."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release-version.py"
SPEC = importlib.util.spec_from_file_location("release_version", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"unable to import {SCRIPT}")
VERSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERSION)


class ReleaseVersionTests(unittest.TestCase):
    def _fixture(self, category: str, *, version: str = "1.40.0", root: Path | None = None) -> tuple[Path, Path]:
        root = root or Path(self.temporary.name)
        galaxy = root / "galaxy.yml"
        galaxy.write_text(f"---\nnamespace: lit\nname: supplementary\nversion: {version}\n", encoding="utf-8")
        fragments = root / "fragments"
        fragments.mkdir()
        (fragments / "change.yml").write_text(
            f"---\n{category}:\n  - Reviewed compatibility impact.\n",
            encoding="utf-8",
        )
        return galaxy, fragments

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def _security_contract(self, root: Path) -> tuple[dict[str, object], datetime]:
        contract = VERSION.CONTRACT
        version = "3.2.4"
        evidence_id = "MLX90-KEYCLOAK-26.7.1-3.2.4"
        profile = "lit.supplementary/keycloak-26.7.1-security-v1"
        checked_at = datetime(2026, 8, 8, 23, 0, tzinfo=UTC)
        profiles = root / ".lit/security-release-profiles.json"
        profiles.parent.mkdir(parents=True)
        profiles.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "profiles": {
                        profile: {
                            "description": "Exact Keycloak acceptance",
                            "releaseEligible": True,
                        }
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        metadata = {
            "schemaVersion": 1,
            "evidenceId": evidence_id,
            "createdAt": "2026-08-08T22:30:00Z",
            "securityIdentifiers": ["CVE-2026-9793"],
            "affectedVersion": "3.2.3",
            "fixedVersion": version,
            "consumers": [contract.CONSUMER_REPOSITORY],
            "acceptanceProfile": profile,
            "validity": {
                "notBefore": "2026-08-08T22:30:00Z",
                "expiresAt": "2026-09-08T22:30:00Z",
                "revoked": False,
            },
        }
        metadata_raw = (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode()
        metadata_path = root / f".lit/security-releases/{version}.json"
        metadata_path.parent.mkdir(parents=True)
        metadata_path.write_bytes(metadata_raw)
        candidate_digest = "sha256:" + "c" * 64
        chain_id = contract.compute_chain_id(
            repository=contract.PRODUCER_REPOSITORY,
            repository_id=contract.PRODUCER_REPOSITORY_ID,
            base_sha="a" * 40,
            candidate_head_sha="b" * 40,
            candidate_diff_sha256=candidate_digest,
            evidence_id=evidence_id,
            fixed_version=version,
            acceptance_profile=profile,
        )
        request = {
            "schemaVersion": 2,
            "event": "mlx90-security-release",
            "repository": contract.PRODUCER_REPOSITORY,
            "repositoryId": contract.PRODUCER_REPOSITORY_ID,
            "baseSha": "a" * 40,
            "candidateRef": "develop",
            "candidateBaseSha": "a" * 40,
            "candidateHeadSha": "b" * 40,
            "candidateDiffSha256": candidate_digest,
            "evidenceId": evidence_id,
            "fixedVersion": version,
            "acceptanceProfile": profile,
            "metadataSha256": contract.sha256_bytes(metadata_raw),
            "chainId": chain_id,
            "issuedAt": "2026-08-08T22:30:00Z",
            "expiresAt": "2026-09-08T22:30:00Z",
            "humanActions": 0,
        }
        fragment = contract.canonical_security_fragment_bytes(["Keycloak fix."])
        verified = {
            "schemaVersion": 2,
            "chainId": chain_id,
            "branch": f"security-release/{evidence_id}",
            "baseSha": "a" * 40,
            "candidateBaseSha": "a" * 40,
            "candidateHeadSha": "b" * 40,
            "candidateDiffSha256": candidate_digest,
            "evidenceId": evidence_id,
            "fixedVersion": version,
            "metadataPath": f".lit/security-releases/{version}.json",
            "metadataSha256": contract.sha256_bytes(metadata_raw),
            "acceptanceProfile": profile,
            "changelogFragmentPath": "changelogs/fragments/keycloak-security.yml",
            "changelogFragmentSha256": contract.sha256_bytes(fragment),
            "changedPaths": [
                f".lit/security-releases/{version}.json",
                "changelogs/fragments/keycloak-security.yml",
                "roles/keycloak_deploy/defaults/main.yml",
            ],
            "humanActions": 0,
        }
        intake = contract.build_intake_receipt(
            request,
            verified,
            checked_at=checked_at,
            workflow_run_id="123456",
            workflow_attempt="1",
            workflow_ref=(
                f"{contract.PRODUCER_REPOSITORY}/.github/workflows/security-release-intake.yml@refs/heads/main"
            ),
            workflow_event="workflow_dispatch",
            workflow_actor=contract.RELEASE_APP_LOGIN,
            workflow_triggering_actor=contract.RELEASE_APP_LOGIN,
            observed_automation=contract.RELEASE_APP_IDENTITY,
        )
        intake_path = root / f".lit/security-release-intakes/{version}.json"
        intake_path.parent.mkdir(parents=True)
        intake_path.write_bytes(contract.canonical_document_bytes(intake))
        fragment_path = root / verified["changelogFragmentPath"]
        fragment_path.parent.mkdir(parents=True)
        fragment_path.write_bytes(fragment)
        return intake, checked_at

    def test_highest_reviewed_impact_selects_exact_next_stable_version(self) -> None:
        cases = (
            ("bugfixes", "patch", "1.40.1"),
            ("minor_changes", "minor", "1.41.0"),
            ("major_changes", "major", "2.0.0"),
        )
        for category, impact, expected in cases:
            with self.subTest(category=category), tempfile.TemporaryDirectory() as directory:
                galaxy, fragments = self._fixture(category, root=Path(directory))
                resolved = VERSION.resolve_version(galaxy, fragments)
                self.assertEqual(impact, resolved["impact"])
                self.assertEqual(expected, resolved["version"])
                self.assertEqual(["change.yml"], resolved["fragments"])
                self.assertRegex(resolved["fragment_sha256"][0]["sha256"], r"^[0-9a-f]{64}$")

    def test_preparation_receipt_binds_fragments_version_and_workflow(self) -> None:
        galaxy, fragments = self._fixture("minor_changes")
        resolution = VERSION.resolve_version(galaxy, fragments)
        repository = "lightning-it/ansible-collection-supplementary"
        repository_id = "123456"
        base_sha = "a" * 40
        receipt = VERSION.build_preparation_receipt(
            resolution,
            repository=repository,
            repository_id=repository_id,
            base_sha=base_sha,
            workflow_run_id="98765",
            workflow_attempt="2",
            workflow_ref=(f"{repository}/.github/workflows/release-prepare.yml@refs/heads/main"),
            workflow_event="workflow_dispatch",
            workflow_actor="release-operator",
            root=Path(self.temporary.name),
        )
        VERSION.verify_preparation_receipt(
            receipt,
            expected_repository=repository,
            expected_repository_id=repository_id,
            expected_base_sha=base_sha,
            expected_version="1.41.0",
            root=Path(self.temporary.name),
        )
        fragment = fragments / "change.yml"
        self.assertEqual("change.yml", receipt["fragments"][0]["path"])
        self.assertEqual(
            hashlib.sha256(fragment.read_bytes()).hexdigest(),
            receipt["fragments"][0]["sha256"],
        )
        self.assertEqual(2, receipt["schema_version"])
        self.assertEqual("normal", receipt["release_mode"])
        self.assertIsNone(receipt["chain_id"])
        self.assertIsNone(receipt["security"])

        receipt_path = Path(self.temporary.name) / "release-preparation.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(VERSION.VersionError, "not canonical JSON"):
            VERSION._load_unique_json(receipt_path)
        receipt_path.write_bytes(VERSION.CONTRACT.canonical_document_bytes(receipt))
        self.assertEqual(receipt, VERSION._load_unique_json(receipt_path))

        for label, mutate in (
            ("version", lambda value: value.__setitem__("next_version", "1.41.1")),
            ("digest", lambda value: value["fragments"][0].__setitem__("sha256", "z" * 64)),
            ("workflow", lambda value: value["workflow"].__setitem__("path", ".github/workflows/other.yml")),
        ):
            with self.subTest(label=label):
                tampered = json.loads(json.dumps(receipt))
                mutate(tampered)
                with self.assertRaises(VERSION.VersionError):
                    VERSION.verify_preparation_receipt(
                        tampered,
                        expected_repository=repository,
                        expected_repository_id=repository_id,
                        expected_base_sha=base_sha,
                        expected_version="1.41.0",
                        root=Path(self.temporary.name),
                    )

    def test_security_preparation_receipt_binds_exact_v2_intake(self) -> None:
        root = Path(self.temporary.name)
        galaxy, _fragments = self._fixture("security_fixes", version="3.2.3", root=root)
        _intake, checked_at = self._security_contract(root)
        fragments = root / "changelogs/fragments"
        resolution = VERSION.resolve_version(galaxy, fragments)
        contract = VERSION.CONTRACT
        receipt = VERSION.build_preparation_receipt(
            resolution,
            repository=contract.PRODUCER_REPOSITORY,
            repository_id=contract.PRODUCER_REPOSITORY_ID,
            base_sha="d" * 40,
            workflow_run_id="98765",
            workflow_attempt="2",
            workflow_ref=(f"{contract.PRODUCER_REPOSITORY}/.github/workflows/release-prepare.yml@refs/heads/main"),
            workflow_event="push",
            workflow_actor=contract.RELEASE_APP_LOGIN,
            root=root,
            checked_at=checked_at,
        )
        VERSION.verify_preparation_receipt(
            receipt,
            expected_repository=contract.PRODUCER_REPOSITORY,
            expected_repository_id=contract.PRODUCER_REPOSITORY_ID,
            expected_base_sha="d" * 40,
            expected_version="3.2.4",
            root=root,
            checked_at=checked_at,
        )
        self.assertEqual("security", receipt["release_mode"])
        self.assertRegex(str(receipt["chain_id"]), r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(0, receipt["security"]["human_actions"])
        self.assertEqual(
            f".lit/security-release-intakes/{resolution['version']}.json",
            receipt["security"]["intake_receipt_path"],
        )

        for label, mutate in (
            ("schema-type", lambda value: value.__setitem__("schema_version", True)),
            ("mode", lambda value: value.__setitem__("release_mode", "normal")),
            ("chain", lambda value: value.__setitem__("chain_id", "sha256:" + "0" * 64)),
            ("intake", lambda value: value["security"].__setitem__("intake_receipt_sha256", "sha256:" + "0" * 64)),
            ("actor", lambda value: value["workflow"].__setitem__("actor", "human")),
            ("event", lambda value: value["workflow"].__setitem__("event", "workflow_dispatch")),
            ("run-id-type", lambda value: value["workflow"].__setitem__("run_id", 98765)),
            ("human-actions-type", lambda value: value["security"].__setitem__("human_actions", False)),
        ):
            with self.subTest(label=label):
                tampered = json.loads(json.dumps(receipt))
                mutate(tampered)
                with self.assertRaises(VERSION.VersionError):
                    VERSION.verify_preparation_receipt(
                        tampered,
                        expected_repository=contract.PRODUCER_REPOSITORY,
                        expected_repository_id=contract.PRODUCER_REPOSITORY_ID,
                        expected_base_sha="d" * 40,
                        expected_version="3.2.4",
                        root=root,
                        checked_at=checked_at,
                    )

        wrong_fragment = json.loads(json.dumps(receipt))
        wrong_fragment["fragments"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(VERSION.VersionError, "immutable intake fragment digest"):
            VERSION.verify_preparation_receipt(
                wrong_fragment,
                expected_repository=contract.PRODUCER_REPOSITORY,
                expected_repository_id=contract.PRODUCER_REPOSITORY_ID,
                expected_base_sha="d" * 40,
                expected_version="3.2.4",
                root=root,
                checked_at=checked_at,
            )

        fragment = fragments / "keycloak-security.yml"
        original_fragment = fragment.read_bytes()
        fragment.write_bytes(contract.canonical_security_fragment_bytes(["Different fix."]))
        with self.assertRaisesRegex(VERSION.VersionError, "fragment digest differs"):
            VERSION.build_preparation_receipt(
                resolution,
                repository=contract.PRODUCER_REPOSITORY,
                repository_id=contract.PRODUCER_REPOSITORY_ID,
                base_sha="d" * 40,
                workflow_run_id="98765",
                workflow_attempt="2",
                workflow_ref=(f"{contract.PRODUCER_REPOSITORY}/.github/workflows/release-prepare.yml@refs/heads/main"),
                workflow_event="push",
                workflow_actor=contract.RELEASE_APP_LOGIN,
                root=root,
                checked_at=checked_at,
            )
        fragment.write_bytes(original_fragment)

        fragment.unlink()
        with self.assertRaisesRegex(VERSION.VersionError, "Security changelog fragment"):
            VERSION.verify_preparation_receipt(
                receipt,
                expected_repository=contract.PRODUCER_REPOSITORY,
                expected_repository_id=contract.PRODUCER_REPOSITORY_ID,
                expected_base_sha="d" * 40,
                expected_version="3.2.4",
                root=root,
                checked_at=checked_at,
            )
        fragment.write_bytes(original_fragment)
        VERSION.verify_preparation_receipt(
            receipt,
            expected_repository=contract.PRODUCER_REPOSITORY,
            expected_repository_id=contract.PRODUCER_REPOSITORY_ID,
            expected_base_sha="d" * 40,
            expected_version="3.2.4",
            root=root,
            checked_at=checked_at,
        )

    def test_partial_security_marker_never_falls_back_to_normal(self) -> None:
        root = Path(self.temporary.name)
        galaxy, _fragments = self._fixture("security_fixes", version="3.2.3", root=root)
        _intake, checked_at = self._security_contract(root)
        fragments = root / "changelogs/fragments"
        (root / ".lit/security-release-intakes/3.2.4.json").unlink()
        with self.assertRaisesRegex(VERSION.VersionError, "partial Security marker"):
            VERSION.build_preparation_receipt(
                VERSION.resolve_version(galaxy, fragments),
                repository=VERSION.CONTRACT.PRODUCER_REPOSITORY,
                repository_id=VERSION.CONTRACT.PRODUCER_REPOSITORY_ID,
                base_sha="d" * 40,
                workflow_run_id="98765",
                workflow_attempt="1",
                workflow_ref=(
                    f"{VERSION.CONTRACT.PRODUCER_REPOSITORY}/.github/workflows/release-prepare.yml@refs/heads/main"
                ),
                workflow_event="push",
                workflow_actor=VERSION.CONTRACT.RELEASE_APP_LOGIN,
                root=root,
                checked_at=checked_at,
            )

    def test_pending_security_marker_cannot_fall_back_to_normal_target(self) -> None:
        root = Path(self.temporary.name)
        galaxy, fragments = self._fixture("minor_changes", version="3.2.3", root=root)
        _intake, checked_at = self._security_contract(root)
        resolution = VERSION.resolve_version(galaxy, fragments)
        self.assertEqual("3.3.0", resolution["version"])
        with self.assertRaisesRegex(VERSION.VersionError, "does not match"):
            VERSION.build_preparation_receipt(
                resolution,
                repository=VERSION.CONTRACT.PRODUCER_REPOSITORY,
                repository_id=VERSION.CONTRACT.PRODUCER_REPOSITORY_ID,
                base_sha="d" * 40,
                workflow_run_id="98765",
                workflow_attempt="1",
                workflow_ref=(
                    f"{VERSION.CONTRACT.PRODUCER_REPOSITORY}/.github/workflows/release-prepare.yml@refs/heads/main"
                ),
                workflow_event="workflow_dispatch",
                workflow_actor="release-operator",
                root=root,
                checked_at=checked_at,
            )

    def test_security_target_selects_only_bound_patch_fragment(self) -> None:
        root = Path(self.temporary.name)
        galaxy = root / "galaxy.yml"
        galaxy.write_text(
            "---\nnamespace: lit\nname: supplementary\nversion: 3.2.3\n",
            encoding="utf-8",
        )
        _intake, checked_at = self._security_contract(root)
        fragments = root / "changelogs/fragments"
        future_fragment = fragments / "future-feature.yml"
        future_fragment.write_text(
            "---\nminor_changes:\n  - Reviewed future feature.\n",
            encoding="utf-8",
        )

        normal = VERSION.resolve_version(galaxy, fragments)
        self.assertEqual("3.3.0", normal["version"])
        resolution = VERSION.resolve_version(
            galaxy,
            fragments,
            security_target="3.2.4",
            root=root,
            checked_at=checked_at,
        )
        self.assertEqual("patch", resolution["impact"])
        self.assertEqual("3.2.4", resolution["version"])
        self.assertEqual(["keycloak-security.yml"], resolution["fragments"])
        self.assertEqual(
            ["keycloak-security.yml"],
            [fragment["path"] for fragment in resolution["fragment_sha256"]],
        )

        receipt = VERSION.build_preparation_receipt(
            resolution,
            repository=VERSION.CONTRACT.PRODUCER_REPOSITORY,
            repository_id=VERSION.CONTRACT.PRODUCER_REPOSITORY_ID,
            base_sha="d" * 40,
            workflow_run_id="98765",
            workflow_attempt="1",
            workflow_ref=(
                f"{VERSION.CONTRACT.PRODUCER_REPOSITORY}/.github/workflows/release-prepare.yml@refs/heads/main"
            ),
            workflow_event="push",
            workflow_actor=VERSION.CONTRACT.RELEASE_APP_LOGIN,
            root=root,
            checked_at=checked_at,
        )
        self.assertEqual(["keycloak-security.yml"], [fragment["path"] for fragment in receipt["fragments"]])
        self.assertTrue(future_fragment.is_file())

    def test_security_target_rejects_normal_requested_version_and_non_patch_target(self) -> None:
        root = Path(self.temporary.name)
        galaxy = root / "galaxy.yml"
        galaxy.write_text(
            "---\nnamespace: lit\nname: supplementary\nversion: 3.2.3\n",
            encoding="utf-8",
        )
        _intake, checked_at = self._security_contract(root)
        fragments = root / "changelogs/fragments"
        with self.assertRaisesRegex(VERSION.VersionError, "mutually exclusive"):
            VERSION.resolve_version(
                galaxy,
                fragments,
                "3.2.4",
                security_target="3.2.4",
                root=root,
                checked_at=checked_at,
            )
        with self.assertRaisesRegex(VERSION.VersionError, "does not match"):
            VERSION.resolve_version(
                galaxy,
                fragments,
                security_target="3.2.5",
                root=root,
                checked_at=checked_at,
            )

    def test_manual_version_must_equal_reviewed_impact(self) -> None:
        galaxy, fragments = self._fixture("major_changes")
        self.assertEqual("2.0.0", VERSION.resolve_version(galaxy, fragments, "2.0.0")["version"])
        for requested in ("1.41.0", "2.0.1", "2.0.0-rc.1", "v2.0.0", "02.0.0"):
            with self.subTest(requested=requested), self.assertRaises(VERSION.VersionError):
                VERSION.resolve_version(galaxy, fragments, requested)

    def test_unknown_empty_neutral_only_and_duplicate_categories_fail_closed(self) -> None:
        cases = {
            "unknown": "---\nfeatures:\n  - change\n",
            "empty": "---\nminor_changes: []\n",
            "neutral": "---\nknown_issues:\n  - issue\n",
            "duplicate": "---\nminor_changes:\n  - one\nminor_changes:\n  - two\n",
        }
        for label, content in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                galaxy, fragments = self._fixture("bugfixes", root=Path(directory))
                (fragments / "change.yml").write_text(content, encoding="utf-8")
                with self.assertRaises(VERSION.VersionError):
                    VERSION.resolve_version(galaxy, fragments)

    def test_repository_release_state_is_consistent(self) -> None:
        fragments_root = ROOT / "changelogs" / "fragments"
        fragments = sorted(path for path in fragments_root.iterdir() if path.suffix.lower() in {".yml", ".yaml"})
        if fragments:
            resolved = VERSION.resolve_version(ROOT / "galaxy.yml", fragments_root)
            galaxy = VERSION._load_yaml(ROOT / "galaxy.yml")
            self.assertNotEqual(str(galaxy["version"]), resolved["version"])
            return

        receipt = VERSION._load_unique_json(ROOT / "changelogs" / "release-preparation.json")
        galaxy = VERSION._load_yaml(ROOT / "galaxy.yml")
        self.assertEqual(str(galaxy["version"]), receipt["next_version"])


if __name__ == "__main__":
    unittest.main()
