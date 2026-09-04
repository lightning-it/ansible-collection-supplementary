"""Pin exact state."""

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HASHES = """
b3c1816aa72b67b48be434f708036df25d0fa2e5dc5830e0022d37aeb532b1ac .github/codex/prompts/review-exact-head.md
1ad04b0b7d046833f809c526e702cd36a2ab4594f9606ba87134b6c5977a7e2a .github/workflows/codex-copilot-remediation.yml
e13a639e02ce2121f34ae5cee46a43d8b323ce525cd41f7da2eb6e811fbb500b .github/workflows/release-bot-exact-head-review.yml
f4a53f6febb193d2a1a4cab985ec8cc2dc0a5ba76db63538b693e03b9c3bdbc6 docs/push-ready-optimization.md
b63faab90271b48068ae5368c3e2ccd0a7efcfac0df5b1e987048c56c0c70b94 scripts/materialize-exact-revision-review.py
31ba28deb51efea7b6d18d57c48a618623f61702d2712b3cbdd3c40e8bea9ae5
tests/unit/test_managed_exact_revision_materializer_security.py
""".split()
DEFERRED = "rep60-ancestry-current-revision rep60-required-status-stability rep60-review-api-convergence".split()
DEFERRED += [
    f"shared-assets-sync-{run_id}"
    for run_id in "32515036139 32519315824 32537006703 32556727553 32931505901 32960968209 32982369383 33016066652 33026452254 33038398057 33050088456".split()  # noqa: E501
]


class BoundedPromotionTransitionTests(unittest.TestCase):
    def test_bounded_transition_stays_exact_and_fail_closed(self) -> None:
        for expected, relative in zip(HASHES[::2], HASHES[1::2], strict=True):
            with self.subTest(path=relative):
                actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                self.assertEqual(expected, actual)
        for name in DEFERRED:
            with self.subTest(path=name):
                self.assertFalse((ROOT / f"changelogs/fragments/{name}.yml").exists())
        workflow = (ROOT / ".github/workflows/release-bot-exact-head-review.yml").read_text()
        for marker in (
            "create_reservation_once() {",
            "Recovering immutable reservation creation outcome",
            "select(.head_sha == $head and .external_id == $external_id)",
        ):
            self.assertIn(marker, workflow)
