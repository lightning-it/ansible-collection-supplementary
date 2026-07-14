"""Tests for persisted, context-scoped local Molecule run identities."""

from __future__ import annotations

import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

MODULE_PATH = (
    Path(__file__).parents[2]
    / "molecule"
    / "shared"
    / "incus"
    / "helpers"
    / "local_run_id.py"
)


def load_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location("local_run_id", MODULE_PATH)
    if specification is None or specification.loader is None:
        raise AssertionError("could not load local_run_id helper")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class LocalRunIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()

    def test_identity_is_created_privately_and_reused_across_invocations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "private" / "scenario.run-id"
            first = "local-tester-111-222"
            second = "local-tester-333-444"
            with mock.patch.object(self.module, "_new_run_id", return_value=first):
                self.assertEqual(first, self.module.persistent_run_id(path))
            with mock.patch.object(self.module, "_new_run_id", return_value=second):
                self.assertEqual(first, self.module.persistent_run_id(path))

            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))

    def test_insecure_state_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "private" / "scenario.run-id"
            path.parent.mkdir(mode=0o700)
            path.write_text("local-tester-111-222\n", encoding="utf-8")
            path.chmod(0o644)
            with self.assertRaisesRegex(RuntimeError, "unsafe ownership or mode"):
                self.module.persistent_run_id(path)

    def test_symlink_state_is_never_followed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            private = root / "private"
            private.mkdir(mode=0o700)
            target = root / "target"
            target.write_text("local-tester-111-222\n", encoding="utf-8")
            target.chmod(0o600)
            path = private / "scenario.run-id"
            path.symlink_to(target)
            with self.assertRaises(OSError):
                self.module.persistent_run_id(path)
            self.assertEqual(
                "local-tester-111-222\n", target.read_text(encoding="utf-8")
            )

    def test_state_directory_must_not_be_group_writable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            private = Path(temporary_directory) / "private"
            private.mkdir(mode=0o770)
            os.chmod(private, 0o770)
            with self.assertRaisesRegex(RuntimeError, "directory is unsafe"):
                self.module.persistent_run_id(private / "scenario.run-id")


if __name__ == "__main__":
    unittest.main()
