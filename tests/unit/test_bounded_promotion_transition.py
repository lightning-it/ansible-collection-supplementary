"""Bind the bounded stage to protected main plus reviewed security corrections."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE_MAIN = "626f249d5e05a9bdca93f183029f031f6979061b"
BOUNDED_COMPONENT_SHA256 = {
    ".github/codex/prompts/review-exact-head.md": "83e5dd32fd96be95f29b01beac2a3a32e49502cabaa11c8d9d717d705899e546",
    ".github/workflows/codex-copilot-remediation.yml": (
        "7bde56e27e0abc77c9320fe13bf1cc2b0751d674c1c88605bddf825b3da5c9c0"
    ),
    ".github/workflows/release-bot-exact-head-review.yml": (
        "283a64eba37967bc9db3dabdbf5db5a0085f229899d2cb389b5728df83ee3c74"
    ),
    "scripts/materialize-exact-revision-review.py": "0f91b95be5145587564974b38cde038e8ed208884cde7cf7138baeab65be690d",
    "tests/unit/test_managed_exact_revision_materializer_security.py": (
        "05d54c8076abae9a9ee43b75dbab412ebb350cb9f14602582681e5704d826170"
    ),
}


class BoundedPromotionTransitionTests(unittest.TestCase):
    """Prove that the reviewed bounded transition stays byte-exact."""

    def test_bounded_component_matches_reviewed_transition(self) -> None:
        self.assertRegex(BASELINE_MAIN, r"^[0-9a-f]{40}$")
        for relative, expected in BOUNDED_COMPONENT_SHA256.items():
            with self.subTest(path=relative):
                actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
