from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "nexus-galaxy-v3-stage.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nexus_galaxy_v3_stage", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Nexus staging script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script()


class FakeClient:
    def __init__(self, candidate: Path, *, existing: bytes | None = None) -> None:
        self.candidate = candidate
        self.remote = existing
        self.uploads = 0
        self.urls: list[str] = []

    def readback(self, url: str, destination: Path) -> int | None:
        self.urls.append(url)
        if self.remote is None:
            return None
        destination.write_bytes(self.remote)
        return len(self.remote)

    def upload(self, url: str, candidate: Path) -> None:
        self.urls.append(url)
        self.uploads += 1
        self.remote = candidate.read_bytes()


class NexusGalaxyV3StageTests(unittest.TestCase):
    def candidate(self, root: Path) -> Path:
        path = root / "lit-supplementary-3.2.4.tar.gz"
        path.write_bytes(b"immutable-collection-candidate")
        return path

    def test_new_candidate_is_uploaded_then_proven_by_exact_readback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = self.candidate(root)
            output = root / "evidence" / "nexus-stage.json"
            client = FakeClient(candidate)

            payload = MODULE.stage(
                candidate,
                "https://nexus.example.test/repository/ansible-security-candidates/",
                "ansible-security-candidates",
                "unused",
                "unused",
                output,
                client=client,
            )

            self.assertEqual(1, client.uploads)
            self.assertEqual(3, len(client.urls))
            self.assertTrue(payload["readback"]["verified"])
            self.assertTrue(payload["uploaded"])
            self.assertEqual(payload, json.loads(output.read_text(encoding="utf-8")))
            self.assertFalse(any(output.parent.glob(".*.nexus-readback")))

    def test_existing_exact_candidate_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = self.candidate(root)
            client = FakeClient(candidate, existing=candidate.read_bytes())

            payload = MODULE.stage(
                candidate,
                "https://nexus.example.test/repository/ansible-hosted",
                "ansible-hosted",
                "unused",
                "unused",
                root / "stage.json",
                client=client,
            )

            self.assertEqual(0, client.uploads)
            self.assertFalse(payload["uploaded"])

    def test_existing_different_bytes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate = self.candidate(root)
            client = FakeClient(candidate, existing=b"substituted")

            with self.assertRaisesRegex(MODULE.StageError, "differ"):
                MODULE.stage(
                    candidate,
                    "https://nexus.example.test/repository/ansible-hosted",
                    "ansible-hosted",
                    "unused",
                    "unused",
                    root / "stage.json",
                    client=client,
                )
            self.assertEqual(0, client.uploads)

    def test_repository_url_is_https_credential_free_and_exact(self) -> None:
        for value, repository in (
            ("http://nexus.example.test/repository/ansible-hosted", "ansible-hosted"),
            ("https://user:pass@nexus.example.test/repository/ansible-hosted", "ansible-hosted"),
            ("https://nexus.example.test/repository/other", "ansible-hosted"),
            ("https://nexus.example.test/repository/ansible-hosted?token=x", "ansible-hosted"),
            ("https://nexus.example.test/a/../repository/ansible-hosted", "ansible-hosted"),
            ("https://nexus.example.test//repository/ansible-hosted", "ansible-hosted"),
            ("https://nexus.example.test/a%2Frepository/ansible-hosted", "ansible-hosted"),
            (" https://nexus.example.test/repository/ansible-hosted", "ansible-hosted"),
        ):
            with self.subTest(value=value):
                with self.assertRaises(MODULE.StageError):
                    MODULE.repository_url(value, repository)

    def test_candidate_path_and_name_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            wrong_name = root / "candidate.tar.gz"
            wrong_name.write_bytes(b"candidate")
            with self.assertRaisesRegex(MODULE.StageError, "name"):
                MODULE.require_candidate(wrong_name)

            target = self.candidate(root)
            link = root / "lit-supplementary-3.2.5.tar.gz"
            link.symlink_to(target)
            with self.assertRaisesRegex(MODULE.StageError, "non-symlink"):
                MODULE.require_candidate(link)


if __name__ == "__main__":
    unittest.main()
