"""Tests for deterministic, fail-closed MLX-90 producer evidence."""

from __future__ import annotations

import hashlib
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate-security-release-evidence.py"
CHECKED_AT = "2026-08-02T12:00:00Z"
SOURCE_SHA = "1" * 40
CONSUMER = "lightning-it/container-ee-wunder-ansible-ubi9"
PROFILE = "lit.supplementary/approved-test"


class ProducerEvidenceTests(unittest.TestCase):
    def make_inputs(
        self,
        root: Path,
        *,
        mutate: Callable[[dict[str, Any]], None] | None = None,
        release_eligible: bool = True,
    ) -> tuple[Path, Path, dict[str, Path]]:
        metadata_root = root / ".lit" / "security-releases"
        metadata_root.mkdir(parents=True)
        metadata: dict[str, Any] = {
            "schemaVersion": 1,
            "evidenceId": "LIT-SEC-TEST",
            "createdAt": "2026-08-02T00:00:00Z",
            "securityIdentifiers": ["LIT-SEC-TEST", "CVE-2026-12345"],
            "affectedVersion": "3.1.0",
            "fixedVersion": "3.1.2",
            "consumers": [CONSUMER],
            "acceptanceProfile": PROFILE,
            "validity": {
                "notBefore": "2026-08-02T00:00:00Z",
                "expiresAt": "2026-08-09T00:00:00Z",
                "revoked": False,
            },
        }
        if mutate is not None:
            mutate(metadata)
        metadata_path = metadata_root / f"{metadata['fixedVersion']}.json"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        profiles = root / ".lit" / "security-release-profiles.json"
        profiles.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "profiles": {
                        PROFILE: {
                            "description": "Unit-test-only release-eligible profile.",
                            "releaseEligible": release_eligible,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        assets = {
            "artifact": root / "lit-supplementary-3.1.2.tar.gz",
            "signature": root / "lit-supplementary-3.1.2.tar.gz.sigstore.json",
            "sbom": root / "sbom.cdx.json",
            "provenance": root / "provenance.json",
        }
        for name, path in assets.items():
            path.write_text(name, encoding="utf-8")
        return metadata_path, profiles, assets

    def command(
        self,
        action: str,
        metadata: Path,
        profiles: Path,
        assets: dict[str, Path],
        target: Path,
    ) -> list[str]:
        command = [
            sys.executable,
            str(SCRIPT),
            action,
            "--metadata",
            str(metadata),
            "--profiles",
            str(profiles),
            "--source-sha",
            SOURCE_SHA,
            "--checked-at",
            CHECKED_AT,
        ]
        for name, path in assets.items():
            command.extend((f"--{name}", str(path)))
        command.extend(("--output" if action == "generate" else "--evidence", str(target)))
        return command

    def run_command(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 -- fixed interpreter/script and test-owned arguments.
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_evidence_is_deterministic_and_binds_every_release_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, profiles, assets = self.make_inputs(root)
            output = root / "output" / "security-release-evidence.json"
            command = self.command("generate", metadata, profiles, assets, output)
            result = self.run_command(command)
            self.assertEqual(result.returncode, 0, result.stderr)

            value = json.loads(output.read_text(encoding="utf-8"))
            artifact_digest = "sha256:" + hashlib.sha256(b"artifact").hexdigest()
            self.assertEqual(value["artifact"]["digest"], artifact_digest)
            self.assertEqual(value["producer"]["sourceSha"], SOURCE_SHA)
            self.assertEqual(value["producer"]["workflowRef"], SOURCE_SHA)
            self.assertEqual(value["consumers"], [CONSUMER])
            self.assertEqual(value["status"], "approved")
            self.assertNotIn("delivery", value)
            for name in ("signature", "sbom", "provenance"):
                expected = "sha256:" + hashlib.sha256(name.encode()).hexdigest()
                self.assertEqual(value["artifact"][name]["digest"], expected)
                self.assertRegex(
                    value["artifact"][name]["url"],
                    rf"/releases/download/v3\.1\.2/{assets[name].name}$",
                )

            verification = self.run_command(self.command("verify", metadata, profiles, assets, output))
            self.assertEqual(verification.returncode, 0, verification.stderr)
            replacement = self.run_command(command)
            self.assertNotEqual(replacement.returncode, 0)
            self.assertIn("refusing to replace existing evidence output", replacement.stderr)

    def test_digest_mismatch_is_rejected_after_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, profiles, assets = self.make_inputs(root)
            output = root / "security-release-evidence.json"
            result = self.run_command(self.command("generate", metadata, profiles, assets, output))
            self.assertEqual(result.returncode, 0, result.stderr)
            assets["artifact"].write_text("changed artifact", encoding="utf-8")
            verification = self.run_command(self.command("verify", metadata, profiles, assets, output))
            self.assertNotEqual(verification.returncode, 0)
            self.assertIn("differs from authoritative metadata", verification.stderr)

    def test_invalid_expired_revoked_and_non_allowlisted_metadata_fail_closed(self) -> None:
        cases: tuple[tuple[str, Callable[[dict[str, Any]], None], str], ...] = (
            (
                "invalid identifier",
                lambda value: value.__setitem__("securityIdentifiers", ["security-label"]),
                "canonical Security IDs",
            ),
            (
                "invalid affected version",
                lambda value: value.__setitem__("affectedVersion", "old"),
                "affectedVersion must be a stable semantic version",
            ),
            (
                "expired",
                lambda value: value["validity"].__setitem__("expiresAt", "2026-08-02T12:00:00Z"),
                "not currently valid",
            ),
            (
                "revoked",
                lambda value: value["validity"].__setitem__("revoked", True),
                "metadata is revoked",
            ),
            (
                "consumer",
                lambda value: value.__setitem__("consumers", [CONSUMER, "lightning-it/extra"]),
                "must contain exactly the approved repository",
            ),
        )
        for label, mutation, message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                metadata, profiles, assets = self.make_inputs(root, mutate=mutation)
                output = root / "security-release-evidence.json"
                result = self.run_command(self.command("generate", metadata, profiles, assets, output))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(output.exists())

    def test_missing_or_non_releaseable_profile_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, profiles, assets = self.make_inputs(root, release_eligible=False)
            output = root / "security-release-evidence.json"
            result = self.run_command(self.command("generate", metadata, profiles, assets, output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("explicitly non-releaseable", result.stderr)

            registry = json.loads(profiles.read_text(encoding="utf-8"))
            registry["profiles"].clear()
            profiles.write_text(json.dumps(registry), encoding="utf-8")
            result = self.run_command(self.command("generate", metadata, profiles, assets, output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not in the fixed producer allowlist", result.stderr)

    def test_symlinked_output_is_rejected_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, profiles, assets = self.make_inputs(root)
            target = root / "target.json"
            output = root / "security-release-evidence.json"
            output.symlink_to(target)
            result = self.run_command(self.command("generate", metadata, profiles, assets, output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not contain symlink components", result.stderr)
            self.assertFalse(target.exists())

    def test_unrecognized_root_level_symlink_is_rejected(self) -> None:
        module = runpy.run_path(str(SCRIPT), run_name="mlx90_evidence_module")
        has_symlink_component = module["has_symlink_component"]
        with patch.object(
            Path,
            "is_symlink",
            autospec=True,
            side_effect=lambda candidate: candidate == Path("/untrusted-root"),
        ):
            self.assertTrue(has_symlink_component(Path("/untrusted-root/repository/evidence.json")))

    def test_only_the_canonical_macos_var_alias_is_accepted(self) -> None:
        module = runpy.run_path(str(SCRIPT), run_name="mlx90_evidence_module")
        has_symlink_component = module["has_symlink_component"]
        with (
            patch.object(
                Path,
                "is_symlink",
                autospec=True,
                side_effect=lambda candidate: candidate == Path("/var"),
            ),
            patch.object(
                Path,
                "resolve",
                autospec=True,
                side_effect=lambda candidate, *, strict: (
                    Path("/private/var") if candidate == Path("/var") and strict else candidate
                ),
            ),
        ):
            self.assertFalse(has_symlink_component(Path("/var/folders/repository/evidence.json")))

        with (
            patch.object(
                Path,
                "is_symlink",
                autospec=True,
                side_effect=lambda candidate: candidate == Path("/var"),
            ),
            patch.object(
                Path,
                "resolve",
                autospec=True,
                return_value=Path("/attacker-controlled"),
            ),
        ):
            self.assertTrue(has_symlink_component(Path("/var/folders/repository/evidence.json")))

    def test_symlinked_metadata_grandparent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, profiles, assets = self.make_inputs(root)
            real_metadata_root = root / "review-bypass"
            (root / ".lit").rename(real_metadata_root)
            (root / ".lit").symlink_to(real_metadata_root, target_is_directory=True)

            output = root / "security-release-evidence.json"
            result = self.run_command(self.command("generate", metadata, profiles, assets, output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be a regular non-symlink file", result.stderr)
            self.assertFalse(output.exists())

    def test_symlinked_output_grandparent_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, profiles, assets = self.make_inputs(root)
            real_output_root = root / "real-output"
            real_output_root.mkdir()
            linked_output_root = root / "linked-output"
            linked_output_root.symlink_to(real_output_root, target_is_directory=True)
            output = linked_output_root / "nested" / "security-release-evidence.json"

            result = self.run_command(self.command("generate", metadata, profiles, assets, output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not contain symlink components", result.stderr)
            self.assertFalse((real_output_root / "nested").exists())

    def test_parent_traversal_cannot_hide_a_symlink_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            metadata, profiles, assets = self.make_inputs(root)
            linked_output_root = root / "linked-output"
            linked_output_root.symlink_to(root, target_is_directory=True)
            output = linked_output_root / ".." / "escaped-evidence.json"

            result = self.run_command(self.command("generate", metadata, profiles, assets, output))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not contain symlink components", result.stderr)
            self.assertFalse((root.parent / "escaped-evidence.json").exists())


if __name__ == "__main__":
    unittest.main()
