from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
MATERIALIZER_PATH = ROOT / "scripts" / "materialize-exact-revision-review.py"


def load_materializer() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("materialize_exact_revision_review", MATERIALIZER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load exact-revision materializer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExactRevisionMaterializerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_materializer()
        self.arguments = argparse.Namespace(
            repository="lightning-it/ansible-collection-supplementary",
            pull_request=748,
            base_ref="develop",
            expected_base="a" * 40,
            expected_head="b" * 40,
            trusted_workflow_sha="a" * 40,
            trigger="app_dispatch",
            dispatch_ref="refs/heads/develop",
        )

    def git_output(self, diff: bytes):
        def output(_git, _git_dir, arguments, **_kwargs):
            if arguments[:2] == ["rev-parse", "refs/review/base^{commit}"]:
                return f"{self.arguments.expected_base}\n"
            if arguments[:2] == ["rev-parse", "refs/review/head^{commit}"]:
                return f"{self.arguments.expected_head}\n"
            if arguments[:2] == ["merge-base", "--all"]:
                return f"{'c' * 40}\n"
            if arguments[:2] == ["merge-tree", "--write-tree"]:
                return f"{'d' * 40}\n"
            if arguments[:2] == ["cat-file", "-t"]:
                return "tree\n"
            if arguments and arguments[0] == "diff":
                return diff
            return ""

        return output

    def materialize(self, diff: bytes, output: Path):
        with (
            mock.patch.dict(os.environ, {"GH_TOKEN": "unit-test-token"}),
            mock.patch.object(self.module, "read_live_pull_request", return_value={}) as live,
            mock.patch.object(self.module, "executable", side_effect=lambda name: f"/usr/bin/{name}"),
            mock.patch.object(self.module, "run", return_value=subprocess.CompletedProcess([], 0, "", "")),
            mock.patch.object(self.module, "git_output", side_effect=self.git_output(diff)),
        ):
            metadata = self.module.materialize(self.arguments, output)
        self.assertEqual(2, live.call_count)
        return metadata

    def test_binary_diff_is_complete_and_bound_to_merge_result(self) -> None:
        binary_diff = (
            b"diff --git a/payload.bin b/payload.bin\n"
            b"new file mode 100644\n"
            b"index 0000000000000000000000000000000000000000..1111111111111111111111111111111111111111\n"
            b"GIT binary patch\nliteral 3\nKcmZQzU|?Vb3IG5A\n\n"
        )
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "review"
            metadata = self.materialize(binary_diff, output)
            self.assertEqual(binary_diff, (output / "change.patch").read_bytes())
            self.assertEqual("c" * 40, metadata["merge_base_sha"])
            self.assertEqual("d" * 40, metadata["integration_tree_sha"])
            self.assertEqual(64, len(metadata["diff_sha256"]))
            self.assertEqual(len(binary_diff), metadata["review_bytes"])
            self.assertEqual(3, metadata["schema_version"])

    def test_complete_input_binds_every_protected_asset_and_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = {
                "materializer_sha256": root / "materializer.py",
                "prompt_sha256": root / "prompt.md",
                "schema_sha256": root / "schema.json",
                "workflow_sha256": root / "workflow.yml",
            }
            for index, path in enumerate(assets.values(), start=1):
                path.write_text(f"protected asset {index}\n", encoding="utf-8")
            metadata = {
                "schema_version": 3,
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "diff_sha256": "c" * 64,
            }
            first = self.module.bind_protected_assets(metadata, assets)
            second = self.module.bind_protected_assets(metadata, assets)
            self.assertEqual(first, second)
            self.assertEqual(64, len(first["input_sha256"]))
            for key in assets:
                self.assertEqual(64, len(first[key]))

            assets["prompt_sha256"].write_text("tampered prompt\n", encoding="utf-8")
            tampered = self.module.bind_protected_assets(metadata, assets)
            self.assertNotEqual(first["prompt_sha256"], tampered["prompt_sha256"])
            self.assertNotEqual(first["input_sha256"], tampered["input_sha256"])

    def test_protected_asset_reader_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("protected\n", encoding="utf-8")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaisesRegex(self.module.MaterializationError, "unavailable|non-symlink"):
                self.module.protected_asset_bytes(link, "prompt")

    def test_empty_and_oversized_diffs_fail_closed(self) -> None:
        for name, diff in (("empty", b""), ("oversized", b"x" * 200_000)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaisesRegex(
                    self.module.MaterializationError,
                    "must contain 1..199999 bytes",
                ):
                    self.materialize(diff, Path(temporary) / "review")

    def test_dispatch_must_run_from_exact_protected_base(self) -> None:
        self.arguments.dispatch_ref = "refs/heads/main"
        with self.assertRaisesRegex(self.module.MaterializationError, "protected pull-request base ref"):
            self.module.validate_inputs(self.arguments)
        self.arguments.dispatch_ref = "refs/heads/develop"
        self.arguments.trusted_workflow_sha = "e" * 40
        with self.assertRaisesRegex(self.module.MaterializationError, "workflow SHA"):
            self.module.validate_inputs(self.arguments)

    def test_live_binding_rejects_non_release_app_author(self) -> None:
        payload = {
            "state": "open",
            "draft": False,
            "user": {"login": "another-bot[bot]", "type": "Bot"},
            "base": {
                "ref": self.arguments.base_ref,
                "sha": self.arguments.expected_base,
                "repo": {"full_name": self.arguments.repository},
            },
            "head": {
                "sha": self.arguments.expected_head,
                "repo": {"full_name": self.arguments.repository},
            },
        }
        completed = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        with (
            mock.patch.dict(os.environ, {"GH_TOKEN": "unit-test-token"}),
            mock.patch.object(self.module, "executable", return_value="/usr/bin/gh"),
            mock.patch.object(self.module, "run", return_value=completed),
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(self.module.MaterializationError, "unauthorized"),
        ):
            self.module.read_live_pull_request(self.arguments, home=Path(temporary))


class ExactRevisionWorkflowContractTests(unittest.TestCase):
    def test_release_app_review_is_protected_and_final_revision_only(self) -> None:
        workflow = (ROOT / ".github/workflows/release-bot-exact-head-review.yml").read_text(encoding="utf-8")
        trigger = workflow.split("on:", 1)[1].split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", trigger)
        self.assertNotIn("pull_request_target:", trigger)
        self.assertNotIn("opened", trigger)
        self.assertNotIn("synchronize", trigger)
        self.assertIn("github.actor == 'lightning-it-release-automation[bot]'", workflow)
        self.assertIn("checks: write", workflow)
        self.assertNotIn("actions/checkout@", workflow)
        self.assertIn("materialize-exact-revision-review.py?ref=${TRUSTED_WORKFLOW_SHA}", workflow)
        self.assertIn("permission-profile: :read-only", workflow)
        self.assertIn("codex-args: '[\"--ephemeral\"]'", workflow)
        self.assertIn("-f name='Current revision review'", workflow)
        self.assertIn("mlx90-exact-revision:v3:${input_sha256}", workflow)
        self.assertIn("automatic retry is forbidden", workflow)
        self.assertIn("input_sha256 == $bound.input_sha256", workflow)
        self.assertIn('and .path == ".github/workflows/release-bot-exact-head-review.yml"', workflow)
        self.assertIn("and .display_title == $title", workflow)
        self.assertIn("and .triggering_actor.login == $actor", workflow)
        self.assertIn("and .run_attempt == 1", workflow)
        self.assertEqual(1, workflow.count("uses: openai/codex-action@"))

    def test_ruleset_workflow_verifies_the_producer_instead_of_trusting_a_check_name(self) -> None:
        rerun = (ROOT / ".github/workflows/current-revision-rerun.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", rerun)
        self.assertIn("test \"${GITHUB_REF}\" = refs/heads/develop", rerun)
        self.assertIn(
            '.path == ".github/workflows/supplementary-current-revision-required.yml"',
            rerun,
        )
        self.assertIn(
            '.name == "Protected Supplementary current-revision evidence verifier"',
            rerun,
        )
        self.assertIn("test \"$(jq -r .run_attempt <<<\"${run}\")\" -eq 1", rerun)
        self.assertEqual(1, rerun.count('/rerun\" >/dev/null'))

    def test_review_producers_request_only_the_protected_verifier_rerun(self) -> None:
        for name in ("copilot-review.yml", "release-bot-exact-head-review.yml"):
            with self.subTest(workflow=name):
                workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
                rerun_job = workflow.split("  request-protected-verifier-reevaluation:", 1)[1]
                self.assertIn("actions: write", rerun_job)
                self.assertIn("current-revision-rerun.yml/dispatches", rerun_job)
                self.assertIn("-f ref=develop", rerun_job)
                self.assertNotIn("openai/codex-action@", rerun_job)

    def test_release_app_pull_requests_do_not_enter_the_copilot_job(self) -> None:
        workflow = (ROOT / ".github/workflows/copilot-review.yml").read_text(encoding="utf-8")
        request_job = workflow.split("  request-current-revision-review:", 1)[1].split(
            "  verify-current-revision-policy:", 1
        )[0]
        review_job = workflow.split("  verify-current-revision-policy:", 1)[1]
        self.assertIn("github.event.pull_request.user.login == 'litroc'", request_job)
        self.assertIn("Contributor-funded review required", request_job)
        self.assertIn("pull_request_target:", workflow)
        self.assertNotIn("pull_request_review:", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        condition = review_job.split("    if: >-", 1)[1].split("    permissions:", 1)[0]
        self.assertIn("github.event.pull_request.user.login != 'lightning-it-release-automation[bot]'", condition)
        self.assertIn("name: Verify current revision policy", review_job)
        self.assertNotIn("\n    name: Current revision review\n", workflow)
        self.assertNotIn("\n    name: Successful Copilot review\n", workflow)
        self.assertIn('-f name="${check_name}"', review_job)
        self.assertIn('test "${EVENT_BASE}" = "${TRUSTED_WORKFLOW_SHA}"', review_job)

    def test_release_app_pr_creators_finalize_draft_once(self) -> None:
        for name in (
            "promote-develop-to-main.yml",
            "sync-main-to-develop.yml",
            "release-prepare.yml",
            "release-back-sync.yml",
        ):
            with self.subTest(workflow=name):
                workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
                self.assertIn("--draft", workflow)
                self.assertIn("gh pr ready", workflow)
                self.assertIn("lightning-it-release-automation[bot]", workflow)
                self.assertIn("gh workflow run release-bot-exact-head-review.yml", workflow)
                self.assertIn("expected_base=", workflow)
                self.assertIn("expected_head=", workflow)
                self.assertLess(
                    workflow.index("gh pr ready"),
                    workflow.index("gh workflow run release-bot-exact-head-review.yml"),
                )

    def test_release_app_is_denied_from_copilot_remediation(self) -> None:
        workflow = (ROOT / ".github/workflows/codex-copilot-remediation.yml").read_text(encoding="utf-8")
        dispatch = workflow.split("  continue-after-push:", 1)[1].split("  inspect:", 1)[0]
        inspect = workflow.split("  inspect:", 1)[1].split("  retry-copilot-service:", 1)[0]
        self.assertIn("!= 'lightning-it-release-automation[bot]'", dispatch)
        self.assertIn("= 'lightning-it-release-automation[bot]'", inspect)
        self.assertLess(inspect.index("Release-App pull requests use only"), inspect.index("retry=true"))

    def test_external_contributors_are_never_auto_funded(self) -> None:
        workflow = (ROOT / ".github/workflows/copilot-review.yml").read_text(encoding="utf-8")
        request_job = workflow.split("  request-current-revision-review:", 1)[1].split(
            "  verify-current-revision-policy:", 1
        )[0]
        self.assertIn("github.event.pull_request.user.login == 'litroc'", request_job)
        self.assertIn("Contributor-funded review required", request_job)
        policy = (ROOT / "docs/mlx90-exact-revision-codex-review.md").read_text(encoding="utf-8")
        self.assertIn("exact account\n`litroc`", policy)
        self.assertIn("under their own", policy)
        self.assertIn("never requests or funds", policy)


if __name__ == "__main__":
    unittest.main()
