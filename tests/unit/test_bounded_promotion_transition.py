"""Pin the bounded promotion stage to exact file hashes and deferred paths."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOUNDED_COMPONENT_SHA256 = {
    ".github/codex/prompts/review-exact-head.md": "b3c1816aa72b67b48be434f708036df25d0fa2e5dc5830e0022d37aeb532b1ac",
    ".github/workflows/codex-copilot-remediation.yml": (
        "1ad04b0b7d046833f809c526e702cd36a2ab4594f9606ba87134b6c5977a7e2a"
    ),
    ".github/workflows/release-bot-exact-head-review.yml": (
        "78f3aab9bd23169e88ced5e53d198162c31f1cfcff64747cbc741be16d453bd6"
    ),
    "scripts/materialize-exact-revision-review.py": "b63faab90271b48068ae5368c3e2ccd0a7efcfac0df5b1e987048c56c0c70b94",
    "tests/unit/test_managed_exact_revision_materializer_security.py": (
        "31ba28deb51efea7b6d18d57c48a618623f61702d2712b3cbdd3c40e8bea9ae5"
    ),
}
DEFERRED_PATHS = (
    "tests/unit/test_dot_github_current_revision.py",
    *(
        f"changelogs/fragments/shared-assets-sync-{run_id}.yml"
        for run_id in (
            32515036139,
            32519315824,
            32537006703,
            32556727553,
            32931505901,
            32960968209,
            32982369383,
            33016066652,
            33026452254,
            33038398057,
            33050088456,
        )
    ),
)


class BoundedPromotionTransitionTests(unittest.TestCase):
    """Prove that the reviewed bounded transition stays byte-exact."""

    def test_bounded_component_matches_reviewed_transition(self) -> None:
        for relative, expected in BOUNDED_COMPONENT_SHA256.items():
            with self.subTest(path=relative):
                actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                self.assertEqual(expected, actual)

    def test_second_promotion_paths_are_absent_from_this_stage(self) -> None:
        for relative in DEFERRED_PATHS:
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists())


if __name__ == "__main__":
    unittest.main()
