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


class PushReadyEngineTests(unittest.TestCase):
    def test_bootstrap_config(self) -> None:
        change = ENGINE["PlannedChange"]("base", "a" * 40, "a" * 40, "b" * 40, "", (), {}, "c" * 64)
        function_globals = ENGINE["require_review_bootstrap_contract"].__globals__
        original = function_globals["git_tree_entry"]
        try:
            function_globals["git_tree_entry"] = lambda commit, _path: "entry" if commit == "b" * 40 else ""
            ENGINE["require_review_bootstrap_contract"](change)
            function_globals["git_tree_entry"] = lambda commit, path: (
                "entry" if commit == "b" * 40 or path == ".lit/push-ready.json" else ""
            )
            with self.assertRaisesRegex(RuntimeError, "bootstrap is incomplete"):
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
            git = shutil.which("git")
            self.assertIsNotNone(git)
            environment = ENGINE["isolated_git_environment"]({"PATH": os.environ["PATH"]})
            subprocess.run([git, "init", "-q", repository], check=True, env=environment)  # noqa: S603
            (repository / "safe.txt").write_text("safe\n", encoding="utf-8")
            subprocess.run([git, "-C", repository, "add", "safe.txt"], check=True, env=environment)  # noqa: S603
            commit = [git, "-C", repository, "-c", "user.name=Test", "-c", "user.email=test@invalid"]
            subprocess.run([*commit, "commit", "-q", "-m", "root"], check=True, env=environment)  # noqa: S603
            self.assertRegex(
                ENGINE["require_history_free_review_workspace"](repository, source_commits=("f" * 40,)),
                r"^[0-9a-f]{40}$",
            )

    def test_integration_checks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository = Path(temporary_directory).resolve() / "repository"
            git = shutil.which("git")
            self.assertIsNotNone(git)
            environment = ENGINE["isolated_git_environment"]({"PATH": os.environ["PATH"]})
            subprocess.run([git, "init", "-q", repository], check=True, env=environment)  # noqa: S603
            command = [git, "-C", repository, "-c", "user.name=Test", "-c", "user.email=test@invalid"]
            commits = []
            for message in ("base", "head"):
                (repository / "value.txt").write_text(message + "\n", encoding="utf-8")
                subprocess.run([git, "-C", repository, "add", "value.txt"], check=True, env=environment)  # noqa: S603
                subprocess.run([*command, "commit", "-q", "-m", message], check=True, env=environment)  # noqa: S603
                commits.append(
                    subprocess.check_output(  # noqa: S603
                        [git, "-C", repository, "rev-parse", "HEAD"], env=environment, text=True
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
            git = shutil.which("git")
            self.assertIsNotNone(git)
            environment = ENGINE["isolated_git_environment"]({"PATH": os.environ["PATH"]})
            subprocess.run([git, "init", "-q", repository], check=True, env=environment)  # noqa: S603
            subprocess.run(  # noqa: S603
                [
                    git,
                    "-C",
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
                ],
                check=True,
                env=environment,
            )
            (repository / "scripts").mkdir()
            shutil.copy2(ROOT / "scripts" / "validate-embedded-code.py", repository / "scripts")
            (repository / "staged.md").write_text("```yaml\ninvalid: [\n```\n", encoding="utf-8")
            subprocess.run([git, "-C", repository, "add", "staged.md"], check=True, env=environment)  # noqa: S603
            subprocess.run(  # noqa: S603
                [git, "-C", repository, "update-ref", "refs/remotes/origin/develop", "HEAD"],
                check=True,
                env=environment,
            )  # noqa: S603
            quality["check_embedded_code"].__globals__["ROOT"] = repository
            with mock.patch.dict(os.environ, environment, clear=True):
                with self.assertRaises(subprocess.CalledProcessError):
                    quality["check_embedded_code"]()

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
                    (markdown / name).write_text(f"```{language}\n[]\n```\n", encoding="utf-8")
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
