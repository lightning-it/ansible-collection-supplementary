"""Pin the bounded promotion stage to exact file hashes and deferred paths."""

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENT_TOKENS = """
.github/codex/prompts/review-exact-head.md b3c1816aa72b67b48be434f708036df25d0fa2e5dc5830e0022d37aeb532b1ac
.github/workflows/codex-copilot-remediation.yml 1ad04b0b7d046833f809c526e702cd36a2ab4594f9606ba87134b6c5977a7e2a
.github/workflows/release-bot-exact-head-review.yml a664468d21f59805ddf2d33618a39d76fcdf06b74f8a15796c5030edfe6bede0
scripts/materialize-exact-revision-review.py b63faab90271b48068ae5368c3e2ccd0a7efcfac0df5b1e987048c56c0c70b94
tests/unit/test_managed_exact_revision_materializer_security.py
31ba28deb51efea7b6d18d57c48a618623f61702d2712b3cbdd3c40e8bea9ae5
""".split()
BOUNDED_COMPONENT_SHA256 = dict(zip(COMPONENT_TOKENS[::2], COMPONENT_TOKENS[1::2], strict=True))
DEFERRED_PATHS = (
    "changelogs/fragments/rep60-ancestry-current-revision.yml",
    "changelogs/fragments/rep60-required-status-stability.yml",
    "changelogs/fragments/rep60-review-api-convergence.yml",
)


class BoundedPromotionTransitionTests(unittest.TestCase):
    def test_bounded_component_matches_reviewed_transition(self) -> None:
        for relative, expected in BOUNDED_COMPONENT_SHA256.items():
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(expected, actual, relative)

    def test_second_promotion_paths_are_absent_from_this_stage(self) -> None:
        for relative in DEFERRED_PATHS:
            self.assertFalse((ROOT / relative).exists(), relative)
        for path in ROOT.glob("changelogs/fragments/shared-assets-sync-*.yml"):
            self.assertLess(int(path.stem.rsplit("-", 1)[1]), 32500000000, path)
