"""Tests for collision-resistant self-hosted quality-cell identities."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("quality_cell_identity", ROOT / "scripts" / "quality_cell_identity.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class QualityCellIdentityTests(unittest.TestCase):
    def test_maximum_length_preserves_full_identity_hash(self) -> None:
        scenario = "s" * 63
        first = MODULE.bounded_identity(f"{scenario}-100000-1-ubuntu-24.04", maximum=63)
        second = MODULE.bounded_identity(f"{scenario}-100001-1-ubuntu-24.04", maximum=63)
        self.assertLessEqual(len(first), 63)
        self.assertLessEqual(len(second), 63)
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[A-Za-z0-9][A-Za-z0-9.-]*-[0-9a-f]{24}$")

    def test_long_owner_retains_run_and_attempt_uniqueness(self) -> None:
        prefix = f"organization/{'repository' * 20}-{'workflow' * 30}"
        first = MODULE.bounded_identity(f"{prefix}-800-1-scenario-target", maximum=255, owner=True)
        second = MODULE.bounded_identity(f"{prefix}-800-2-scenario-target", maximum=255, owner=True)
        self.assertLessEqual(len(first), 255)
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^[A-Za-z0-9][A-Za-z0-9._/-]*-[0-9a-f]{24}$")

    def test_identity_rejects_unsafe_leading_character(self) -> None:
        with self.assertRaisesRegex(ValueError, "begin"):
            MODULE.bounded_identity("/unsafe", maximum=63)


if __name__ == "__main__":
    unittest.main()
