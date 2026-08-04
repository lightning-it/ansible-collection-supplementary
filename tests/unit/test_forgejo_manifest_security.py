"""Regression tests for the Forgejo secret-bearing Pod manifest."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "roles" / "forgejo_deploy" / "tasks" / "deploy_pod.yml"
VERIFIER = ROOT / "scripts" / "verify-forgejo-manifest-security.py"
EVIDENCE_GENERATOR = ROOT / "scripts" / "generate-security-release-evidence.py"
PROFILE = "lit.supplementary/forgejo-manifest-secret-permissions-v1"


class ForgejoManifestSecurityTests(unittest.TestCase):
    def test_real_release_metadata_binds_the_ghsa_version_and_profile(self) -> None:
        registry_path = ROOT / ".lit" / "security-release-profiles.json"
        metadata_path = ROOT / ".lit" / "security-releases" / "3.2.2.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "description": (
                    "Verify the packaged Forgejo Pod manifest writer is root:root mode 0600 with no_log enabled."
                ),
                "releaseEligible": True,
            },
            registry["profiles"][PROFILE],
        )
        self.assertEqual(["GHSA-vjjf-wc74-gp86"], metadata["securityIdentifiers"])
        self.assertEqual("MLX90-GHSA-VJJF-WC74-GP86-3.2.2", metadata["evidenceId"])
        self.assertEqual("3.1.0", metadata["affectedVersion"])
        self.assertEqual("3.2.2", metadata["fixedVersion"])
        self.assertEqual(PROFILE, metadata["acceptanceProfile"])
        self.assertEqual(
            ["lightning-it/container-ee-wunder-ansible-ubi9"],
            metadata["consumers"],
        )
        generator = runpy.run_path(
            str(EVIDENCE_GENERATOR),
            run_name="security_release_evidence_module",
        )
        validated = generator["load_metadata"](
            metadata_path,
            registry_path,
            datetime(2026, 8, 4, 11, 31, 48, tzinfo=UTC),
        )
        self.assertEqual(metadata, validated)

    def test_secret_bearing_manifest_is_root_only_and_redacted(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        matches = [task for task in tasks if task.get("name") == "Render Forgejo Pod manifest"]
        self.assertEqual(1, len(matches))
        task = matches[0]
        template = task["ansible.builtin.template"]
        self.assertEqual("root", template.get("owner"))
        self.assertEqual("root", template.get("group"))
        self.assertEqual("0600", template.get("mode"))
        self.assertIs(task.get("no_log"), True)

    def test_packaged_offline_verifier_accepts_the_reviewed_source(self) -> None:
        result = subprocess.run(  # noqa: S603 -- fixed interpreter and repository-owned verifier.
            [sys.executable, str(VERIFIER)],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("Forgejo manifest security contract verified", result.stdout.strip())

    def test_packaged_verifier_rejects_a_relaxed_contract(self) -> None:
        module = runpy.run_path(str(VERIFIER), run_name="forgejo_manifest_security_module")
        original = yaml.load

        def relaxed_loader(stream: str, *, Loader: type[yaml.SafeLoader]) -> object:  # noqa: N803
            payload = original(stream, Loader=Loader)
            if isinstance(payload, list):
                for task in payload:
                    if isinstance(task, dict) and task.get("name") == "Render Forgejo Pod manifest":
                        task["ansible.builtin.template"]["mode"] = "0644"
            return payload

        with (
            patch.object(module["yaml"], "load", side_effect=relaxed_loader),
            self.assertRaisesRegex(SystemExit, "root:root with mode 0600"),
        ):
            module["verify"](ROOT)


if __name__ == "__main__":
    unittest.main()
