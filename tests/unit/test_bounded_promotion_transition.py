"""Pin the bounded promotion stage to exact file hashes and deferred paths."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOUNDED_COMPONENT_SHA256 = {
    "AGENTS.md": "e2b67d46718d5966f63ceeade8466dbff26ff0aab04600247fbdc35b60af74e9",
    ".github/codex/prompts/review-exact-head.md": "b3c1816aa72b67b48be434f708036df25d0fa2e5dc5830e0022d37aeb532b1ac",
    ".github/workflows/codex-copilot-remediation.yml": (
        "972539527b2a1ff3499db34d0d867aadde90313c9120b15b1c273287b7b82e76"
    ),
    ".github/workflows/current-revision-rerun.yml": (
        "c631843139ee2cd47f8bc5958d41c7395bcff4b2b710770d05a11bbee03054df"
    ),
    ".github/workflows/release-bot-exact-head-review.yml": (
        "ac2a2bc75c183b856cbb121eeac0e6fc660e5e03fe73cdf2513171114cfc5ecf"
    ),
    "docs/push-ready-optimization.md": "285a46ff586b2913e2f4087fd8001959296f6a137d45d1407b86e9d92648b814",
    "scripts/materialize-exact-revision-review.py": "30943308ea3b541c68565511d940ea7ba6be8d0207410ae21e20e3dd60b3ea6a",
    "scripts/devtools-collection-prepare.sh": ("6134b951da0d873c5bc15cb525c73eb962d5ff1413d32dca7389977fe98bf3c2"),
    "scripts/devtools-ansible-lint.sh": "3689b5bc1d6d55efaacbbd4bfeda3eec058e61ca48f6b95d8c737f396f3722b2",
    "scripts/devtools-collection-smoke.sh": "26b9f454f1d7705738f8f2f275ae5c40ff07d1804fd832c7be74d871bd4bf846",
    "scripts/devtools-galaxy-verify.sh": "0f50d2c851cd51bf32585503811c58fd646959cb55f99c6b39e7180159c9620e",
    "scripts/devtools-molecule.sh": "8b48cf08b534316e25449e36c1c79f04b40f92c05b0f2cdcef2c5a0ce76a651d",
    "scripts/lit-ci-profile.sh": "b2ced9a43284dbdc77e8eb990bc52d50515ad381e138a76591db01e7b0dae19d",
    "tests/unit/test_managed_exact_revision_materializer_security.py": (
        "523ab2222052fc1e9960147f0faabe76fb38727bed22f7287087205ca438cb58"
    ),
    "tests/unit/test_exact_revision_review.py": (
        "19267f4c59cd64c386da5ff1fb6bcbbe37f452c7c05f31e11b343409b71fc382"
    ),
    "tests/unit/test_workflow_security.py": ("160e2a7003a2f5d33817c1e82791446bd76352b92baa738eddfab09b82184b03"),
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

    def test_one_exact_legacy_base_handoff_is_transition_bound(self) -> None:
        rerun = (ROOT / ".github/workflows/current-revision-rerun.yml").read_text(encoding="utf-8")
        exact = (ROOT / ".github/workflows/release-bot-exact-head-review.yml").read_text(encoding="utf-8")
        self.assertEqual(2, rerun.count("626f249d5e05a9bdca93f183029f031f6979061b"))
        self.assertIn("github.workflow_sha == inputs.expected_head", rerun)
        self.assertIn("github.sha == inputs.expected_head", rerun)
        self.assertIn('test "${GITHUB_REF}:${GITHUB_SHA}" = "refs/heads/develop:${EXPECTED_HEAD}"', rerun)
        self.assertIn('-f "ref=${BASE_REF}"', exact)
        self.assertIn('-f "inputs[base_ref]=${BASE_REF}"', exact)
        self.assertIn('-f "inputs[producer_run_id]=${PRODUCER_RUN_ID}"', exact)


if __name__ == "__main__":
    unittest.main()
