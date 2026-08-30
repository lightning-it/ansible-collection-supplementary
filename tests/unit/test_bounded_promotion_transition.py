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
        "2dd934c670253acb16766d1ff2f033dec8741ac75204456e205272dd476e5b0d"
    ),
    ".github/workflows/copilot-review.yml": ("749b5c447efcfb9be421b8c7630241b8a1a84624a4f676495a3d8da164d1b34a"),
    ".github/workflows/release-bot-exact-head-review.yml": (
        "ac2a2bc75c183b856cbb121eeac0e6fc660e5e03fe73cdf2513171114cfc5ecf"
    ),
    "docs/push-ready-optimization.md": "285a46ff586b2913e2f4087fd8001959296f6a137d45d1407b86e9d92648b814",
    "scripts/materialize-exact-revision-review.py": "30943308ea3b541c68565511d940ea7ba6be8d0207410ae21e20e3dd60b3ea6a",
    "scripts/devtools-collection-prepare.sh": ("e187a180997a5c9b3de2dde1be0ce619801a43987ca1425366e030e3447b3be2"),
    "scripts/devtools-ansible-lint.sh": "ba9a002c20842c8bdeb657b7a24e48984c88f0c3479e0640534766cf75f5eaa9",
    "scripts/devtools-collection-smoke.sh": "af844fe0c99a2675623827fa56173b22f5d691b6f6fc491f28cf3ef851337593",
    "scripts/devtools-galaxy-verify.sh": "27f5af823ebeb5b3417f9833323d7704bc6ba0935185323f29cbb4c56e87a701",
    "scripts/devtools-molecule.sh": "0e77de4bc7e1ef4527d7710f944680a0c7e6d390da96da785b5f93e6736b4a9a",
    "scripts/lit-ci-profile.sh": "b2ced9a43284dbdc77e8eb990bc52d50515ad381e138a76591db01e7b0dae19d",
    "tests/unit/test_managed_exact_revision_materializer_security.py": (
        "523ab2222052fc1e9960147f0faabe76fb38727bed22f7287087205ca438cb58"
    ),
    "tests/unit/test_exact_revision_review.py": ("b5403e5e73db4d89aa77d13cb6d5521aff0e243a6803e792811b1a48b5bb35e1"),
    "tests/unit/test_workflow_security.py": ("c5cd795601a38e04db1cb6a5ed67998d754f4080a6351f8ebfd07b115d222713"),
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
