from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release-stage-handoff.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_stage_handoff", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load release stage handoff script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script()


def binding(*, security: bool = True) -> dict[str, object]:
    return {
        "candidateName": "lit-supplementary-3.2.4.tar.gz",
        "ciRunAttempt": 1,
        "ciRunId": 456,
        "galaxyRequired": security,
        "releaseVersion": "3.2.4",
        "securityEvidenceId": "MLX90-GHSA-VJJF-WC74-GP86-3.2.4" if security else None,
        "securityRelease": security,
        "sourceRunAttempt": 2,
        "sourceRunId": 123,
        "sourceSha": "a" * 40,
    }


class ReleaseStageHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.name = "lit-supplementary-3.2.4.tar.gz"
        for directory in ("incoming/candidate", "dist/release", "dist/validation"):
            (self.root / directory).mkdir(parents=True)
        for directory in ("incoming/candidate", "dist/release"):
            (self.root / directory / self.name).write_bytes(b"exact release candidate")
        (self.root / "dist/validation/nexus-stage.json").write_bytes(b'{"staged":true}\n')
        self.binding = binding()

    def make_manifest(self) -> tuple[bytes, str]:
        payload = MODULE.canonical(MODULE.build_manifest(self.root, self.binding))
        return payload, hashlib.sha256(payload).hexdigest()

    def test_exact_handoff_and_independent_source_binding(self) -> None:
        payload, digest = self.make_manifest()
        MODULE.verify(self.root, self.binding, payload, digest)
        changed = {**self.binding, "sourceRunAttempt": 3}
        with self.assertRaisesRegex(MODULE.HandoffError, "source binding changed"):
            MODULE.verify(self.root, changed, payload, digest)

    def test_changed_candidate_and_extra_attachment_fail(self) -> None:
        payload, digest = self.make_manifest()
        (self.root / "incoming/candidate" / self.name).write_bytes(b"different candidate")
        with self.assertRaisesRegex(MODULE.HandoffError, "candidate and release attachment"):
            MODULE.verify(self.root, self.binding, payload, digest)
        (self.root / "incoming/candidate" / self.name).write_bytes(b"exact release candidate")
        (self.root / "dist/release/unlisted.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.HandoffError, "files or source binding changed"):
            MODULE.verify(self.root, self.binding, payload, digest)

    def test_missing_security_stage_and_ordinary_release(self) -> None:
        (self.root / "dist/validation/nexus-stage.json").unlink()
        with self.assertRaisesRegex(MODULE.HandoffError, "lacks staged Nexus"):
            MODULE.build_manifest(self.root, self.binding)
        ordinary = binding(security=False)
        payload = MODULE.canonical(MODULE.build_manifest(self.root, ordinary))
        MODULE.verify(self.root, ordinary, payload, hashlib.sha256(payload).hexdigest())
        security_without_galaxy = {**self.binding, "galaxyRequired": False}
        payload = MODULE.canonical(MODULE.build_manifest(self.root, security_without_galaxy))
        MODULE.verify(self.root, security_without_galaxy, payload, hashlib.sha256(payload).hexdigest())

    def test_symlink_hardlink_and_executable_content_fail(self) -> None:
        candidate = self.root / "incoming/candidate" / self.name
        candidate.unlink()
        candidate.symlink_to(self.root / "dist/release" / self.name)
        with self.assertRaisesRegex(MODULE.HandoffError, "symlink"):
            MODULE.build_manifest(self.root, self.binding)
        candidate.unlink()
        os.link(self.root / "dist/release" / self.name, candidate)
        with self.assertRaisesRegex(MODULE.HandoffError, "nonexecutable"):
            MODULE.build_manifest(self.root, self.binding)
        candidate.unlink()
        candidate.write_bytes(b"exact release candidate")
        candidate.chmod(0o755)
        with self.assertRaisesRegex(MODULE.HandoffError, "nonexecutable"):
            MODULE.build_manifest(self.root, self.binding)

    def test_modified_manifest_and_wrong_digest_fail(self) -> None:
        payload, digest = self.make_manifest()
        with self.assertRaisesRegex(MODULE.HandoffError, "digest differs"):
            MODULE.verify(self.root, self.binding, payload, "0" * 64)
        with self.assertRaisesRegex(MODULE.HandoffError, "digest differs"):
            MODULE.verify(self.root, self.binding, payload + b" ", digest)
        forged = MODULE.canonical({**MODULE.build_manifest(self.root, self.binding), "totalBytes": 0})
        with self.assertRaisesRegex(MODULE.HandoffError, "files or source binding changed"):
            MODULE.verify(self.root, self.binding, forged, hashlib.sha256(forged).hexdigest())

    def test_boolean_integer_equality_cannot_forge_manifest(self) -> None:
        forged = MODULE.build_manifest(self.root, self.binding)
        forged["binding"] = {**self.binding, "securityRelease": 1}
        payload = MODULE.canonical(forged)
        with self.assertRaisesRegex(MODULE.HandoffError, "files or source binding changed"):
            MODULE.verify(self.root, self.binding, payload, hashlib.sha256(payload).hexdigest())

    def test_duplicate_keys_noncanonical_json_and_unsafe_path_fail(self) -> None:
        with self.assertRaisesRegex(MODULE.HandoffError, "duplicate JSON key"):
            MODULE.load_canonical(b'{"a":1,"a":2}\n', "test")
        with self.assertRaisesRegex(MODULE.HandoffError, "not canonical"):
            MODULE.load_canonical(b'{ "a": 1 }\n', "test")
        for unsafe in ("dist/../secret", "incoming//secret", "dist/evil\\name", "dist/\ud800", "dist/.token"):
            with self.subTest(path=unsafe), self.assertRaises(MODULE.HandoffError):
                MODULE.safe_relative(unsafe)


if __name__ == "__main__":
    unittest.main()
