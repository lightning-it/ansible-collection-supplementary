"""Bind the bounded promotion stage to the already protected main controller."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTECTED_MAIN = "626f249d5e05a9bdca93f183029f031f6979061b"
PROTECTED_COMPONENT_SHA256 = {
    ".github/codex/prompts/review-exact-head.md": "83e5dd32fd96be95f29b01beac2a3a32e49502cabaa11c8d9d717d705899e546",
    ".github/workflows/release-bot-exact-head-review.yml": (
        "1ba8edb2b6460530099a0ac7f554c8bb76a5953eddd57c59b525925ed7a1661a"
    ),
    "scripts/materialize-exact-revision-review.py": "f511ff5445a2d8e5fc7d050ca409f81b1573730f63ab259c1e1e008df960bd97",
    "tests/unit/test_managed_exact_revision_materializer_security.py": (
        "63549817c48a11212f87f689f826da9e8204b61589d923834287cc2cf6f6b984"
    ),
}


class BoundedPromotionTransitionTests(unittest.TestCase):
    """Prove that the deferred component is byte-identical to protected main."""

    def test_deferred_component_is_exact_protected_main_baseline(self) -> None:
        self.assertRegex(PROTECTED_MAIN, r"^[0-9a-f]{40}$")
        for relative, expected in PROTECTED_COMPONENT_SHA256.items():
            with self.subTest(path=relative):
                actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
