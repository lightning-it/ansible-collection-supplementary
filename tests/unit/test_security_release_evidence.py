import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/generate-security-release-evidence.py"


class ProducerEvidenceTests(unittest.TestCase):
    def test_evidence_binds_every_release_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {}
            for name in ("artifact", "signature", "sbom", "provenance"):
                files[name] = root / name
                files[name].write_text(name)
            output = root / "evidence.json"
            cmd = [
                "python3",
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
            subprocess.run(cmd, check=True)  # noqa: S603
            value = json.loads(output.read_text())
            self.assertEqual(value["artifact"]["digest"], "sha256:" + hashlib.sha256(b"artifact").hexdigest())
            for name in ("signature", "sbom", "provenance"):
                expected_digest = "sha256:" + hashlib.sha256(name.encode()).hexdigest()
                self.assertEqual(value["artifact"][name]["digest"], expected_digest)
            self.assertEqual(value["consumers"], ["lightning-it/container-ee-wunder-ansible-ubi9"])
            self.assertEqual(value["status"], "approved")
            self.assertNotIn("delivery", value)


if __name__ == "__main__":
    unittest.main()
