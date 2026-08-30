"""Pin the bounded promotion stage to exact file hashes and deferred paths."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOUNDED_COMPONENT_SHA256 = {
    ".github/codex/prompts/review-exact-head.md": "b3c1816aa72b67b48be434f708036df25d0fa2e5dc5830e0022d37aeb532b1ac",
    ".github/workflows/codex-copilot-remediation.yml": (
        "972539527b2a1ff3499db34d0d867aadde90313c9120b15b1c273287b7b82e76"
    ),
    ".github/workflows/release-bot-exact-head-review.yml": (
        "e13a639e02ce2121f34ae5cee46a43d8b323ce525cd41f7da2eb6e811fbb500b"
    ),
    "docs/push-ready-optimization.md": "285a46ff586b2913e2f4087fd8001959296f6a137d45d1407b86e9d92648b814",
    "scripts/materialize-exact-revision-review.py": "30943308ea3b541c68565511d940ea7ba6be8d0207410ae21e20e3dd60b3ea6a",
    "tests/unit/test_managed_exact_revision_materializer_security.py": (
        "523ab2222052fc1e9960147f0faabe76fb38727bed22f7287087205ca438cb58"
    ),
}
DEFERRED_PATHS = (
    "changelogs/fragments/rep60-ancestry-current-revision.yml",
    "changelogs/fragments/rep60-required-status-stability.yml",
    "changelogs/fragments/rep60-review-api-convergence.yml",
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

    def test_reservation_creation_recovers_without_a_blind_retry(self) -> None:
        workflow = (ROOT / ".github/workflows/release-bot-exact-head-review.yml").read_text(encoding="utf-8")
        self.assertIn("create_reservation_once() {", workflow)
        self.assertIn("Recovering immutable reservation creation outcome", workflow)
        self.assertIn("select(.head_sha == $head and .external_id == $external_id)", workflow)


if __name__ == "__main__":
    unittest.main()
