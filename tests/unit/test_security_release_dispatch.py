"""Tests for the immutable MLX-90 consumer dispatch contract."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/dispatch-security-release.py"
EVIDENCE_URL = (
    "https://github.com/lightning-it/ansible-collection-supplementary/"
    "releases/download/v3.1.2/security-release-evidence.json"
)
DIGEST = "sha256:" + "a" * 64


class SecurityReleaseDispatchTests(unittest.TestCase):
    def run_dispatch(
        self,
        root: Path,
        *,
        evidence_url: str = EVIDENCE_URL,
        digest: str = DIGEST,
        include_token: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        fake_bin = root / "bin"
        fake_bin.mkdir()
        capture = root / "arguments"
        fake_gh = fake_bin / "gh"
        fake_gh.write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\nprintf "%s\\n" "$@" >"${MLX90_CAPTURE:?}"\n',
            encoding="utf-8",
        )
        fake_gh.chmod(0o700)
        environment = os.environ.copy()
        environment.update(
            {
                "MLX90_CAPTURE": str(capture),
                "PATH": f"{fake_bin}:{environment['PATH']}",
            }
        )
        if include_token:
            environment["GH_TOKEN"] = "test-app-token"  # noqa: S105 -- fake process-local test value.
        else:
            environment.pop("GH_TOKEN", None)
        command = [
            sys.executable,
            str(SCRIPT),
            "--evidence-url",
            evidence_url,
            "--evidence-sha256",
            digest,
        ]
        result = subprocess.run(  # noqa: S603 -- fixed interpreter/script and test-owned fake PATH.
            command,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
        )
        return result, capture

    def test_dispatch_contains_only_fixed_ref_and_immutable_evidence_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result, capture = self.run_dispatch(Path(temporary))
            self.assertEqual(result.returncode, 0, result.stderr)
            arguments = capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                arguments,
                [
                    "api",
                    "--method",
                    "POST",
                    "repos/lightning-it/container-ee-wunder-ansible-ubi9/actions/workflows/"
                    "security-release-update.yml/dispatches",
                    "-f",
                    "ref=main",
                    "-f",
                    f"inputs[evidence_url]={EVIDENCE_URL}",
                    "-f",
                    f"inputs[evidence_sha256]={DIGEST}",
                ],
            )
            serialized = "\n".join(arguments)
            self.assertNotIn("evidence_id", serialized)
            self.assertNotIn("version", serialized)
            self.assertNotIn("consumer", serialized)

    def test_dispatch_has_a_fixed_network_timeout(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("DISPATCH_TIMEOUT_SECONDS = 60", source)
        self.assertIn("timeout=DISPATCH_TIMEOUT_SECONDS", source)

    def test_invalid_url_digest_and_missing_app_token_never_dispatch(self) -> None:
        cases = (
            {"evidence_url": "https://example.invalid/security-release-evidence.json"},
            {"digest": "a" * 64},
            {"include_token": False},
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                result, capture = self.run_dispatch(Path(temporary), **case)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(capture.exists())


if __name__ == "__main__":
    unittest.main()
