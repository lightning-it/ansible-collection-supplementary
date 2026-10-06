"""Exercise evidence production with independent real streamed Git plans."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .test_push_ready_engine import ENGINE, ROOT, run_git


class PlanBindingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name).resolve() / "repo"
        env = ENGINE["isolated_git_environment"]({"PATH": os.environ["PATH"]})
        run_git(self.repo, "init", "-q", environment=env)
        (self.repo / "docs").mkdir()
        document = self.repo / "docs/change.txt"
        document.write_text("before\n")
        self.commit(env)
        self.config = json.loads((ROOT / ".lit/push-ready.json").read_text())
        self.namespace = ENGINE["produce_evidence"].__globals__
        self.enterContext(mock.patch.dict(self.namespace, ROOT=self.repo))
        self.base = self.namespace["git_output"]("rev-parse", "HEAD").strip()
        document.write_text("after ä𐍈\n" * 9000)
        self.commit(env)
        self.enterContext(
            mock.patch.dict(
                self.namespace,
                {
                    "resolve_base": lambda *_a, **_kw: ("refs/remotes/origin/develop", self.base, self.base),
                    "secret_fixture_manifest_for_change": lambda *_a, **_kw: {},
                    "config_at_commit": lambda *_a: self.config,
                },
            )
        )
        self.enterContext(
            mock.patch.object(ENGINE["PatchSpool"], "as_text", side_effect=AssertionError("whole patch read"))
        )
        self.planner = self.namespace["planned_change"]
        self.initial = self.plan()
        self.reviews = mock.Mock(return_value=[])
        self.writer = mock.Mock()
        self.verifier = mock.Mock()
        self.enterContext(
            mock.patch.dict(
                self.namespace,
                {
                    "require_trusted_review_policy": mock.Mock(),
                    "require_policy_files_committed": mock.Mock(),
                    "execute_integration_checks": mock.Mock(return_value=([], "tree", "commit", "fingerprint")),
                    "run_agent_reviews": self.reviews,
                    "install_pre_push_hook": mock.Mock(),
                    "write_evidence": self.writer,
                    "verify_evidence": self.verifier,
                    "evidence_path": lambda: self.repo / "evidence.json",
                },
            )
        )

    def commit(self, environment):
        run_git(self.repo, "add", ".", environment=environment)
        run_git(
            self.repo,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
            environment=environment,
        )

    def plan(self):
        change = self.planner(self.config)
        self.addCleanup(change.patch.close)
        return change

    def produce(self):
        ENGINE["produce_evidence"](self.config, self.initial, fixture_manifest_bootstrap=False)

    def test_unchanged_real_replanned_spool_reaches_evidence_write_and_verify(self):
        current = self.plan()
        self.assertIsNot(current.patch, self.initial.patch)
        self.assertGreater(current.patch.size, ENGINE["CHUNK_BYTES"])
        self.assertEqual(current.diff_sha256, self.initial.diff_sha256)
        with mock.patch.dict(self.namespace, planned_change=mock.Mock(return_value=current)):
            self.produce()
        self.reviews.assert_called_once()
        self.assertIs(self.reviews.call_args.args[1], current)
        self.writer.assert_called_once()
        self.assertIs(self.writer.call_args.args[3], current)
        self.verifier.assert_called_once_with(self.config)

    def test_every_stable_plan_field_drift_blocks_evidence(self):
        changes = {
            "base_ref": "refs/remotes/origin/other",
            "base_tip": "a" * 40,
            "base_commit": "b" * 40,
            "head_commit": "c" * 40,
            "paths": ("docs/other.txt",),
            "untracked_sha256": {"other": "d" * 64},
            "tree_fingerprint": "e" * 64,
        }
        for field, value in changes.items():
            current = self.plan()._replace(**{field: value})
            with (
                self.subTest(field=field),
                mock.patch.dict(self.namespace, planned_change=mock.Mock(return_value=current)),
                self.assertRaisesRegex(RuntimeError, "change binding drifted"),
            ):
                self.produce()
        self.reviews.assert_not_called()
        self.writer.assert_not_called()
        self.verifier.assert_not_called()

    def test_equal_length_changed_patch_blocks_evidence(self):
        current = self.plan()
        altered = ENGINE["PatchSpool"]()
        self.addCleanup(altered.close)
        for chunk in current.patch.chunks():
            altered.write(chunk.replace(b"after", b"other"))
        self.assertEqual(altered.size, current.patch.size)
        current = current._replace(patch=altered)
        with (
            mock.patch.dict(self.namespace, planned_change=mock.Mock(return_value=current)),
            self.assertRaisesRegex(RuntimeError, "change binding drifted"),
        ):
            self.produce()
        self.reviews.assert_not_called()
        self.writer.assert_not_called()

    def test_tampered_spool_with_unchanged_cached_digest_blocks_evidence(self):
        for side in ("initial", "current"):
            initial = self.plan()
            current = self.plan()
            spool = initial.patch if side == "initial" else current.patch
            spool.file.seek(0)
            spool.file.write(b"X")
            self.assertEqual(initial.diff_sha256, current.diff_sha256)
            with (
                self.subTest(side=side),
                mock.patch.dict(self.namespace, planned_change=mock.Mock(return_value=current)),
                self.assertRaisesRegex(RuntimeError, "private patch spool changed"),
            ):
                ENGINE["produce_evidence"](self.config, initial, fixture_manifest_bootstrap=False)
        self.reviews.assert_not_called()
        self.writer.assert_not_called()
