from __future__ import annotations

import contextlib
import json
import os
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
ENGINE = runpy.run_path(str(ROOT / "scripts" / "lit-push-ready.py"), run_name="lit_push_ready_engine_test")
GIT = shutil.which("git") or "git"


def run_git(repository: Path, *args: str, environment: dict[str, str]) -> None:
    if args[0] == "init":
        repository.mkdir()
    subprocess.run([GIT, "-C", repository, *args], check=True, env=environment)  # noqa: S603


class PushReadyEngineTests(unittest.TestCase):
    def test_trusted_policy_covers_executable_quality_scripts(self) -> None:
        trusted_paths = set(ENGINE["TRUSTED_CHECK_POLICY_PATHS"])

        self.assertIn(".pre-commit-config.yaml", trusted_paths)
        self.assertIn("scripts/lit-repository-quality.py", trusted_paths)
        self.assertIn("scripts/validate-embedded-code.py", trusted_paths)

    def test_pre_commit_policy_drift(self) -> None:
        change = ENGINE["PlannedChange"]("base", "a" * 40, "a" * 40, "b" * 40, "", (), {}, "c" * 64)
        function_globals = ENGINE["require_trusted_check_policy"].__globals__

        def tree_entry(commit: str, path: str) -> str:
            if path == ".pre-commit-config.yaml":
                return "base-entry" if commit == change.base_tip else "head-entry"
            return "stable-entry"

        with (
            mock.patch.dict(function_globals, {"git_tree_entry": tree_entry}),
            self.assertRaisesRegex(RuntimeError, r"policy differs from base: \.pre-commit-config\.yaml"),
        ):
            ENGINE["require_trusted_check_policy"](change)

    def test_review_cli_produces_push_evidence(self) -> None:
        config: dict[str, object] = {}
        change = ENGINE["PlannedChange"]("base", "a" * 40, "a" * 40, "b" * 40, "", (), {}, "c" * 64)
        produced = mock.Mock()
        replacements = {
            "check_instruction_contract": mock.Mock(),
            "load_config": mock.Mock(return_value=config),
            "require_clean_head": mock.Mock(),
            "refresh_authoritative_base": mock.Mock(),
            "planned_change": mock.Mock(return_value=change),
            "require_review_bootstrap_contract": mock.Mock(),
            "produce_evidence": produced,
        }
        function_globals = ENGINE["main"].__globals__
        with (
            mock.patch.dict(function_globals, replacements),
            mock.patch.object(function_globals["sys"], "argv", ["lit-push-ready.py", "review"]),
        ):
            self.assertEqual(0, ENGINE["main"]())
        produced.assert_called_once_with(config, change, fixture_manifest_bootstrap=False)

    def test_pre_push_hook_rejects_stale_head(self) -> None:
        config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        for marker in ("default_stages: [pre-commit]", "default_install_hook_types: [pre-commit, pre-push]"):
            self.assertIn(marker, config)
        for hook in ("ansible-lint-ee", "changelog-policy-ee", "molecule-light", "collection-smoke", "galaxy-verify"):
            self.assertIn(f"- id: {hook}", config)
        self.assertEqual(1, config.count("stages: [pre-push]"))
        profile = (ROOT / "scripts" / "lit-ci-profile.sh").read_text(encoding="utf-8")
        self.assertIn('python3 "$pre_commit_zipapp" run --all-files', profile)
        self.assertIn("${TMPDIR:-/tmp}", profile)
        self.assertRegex(profile, r'readonly PRE_COMMIT_SHA256="[0-9a-f]{64}"')
        self.assertIn('actual_sha256" = "$PRE_COMMIT_SHA256', profile)
        self.assertNotIn("pip install", profile)
        self.assertIn("SKIP=molecule-light", profile)
        self.assertIn("devtools-molecule.sh artifacts-basic", profile)
        scenario = (ROOT / "molecule" / "artifacts-basic" / "converge.yml").read_text(encoding="utf-8")
        self.assertIn("'id -u'", scenario)
        self.assertIn("'id -g'", scenario)
        self.assertNotIn("id -un", scenario)
        branch, stale, expected = "refs/heads/test", "b" * 40, "a" * 40
        payload = {
            "push_remote": ENGINE["governed_push_remote_from_url"](
                "origin", "https://github.com/lightning-it/ansible-collection-supplementary.git"
            ),
            "head_commit": expected,
            "local_branch_ref": branch,
        }
        function_globals = ENGINE["verify_pre_push_updates"].__globals__
        with (
            mock.patch.dict(function_globals, {"git_output": lambda *_args: stale}),
            self.assertRaisesRegex(RuntimeError, "not bound"),
        ):
            ENGINE["verify_pre_push_updates"](
                payload,
                f"{branch} {stale} {branch} {'0' * 40}\n",
                remote_name="origin",
                remote_url="https://github.com/lightning-it/ansible-collection-supplementary.git",
            )

    def test_container_engine_fallback(self) -> None:
        function_globals = ENGINE["copilot_container_command"].__globals__
        probe = mock.Mock(side_effect=[subprocess.CompletedProcess([], code, "") for code in (1, 0)])
        with (
            mock.patch.object(function_globals["shutil"], "which", side_effect=("/docker", "/podman")),
            mock.patch.dict(function_globals, {"run": probe}),
            mock.patch.dict(os.environ, {"WUNDER_CONTAINER_ENGINE": ""}),
        ):
            command = ENGINE["copilot_container_command"](dict(ENGINE["COPILOT_PROMPT_MODE_BOUNDARY"]), ROOT)
        self.assertEqual("/podman", command[0])
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            mock.patch.dict(os.environ, {name: "token" for name in ENGINE["COPILOT_TOKEN_NAMES"]}, clear=True),
            mock.patch.object(function_globals["shutil"], "which", return_value=None),
        ):
            environment = ENGINE["minimal_agent_environment"](state_root=Path(temporary_directory), agent="copilot")
        forwarded = [name for name in ENGINE["COPILOT_TOKEN_NAMES"] if name in environment]
        self.assertEqual(["COPILOT_GITHUB_TOKEN"], forwarded)
        with (
            mock.patch.object(function_globals["shutil"], "which", return_value="/podman"),
            mock.patch.dict(function_globals, {"run": mock.Mock(return_value=subprocess.CompletedProcess([], 0, ""))}),
        ):
            version_command = ENGINE["copilot_container_command"](environment, ROOT, include_credentials=False)
        self.assertTrue(all(name not in version_command for name in ENGINE["COPILOT_TOKEN_NAMES"]))

    def test_bootstrap_config(self) -> None:
        change = ENGINE["PlannedChange"]("base", "a" * 40, "a" * 40, "b" * 40, "", (), {}, "c" * 64)
        function_globals = ENGINE["require_review_bootstrap_contract"].__globals__
        original = function_globals["git_tree_entry"]
        try:
            function_globals["git_tree_entry"] = lambda commit, _path: "entry" if commit == "b" * 40 else ""
            self.assertTrue(ENGINE["require_review_bootstrap_contract"](change))
            function_globals["git_tree_entry"] = lambda commit, path: (
                "entry" if commit == "b" * 40 or path == ".lit/push-ready.json" else ""
            )
            with self.assertRaisesRegex(RuntimeError, "bootstrap is incomplete"):
                ENGINE["require_review_bootstrap_contract"](change)
            function_globals["git_tree_entry"] = lambda commit, path: (
                "" if commit == "b" * 40 and path == ".lit/push-ready.json" else "entry"
            )
            with self.assertRaisesRegex(RuntimeError, "lacks policy"):
                ENGINE["require_review_bootstrap_contract"](change)
        finally:
            function_globals["git_tree_entry"] = original

        with tempfile.TemporaryDirectory() as temporary_directory:
            config = json.loads((ROOT / ".lit" / "push-ready.json").read_text(encoding="utf-8"))
            config["checks"] = []
            path = Path(temporary_directory) / "push-ready.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            function_globals = ENGINE["load_config"].__globals__
            original = function_globals["CONFIG"]
            function_globals["CONFIG"] = path
            try:
                with self.assertRaisesRegex(RuntimeError, "define checks"):
                    ENGINE["load_config"]()
            finally:
                function_globals["CONFIG"] = original

    def test_history_free_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repository = root / "repository"
            environment = ENGINE["isolated_git_environment"]({"PATH": os.environ["PATH"]})
            run_git(repository, "init", "-q", environment=environment)
            (repository / "safe.txt").write_text("safe\n", encoding="utf-8")
            run_git(repository, "add", "safe.txt", environment=environment)
            run_git(
                repository,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@invalid",
                "commit",
                "-q",
                "-m",
                "root",
                environment=environment,
            )
            self.assertRegex(
                ENGINE["require_history_free_review_workspace"](repository, source_commits=("f" * 40,)),
                r"^[0-9a-f]{40}$",
            )

    def test_review_workspace_rejects_non_utf8_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = Path(tmp).resolve() / "repository"
            environment = ENGINE["isolated_git_environment"]({"PATH": os.environ["PATH"]})
            run_git(repository, "init", "-q", environment=environment)
            (repository / "invalid.bin").write_bytes(b"invalid\xff")
            run_git(repository, "add", "invalid.bin", environment=environment)
            with self.assertRaisesRegex(RuntimeError, "sanitized review file is not UTF-8: invalid.bin"):
                ENGINE["ensure_workspace_review_safe"](repository)

    def test_integration_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory).resolve() / "repository"
            environment = ENGINE["isolated_git_environment"]({"PATH": os.environ["PATH"]})
            run_git(repository, "init", "-q", environment=environment)
            commits = []
            for message in ("base", "head"):
                (repository / "value.txt").write_text(message + "\n", encoding="utf-8")
                run_git(repository, "add", "value.txt", environment=environment)
                run_git(
                    repository,
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@invalid",
                    "commit",
                    "-q",
                    "-m",
                    message,
                    environment=environment,
                )
                commits.append(
                    subprocess.check_output(  # noqa: S603
                        [GIT, "-C", repository, "rev-parse", "HEAD"], env=environment, text=True
                    ).strip()
                )
            function_globals = ENGINE["execute_integration_checks"].__globals__
            original = function_globals["ROOT"]
            function_globals["ROOT"] = repository
            try:
                change = ENGINE["PlannedChange"]("base", commits[0], commits[0], commits[1], "", (), {}, "f" * 64)
                result = ENGINE["execute_integration_checks"](
                    {"checks": [{"name": "true", "command": ["true"]}]}, change
                )
            finally:
                function_globals["ROOT"] = original
            self.assertEqual(0, result[0][0]["exit_code"])
            self.assertRegex("".join(result[1:]), r"^[0-9a-f]{144}$")

    def test_markdown_validators(self) -> None:
        quality = runpy.run_path(str(ROOT / "scripts" / "lit-repository-quality.py"))
        validator = runpy.run_path(
            str(ROOT / "scripts" / "validate-embedded-code.py"),
            run_name="embedded_code_contract_test",
        )
        runtime = __import__("sys")
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory).resolve()
            repository = root / "repository"
            environment = ENGINE["isolated_git_environment"]({"PATH": os.environ["PATH"]})
            run_git(repository, "init", "-q", environment=environment)
            run_git(
                repository,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@invalid",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "root",
                environment=environment,
            )
            (repository / "scripts").mkdir()
            shutil.copy2(ROOT / "scripts" / "validate-embedded-code.py", repository / "scripts")
            (repository / "staged.MD").write_text("~~~yaml\ninvalid: [\n~~~\n", encoding="utf-8")
            run_git(repository, "add", "staged.MD", environment=environment)
            run_git(repository, "update-ref", "refs/remotes/origin/develop", "HEAD", environment=environment)
            quality["check_embedded_code"].__globals__["ROOT"] = repository
            with mock.patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(subprocess.CalledProcessError):
                    quality["check_embedded_code"]()
            canary = root / "filter-canary"
            run_git(repository, "config", "filter.review.clean", f"touch {canary}", environment=environment)
            with self.assertRaisesRegex(AssertionError, "unsafe local Git configuration"):
                quality["check_embedded_code"]()
            self.assertFalse(canary.exists())
            with self.assertRaises(subprocess.CalledProcessError):
                quality["check_embedded_code"](["staged.MD"])

            quality["assert_file"].__globals__["ROOT"] = repository
            outside = root / "outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            linked_document = repository / "linked.md"
            linked_document.symlink_to(outside)
            with self.assertRaisesRegex(AssertionError, "non-symlink regular file"):
                quality["assert_file"](linked_document)
            directory = repository / "directory.md"
            directory.mkdir()
            with self.assertRaisesRegex(AssertionError, "non-symlink regular file"):
                quality["assert_file"](directory)

            markdown = root / "markdown"
            markdown.mkdir()
            validator["main"].__globals__["ROOT"] = markdown
            for language in ("yaml", "shell"):
                self.assertEqual(
                    "safe\n```\nunsafe\n",
                    validator["fenced_blocks"](f"````{language}\nsafe\n```\nunsafe\n````\n")[0][1],
                )
            original_argv, original_which = runtime.argv, shutil.which
            try:
                shutil.which = lambda _name: None
                for name, language in (("A.MD", "ansible"), ("s.md", "sh")):
                    fence = "~~~" if name == "s.md" else "```"
                    (markdown / name).write_text(f"{fence}{language}\n[]\n{fence}\n", encoding="utf-8")
                    runtime.argv = ["validate-embedded-code.py", name]
                    self.assertEqual(1, validator["main"]())
            finally:
                runtime.argv, shutil.which = original_argv, original_which

    def test_evidence_intervals(self) -> None:
        prefix = "2026-01-01T"
        bounds = tuple(ENGINE["parse_timestamp"](prefix + value, "test") for value in ("00:01:00Z", "00:10:00Z"))
        cases = (
            ("00:05:00Z", "00:04:00Z", 0),
            ("00:02:00Z", "00:03:00Z", 1),
            ("00:00:00Z", "00:02:00Z", 120),
            ("00:09:00Z", "00:11:00Z", 120),
        )
        for started, completed, duration in cases:
            with self.assertRaisesRegex(RuntimeError, "invalid timing"):
                ENGINE["evidence_interval"](
                    {
                        "started_at": prefix + started,
                        "completed_at": prefix + completed,
                        "duration_seconds": duration,
                    },
                    "test",
                    bounds,
                )

    def test_review_binding(self) -> None:
        change = ENGINE["PlannedChange"]("base", "a" * 40, "a" * 40, "b" * 40, "", (), {}, "f" * 64)
        function_globals = ENGINE["run_agent_reviews"].__globals__
        replacements = {
            "tree_fingerprint": lambda: "f" * 64,
            "sanitized_review_workspace": lambda *_args, **_kwargs: contextlib.nullcontext(
                (ROOT, ROOT, type("Topology", (), {"integration_tree": "d" * 40})())
            ),
            "tracked_instruction_bundle": lambda _workspace: "instructions",
            "integration_worktree_fingerprint": lambda *_args, **_kwargs: "stable",
            "copilot_review": lambda *_args, **_kwargs: {"agent": "copilot", "result": "pass"},
            "codex_review": lambda *_args, **_kwargs: {"agent": "codex", "result": "pass"},
        }
        original = {name: function_globals[name] for name in replacements}
        try:
            function_globals.update(replacements)
            reviews = ENGINE["run_agent_reviews"]({}, change)
        finally:
            function_globals.update(original)
        self.assertEqual(1, len({review["input_sha256"] for review in reviews}))
        self.assertNotEqual(
            reviews[0]["input_sha256"],
            ENGINE["review_input_sha256"](change, "d" * 40, {"changed": "e" * 64}),
        )
