"""Tests for deterministic MLX-90 producer evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate-security-release-evidence.py"


class ProducerEvidenceTests(unittest.TestCase):
    def test_evidence_binds_every_release_asset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {}
            for name in ("artifact", "signature", "sbom", "provenance"):
                files[name] = root / name
                files[name].write_text(name, encoding="utf-8")
            output = root / "missing" / "evidence.json"
            cmd = [
                sys.executable,
                str(SCRIPT),
                "--id",
                "LIT-SEC-TEST",
                "--security-id",
                "LIT-SEC-TEST",
                "--affected-version",
                "3.1.0",
                "--version",
                "3.1.2",
                "--source-sha",
                "1" * 40,
                "--workflow-ref",
                "2" * 40,
                "--consumer",
                "lightning-it/container-ee-wunder-ansible-ubi9",
                "--acceptance-profile",
                "lit.supplementary/test",
                "--created-at",
                "2026-07-31T00:00:00Z",
                "--not-before",
                "2026-07-31T00:00:00Z",
                "--expires-at",
                "2026-08-07T00:00:00Z",
                "--output",
                str(output),
            ]
            for name, path in files.items():
                cmd += [f"--{name}", str(path), f"--{name}-url", f"https://example.invalid/{name}"]
            # The command contains only a fixed interpreter/script and test-owned arguments.
            subprocess.run(cmd, check=True, timeout=30)  # noqa: S603
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["artifact"]["digest"], "sha256:" + hashlib.sha256(b"artifact").hexdigest())
            for name in ("signature", "sbom", "provenance"):
                expected_digest = "sha256:" + hashlib.sha256(name.encode()).hexdigest()
                self.assertEqual(value["artifact"][name]["digest"], expected_digest)
            self.assertEqual(value["consumers"], ["lightning-it/container-ee-wunder-ansible-ubi9"])
            self.assertEqual(value["status"], "approved")
            self.assertNotIn("delivery", value)

            output_arg = cmd.index("--output") + 1
            target = root / "target.json"
            linked_output = root / "linked-output.json"
            linked_output.symlink_to(target)
            cmd[output_arg] = str(linked_output)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # noqa: S603
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not contain symlink components", result.stderr)
            self.assertFalse(target.exists())

            real_directory = root / "real-directory"
            real_directory.mkdir()
            linked_directory = root / "linked-directory"
            linked_directory.symlink_to(real_directory, target_is_directory=True)
            cmd[output_arg] = str(linked_directory / "evidence.json")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # noqa: S603
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must not contain symlink components", result.stderr)
            self.assertFalse((real_directory / "evidence.json").exists())


if __name__ == "__main__":
    unittest.main()
