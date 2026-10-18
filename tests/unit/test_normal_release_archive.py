"""Bounded archive transport, crypto arguments and strict historical replay."""

from __future__ import annotations

import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("normal_release_archive", ROOT / "scripts/normal_release_archive.py")
ARCHIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ARCHIVE)
REPO = "lightning-it/ansible-collection-supplementary"
SHA, BASE, HEAD, SOURCE = (letter * 40 for letter in "abcd")
EXPECTED = ARCHIVE.binding(REPO, "1103407173", SHA, BASE, HEAD, SOURCE)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.snapshot = self.root / ARCHIVE.SNAPSHOT
        self.bundle = self.root / ARCHIVE.BUNDLE
        self.value = {
            "version": 1,
            "kind": "normal-release-native-observations",
            "binding": EXPECTED,
            "reads": [
                {"kind": "call", "args": [f"repos/{REPO}/git/ref/heads/main"], "value": {"object": {"sha": SHA}}}
            ],
            "result": {"main_merge": SHA},
        }
        self.snapshot.write_bytes(ARCHIVE.canonical(self.value))
        self.bundle.write_text('{"unit":"signature boundary mocked, not native acceptance"}')

    def verify(self):
        return ARCHIVE.verify_files(self.snapshot, self.bundle, REPO, "1103407173", SHA)

    def test_verification_uses_local_bundle_exact_workflow_and_source_before_decode(self):
        with (
            patch.object(ARCHIVE.shutil, "which", return_value="/usr/bin/gh"),
            patch.object(ARCHIVE.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as command,
        ):
            self.assertEqual(self.value, self.verify())
        self.assertEqual(
            [
                "/usr/bin/gh",
                "attestation",
                "verify",
                str(self.snapshot),
                "--bundle",
                str(self.bundle),
                "--repo",
                REPO,
                "--cert-identity",
                f"https://github.com/{REPO}/.github/workflows/collection-publish.yml@refs/heads/main",
                "--source-ref",
                "refs/heads/main",
                "--source-digest",
                SHA,
            ],
            command.call_args.args[0],
        )
        command.assert_called_once()

    def test_bad_signature_wrong_signer_or_wrong_source_never_decodes_or_replays(self):
        for reason in ("tampered payload", "wrong signer", "wrong source SHA", "wrong bundle"):
            with (
                self.subTest(reason=reason),
                patch.object(ARCHIVE.shutil, "which", return_value="/usr/bin/gh"),
                patch.object(ARCHIVE.subprocess, "run", return_value=SimpleNamespace(returncode=1)),
                patch.object(ARCHIVE, "decode") as decode,
                self.assertRaisesRegex(ValueError, "attestation-verification-failed"),
            ):
                self.verify()
            decode.assert_not_called()

    def test_oversized_symlink_or_missing_bundle_never_calls_verifier(self):
        for defect in ("oversized", "symlink", "missing"):
            with self.subTest(defect=defect), patch.object(ARCHIVE.subprocess, "run") as command:
                self.bundle.unlink(missing_ok=True)
                if defect == "oversized":
                    self.bundle.write_bytes(b"x" * 11)
                elif defect == "symlink":
                    self.bundle.symlink_to(self.snapshot)
                with patch.object(ARCHIVE, "MAX_BUNDLE_BYTES", 10), self.assertRaisesRegex(ValueError, "file-bound"):
                    self.verify()
            command.assert_not_called()

    def test_authenticated_json_still_requires_exact_binding_and_canonical_bounded_shape(self):
        for raw in (
            b'{"version":1,"version":1}\n',
            b"{}",
            b"[" * 65 + b"]" * 65,
            ARCHIVE.canonical(self.value | {"binding": EXPECTED | {"release": BASE}}),
        ):
            self.snapshot.write_bytes(raw)
            with (
                self.subTest(raw=raw[:50]),
                patch.object(ARCHIVE.shutil, "which", return_value="/usr/bin/gh"),
                patch.object(ARCHIVE.subprocess, "run", return_value=SimpleNamespace(returncode=0)),
                self.assertRaises(ValueError),
            ):
                self.verify()

    def test_only_historical_main_tip_is_overlaid_and_complete_consumption_is_mandatory(self):
        replay = ARCHIVE.Replay(self.value, EXPECTED, HEAD)
        self.assertEqual({"object": {"sha": HEAD}}, replay.call(f"repos/{REPO}/git/ref/heads/main"))
        replay.finish({"main_merge": SHA})
        self.assertEqual(SHA, self.value["reads"][0]["value"]["object"]["sha"])
        for defect in ("missing", "extra", "arguments", "main", "result", "binding", "write"):
            value = copy.deepcopy(self.value)
            if defect == "missing":
                value["reads"] = []
            elif defect == "extra":
                value["reads"] *= 2
            elif defect == "arguments":
                value["reads"][0]["args"] = ["repos/other/repository"]
            elif defect == "main":
                value["reads"][0]["value"]["object"]["sha"] = BASE
            elif defect == "result":
                value["result"] = {}
            elif defect == "binding":
                value["binding"] = EXPECTED | {"head": BASE}
            with self.subTest(defect=defect), self.assertRaises(ValueError):
                replay = ARCHIVE.Replay(value, EXPECTED, HEAD)
                replay.call(f"repos/{REPO}/git/ref/heads/main", method="POST" if defect == "write" else "GET")
                replay.finish({"main_merge": SHA})

    def test_capture_pauses_nested_artifact_reads_but_binds_verified_return_and_metadata(self):
        api = Mock()
        metadata = {
            "id": 21,
            "name": "control-proof-1",
            "expired": False,
            "size_in_bytes": 100,
            "digest": "sha256:" + "e" * 64,
        }
        api.pages.return_value = [metadata]
        api.call.return_value = {"verified": "native-observation"}
        run = {"id": 20, "run_attempt": 1, "head_sha": HEAD}

        def original(reader, repository, observed, _name, _filename):
            self.assertEqual(
                [metadata], reader.pages(f"repos/{repository}/actions/runs/{observed['id']}/artifacts", "artifacts")
            )
            return {"version": 1, "binding": "native reader already checked the real download"}

        core = SimpleNamespace(artifact_record=original)
        record = ARCHIVE.Record(api, EXPECTED)
        with ARCHIVE.artifact_reader(core, record):
            native = record.call(f"repos/{REPO}/actions/runs/20")
            proof = core.artifact_record(record, REPO, run, "control-proof-1", "control-proof.json")
        self.assertIs(original, core.artifact_record)
        value = ARCHIVE.decode(record.finish({"checked": True}))
        self.assertEqual(["call", "artifact"], [item["kind"] for item in value["reads"]])
        api.pages.assert_called_once()
        self.assertEqual(metadata, value["reads"][1]["value"]["metadata"])
        api.reset_mock()
        api.call.side_effect = AssertionError("original Actions expired")
        api.pages.side_effect = AssertionError("original artifacts expired")
        replay = ARCHIVE.Replay(value, EXPECTED, SHA)
        with ARCHIVE.artifact_reader(core, replay):
            self.assertEqual(native, replay.call(f"repos/{REPO}/actions/runs/20"))
            self.assertEqual(proof, core.artifact_record(replay, REPO, run, "control-proof-1", "control-proof.json"))
        replay.finish({"checked": True})
        api.call.assert_not_called()
        api.pages.assert_not_called()
        for changed in (run | {"id": 22}, run | {"run_attempt": 2}, run | {"head_sha": BASE}):
            replay = ARCHIVE.Replay(value, EXPECTED, SHA)
            replay.call(f"repos/{REPO}/actions/runs/20")
            with self.subTest(run=changed), self.assertRaisesRegex(ValueError, "order-or-binding"):
                replay.artifact(None, None, REPO, changed, "control-proof-1", "control-proof.json")

    def test_preparation_input_protocol_is_exact_attempt_bound_and_replayed_without_download(self):
        run = {"id": 10, "run_attempt": 2, "head_sha": HEAD}
        name, filename = "normal-release-preparation-2", "preparation-inputs.json"
        metadata = {"id": 99, "name": name, "expired": False, "size_in_bytes": 100}
        original_record = {
            "schema": "collection-normal-preparation/v1",
            "head": HEAD,
            "version_selection": {"requested": "1.2.3-rc.1"},
            "publication": {"github_release": True, "galaxy": False},
        }
        api = Mock()
        api.pages.return_value = [metadata]

        def reader(source, repository, observed, artifact, selected_file):
            self.assertEqual(name, artifact)
            self.assertEqual(filename, selected_file)
            source.pages(f"repos/{repository}/actions/runs/{observed['id']}/artifacts", "artifacts")
            return copy.deepcopy(original_record)

        recorder = ARCHIVE.Record(api, EXPECTED)
        self.assertEqual(original_record, recorder.artifact(reader, recorder, REPO, run, name, filename))
        value = ARCHIVE.decode(recorder.finish({"verified": True}))
        replay = ARCHIVE.Replay(value, EXPECTED, SHA)
        with patch.object(api, "pages", side_effect=AssertionError("historical source expired")):
            self.assertEqual(original_record, replay.artifact(None, None, REPO, run, name, filename))
        replay.finish({"verified": True})
        for wrong_run, wrong_name, wrong_file in (
            (run, "normal-release-preparation-1", filename),
            (run, "normal-release-preparation-0", filename),
            (run, "control-proof-2", filename),
            (run, name, "other-inputs.json"),
            (run | {"run_attempt": True}, "normal-release-preparation-True", filename),
            (run | {"run_attempt": 0}, "normal-release-preparation-0", filename),
            (run | {"run_attempt": -1}, "normal-release-preparation--1", filename),
        ):
            original = Mock()
            with self.subTest(run=wrong_run, name=wrong_name, filename=wrong_file), self.assertRaises(ValueError):
                recorder.artifact(original, recorder, REPO, wrong_run, wrong_name, wrong_file)
            original.assert_not_called()

    def test_record_writes_other_repository_or_unbounded_history_are_closed(self):
        api = Mock()
        recorder = ARCHIVE.Record(api, EXPECTED)
        for path, method in ((f"repos/{REPO}/pulls", "POST"), ("repos/other/repo/pulls", "GET")):
            with self.subTest(path=path), self.assertRaises(ValueError):
                recorder.call(path, method=method)
        api.call.assert_not_called()
        with patch.object(ARCHIVE, "MAX_READS", 0), self.assertRaises(ValueError):
            recorder.add("call", [], {})

    def test_pair_transport_uses_exact_native_asset_ids_and_bounded_streams(self):
        assets = [
            {
                "name": name,
                "id": index,
                "state": "uploaded",
                "size": 10,
                "browser_download_url": "https://untrusted.invalid/ignored",
            }
            for index, name in enumerate((ARCHIVE.SNAPSHOT, ARCHIVE.BUNDLE), 1)
        ]
        original = ARCHIVE.subprocess.Popen

        def transport(_command, **kwargs):
            return original([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 10)"], **kwargs)

        with (
            patch.object(ARCHIVE.shutil, "which", return_value="/usr/bin/gh"),
            patch.object(ARCHIVE.subprocess, "Popen", side_effect=transport) as command,
        ):
            ARCHIVE.download_pair({"assets": assets}, REPO, self.root)
        self.assertEqual(2, command.call_count)
        for index, call in enumerate(command.call_args_list, 1):
            self.assertEqual(f"repos/{REPO}/releases/assets/{index}", call.args[0][-1])
        self.assertEqual(b"x" * 10, self.snapshot.read_bytes())
        self.assertEqual(b"x" * 10, self.bundle.read_bytes())
        for script in ("import sys; sys.stdout.buffer.write(b'x' * 11)", "raise SystemExit(1)"):

            def failed_transport(_command, script=script, **kwargs):
                return original([sys.executable, "-c", script], **kwargs)

            with (
                self.subTest(script=script),
                patch.object(ARCHIVE, "MAX_BYTES", 10),
                patch.object(ARCHIVE.shutil, "which", return_value="/usr/bin/gh"),
                patch.object(ARCHIVE.subprocess, "Popen", side_effect=failed_transport) as command,
                self.assertRaises(ValueError),
            ):
                ARCHIVE.download_pair({"assets": assets}, REPO, self.root)
            command.assert_called_once()

    def test_asset_download_rejects_missing_ambiguous_expired_or_oversized_sources_before_transport(self):
        assets = [
            {"name": name, "id": index, "state": "uploaded", "size": 10}
            for index, name in enumerate((ARCHIVE.SNAPSHOT, ARCHIVE.BUNDLE), 1)
        ]
        for bad in (
            [],
            [assets[0]],
            [assets[0], assets[1] | {"id": 1}],
            [assets[0], assets[0]],
            [assets[0] | {"size": ARCHIVE.MAX_BYTES + 1}],
            [assets[0] | {"id": True}],
            [assets[0] | {"state": "new"}],
        ):
            with (
                self.subTest(assets=bad),
                patch.object(ARCHIVE.shutil, "which", return_value="/usr/bin/gh"),
                patch.object(ARCHIVE.subprocess, "Popen") as process,
                self.assertRaises(ValueError),
            ):
                ARCHIVE.download_pair({"assets": bad}, REPO, self.root)
            process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
