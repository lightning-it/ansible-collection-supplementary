from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPT = Path(__file__).parents[2] / "scripts" / "lit-trust-root-base-verifier.py"
SPEC = importlib.util.spec_from_file_location("trust_root_base_verifier", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)


class TrustRootBaseVerifierTests(unittest.TestCase):
    def test_requires_full_lowercase_git_object_ids(self) -> None:
        value = "a" * 40
        self.assertEqual(value, VERIFIER.require_full_object_id(value, "test"))
        for invalid in ("a" * 39, "A" * 40, "z" * 40):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(RuntimeError, "full Git object ID"):
                    VERIFIER.require_full_object_id(invalid, "test")

    def test_accepts_verifier_commands(self) -> None:
        with mock.patch.object(VERIFIER, "install") as install:
            self.assertEqual(0, VERIFIER.main(["install"]))
        install.assert_called_once_with()
        for command in ("push-ready", "pre-push"):
            with self.subTest(command=command):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    VERIFIER.main([command])

    def test_refreshed_base_must_match_pinned_base(self) -> None:
        with mock.patch.object(VERIFIER, "git_text", return_value="a" * 40):
            VERIFIER.require_unchanged_base("a" * 40)
        with mock.patch.object(VERIFIER, "git_text", return_value="b" * 40):
            with self.assertRaisesRegex(RuntimeError, "Base advanced"):
                VERIFIER.require_unchanged_base("a" * 40)

    def test_public_base_refresh_removes_credentials_and_interaction(self) -> None:
        completed = SimpleNamespace(returncode=0)
        token_environment = {
            "AWS_SECRET_ACCESS_KEY": "private",
            "CODEX_API_KEY": "private",
            "COPILOT_GITHUB_TOKEN": "private",
            "CUSTOM_PRIVATE_TOKEN": "private",
            "GH_TOKEN": "private",
            "GITHUB_TOKEN": "private",
            "GIT_ASKPASS": "private",
            "GIT_CONFIG_COUNT": "1",
            "GIT_SSH_COMMAND": "private",
            "HTTPS_PROXY": "https://private.invalid",
            "OPENAI_API_KEY": "private",
            "PATH": os.environ.get("PATH", ""),
            "SSH_ASKPASS": "private",
        }
        with (
            mock.patch.object(VERIFIER, "require_safe_fetch_configuration") as safe_configuration,
            mock.patch.object(VERIFIER.subprocess, "run", return_value=completed) as run,
            mock.patch.dict(VERIFIER.os.environ, token_environment, clear=True),
        ):
            VERIFIER.refresh_public_base()
        safe_configuration.assert_called_once_with()
        command = run.call_args.args[0]
        environment = run.call_args.kwargs["env"]
        self.assertIn("credential.helper=", command)
        self.assertIn("core.askPass=", command)
        self.assertIn("http.extraHeader=", command)
        self.assertIn("http.proxy=", command)
        self.assertIn("https.proxy=", command)
        self.assertIn("core.hooksPath=/dev/null", command)
        self.assertIn(VERIFIER.PUBLIC_ORIGIN, command)
        self.assertEqual(
            {
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "LC_ALL": "C",
                "PATH": os.defpath,
            },
            environment,
        )

    def test_fetch_configuration_accepts_only_expected_local_keys_and_origin(self) -> None:
        local_names = "\n".join(
            (
                "core.repositoryformatversion",
                "core.filemode",
                "core.bare",
                "core.logallrefupdates",
                "core.ignorecase",
                "core.precomposeunicode",
                "remote.origin.url",
                "remote.origin.fetch",
                "branch.agent/mlx90.remote",
                "branch.agent/mlx90.merge",
            )
        )
        with mock.patch.object(
            VERIFIER,
            "public_git_output",
            side_effect=(local_names, VERIFIER.PUBLIC_ORIGIN),
        ):
            VERIFIER.require_safe_fetch_configuration()

    def test_fetch_configuration_rejects_credential_proxy_include_and_url_rewrite(self) -> None:
        for unsafe in (
            "credential.helper",
            "http.proxy",
            "include.path",
            "url.https://evil.invalid/.insteadof",
        ):
            with self.subTest(unsafe=unsafe):
                with (
                    mock.patch.object(VERIFIER, "public_git_output", return_value=f"remote.origin.url\n{unsafe}"),
                    self.assertRaisesRegex(RuntimeError, "rejects local Git configuration"),
                ):
                    VERIFIER.require_safe_fetch_configuration()

    def test_fetch_configuration_rejects_any_other_origin(self) -> None:
        with (
            mock.patch.object(
                VERIFIER,
                "public_git_output",
                side_effect=("remote.origin.url", "https://example.invalid/repository.git"),
            ),
            self.assertRaisesRegex(RuntimeError, "canonical public origin"),
        ):
            VERIFIER.require_safe_fetch_configuration()

    def test_base_blob_digest_mismatch_stops_before_execution(self) -> None:
        values = iter(("a" * 40, "b" * 40, "c" * 40))
        with (
            mock.patch.object(VERIFIER, "git_text", side_effect=lambda *args, **kwargs: next(values)),
            mock.patch.object(
                VERIFIER,
                "run_git",
                return_value=b"print('must not execute')\n",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "blob digest changed"):
                VERIFIER.load_base_engine()

    def test_base_engine_blob_is_bound_to_pinned_commit_when_ref_moves(self) -> None:
        pinned = "a" * 40
        pinned_blob = "b" * 40
        calls: list[tuple[str, ...]] = []

        def git_text(*args, **_kwargs) -> str:
            calls.append(args)
            if args == ("rev-parse", "--verify", f"{VERIFIER.BASE_REF}^{{commit}}"):
                return pinned
            if args == ("rev-parse", "--verify", f"{pinned}:{VERIFIER.ENGINE_PATH}"):
                return pinned_blob
            if args == ("hash-object", "--stdin"):
                return pinned_blob
            self.fail(f"unexpected mutable-ref lookup: {args}")

        with (
            mock.patch.object(VERIFIER, "git_text", side_effect=git_text),
            mock.patch.object(VERIFIER, "run_git", return_value=b"loaded_from_pinned_base = True\n"),
        ):
            engine, base_commit, blob = VERIFIER.load_base_engine()

        self.assertTrue(engine["loaded_from_pinned_base"])
        self.assertEqual((pinned, pinned_blob), (base_commit, blob))
        self.assertNotIn(("rev-parse", "--verify", f"{VERIFIER.BASE_REF}:{VERIFIER.ENGINE_PATH}"), calls)

    def test_candidate_engine_path_rejects_symlinks_and_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            engine = scripts / "lit-push-ready.py"
            engine.write_text("# engine\n", encoding="utf-8")
            with mock.patch.object(VERIFIER, "ROOT", root):
                self.assertEqual(engine.resolve(), VERIFIER.candidate_engine_path())
                engine.unlink()
                engine.symlink_to(root / "inside.py")
                with self.assertRaisesRegex(RuntimeError, "must not be a symlink"):
                    VERIFIER.candidate_engine_path()
                engine.unlink()
                engine.symlink_to(Path(temporary).parent / "outside.py")
                with self.assertRaisesRegex(RuntimeError, "must not be a symlink"):
                    VERIFIER.candidate_engine_path()

    def test_cached_controller_check_does_not_require_python_3_10_stat_keyword(self) -> None:
        source = b"#!/usr/bin/env python3\n"
        digest = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            cached = Path(temporary) / "cached-controller.py"
            cached.write_bytes(source)
            cached.chmod(0o700)
            with (
                mock.patch.object(VERIFIER, "cached_controller_path", return_value=cached),
                mock.patch.object(VERIFIER, "base_controller_source", return_value=(source, digest)),
                mock.patch.object(VERIFIER, "git_text", return_value=digest),
                mock.patch.object(Path, "stat", side_effect=AssertionError("Path.stat must not be used")),
            ):
                VERIFIER.require_cached_base_controller("b" * 40)

    def test_owned_file_mode_is_exact_under_restrictive_umask(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "controller.py"
            previous = os.umask(0o777)
            try:
                VERIFIER.write_owned_regular_file(target, b"verified\n", mode=0o700)
            finally:
                os.umask(previous)
            details = os.stat(target, follow_symlinks=False)
            self.assertTrue(stat.S_ISREG(details.st_mode))
            self.assertEqual(0o700, stat.S_IMODE(details.st_mode))
            self.assertEqual(b"verified\n", target.read_bytes())

    def test_owned_file_rejects_an_existing_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "controller.py"
            target.symlink_to(root / "outside.py")
            with self.assertRaisesRegex(RuntimeError, "target is unsafe"):
                VERIFIER.write_owned_regular_file(target, b"verified\n", mode=0o700)

    def test_cached_controller_symlink_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.py"
            source.write_bytes(b"must not execute\n")
            cached = root / "cached.py"
            cached.symlink_to(source)
            with (
                mock.patch.object(VERIFIER, "cached_controller_path", return_value=cached),
                self.assertRaisesRegex(RuntimeError, "unavailable"),
            ):
                VERIFIER.read_cached_controller()

    def test_cached_controller_fifo_is_rejected_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cached = Path(temporary) / "cached.py"
            os.mkfifo(cached, mode=0o700)
            with (
                mock.patch.object(VERIFIER, "cached_controller_path", return_value=cached),
                self.assertRaisesRegex(RuntimeError, "unsafe"),
            ):
                VERIFIER.read_cached_controller()

    def test_oversized_cached_controller_is_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cached = Path(temporary) / "cached.py"
            with cached.open("wb") as handle:
                handle.truncate(VERIFIER.MAX_CONTROLLER_BYTES + 1)
            cached.chmod(0o700)
            with (
                mock.patch.object(VERIFIER, "cached_controller_path", return_value=cached),
                self.assertRaisesRegex(RuntimeError, "unsafe"),
            ):
                VERIFIER.read_cached_controller()

    def test_controller_has_no_local_external_review_or_hook_installer(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("run_agent_reviews", source)
        self.assertNotIn("install_base_verified_pre_push_hook", source)
        self.assertNotIn("gh auth", source)
        self.assertNotIn("verify_pre_push_updates", source)
        self.assertNotIn("def pre_push", source)
        self.assertNotIn('"push-ready"', source)

    def test_controller_binding_requires_an_existing_unchanged_base_controller(self) -> None:
        change = SimpleNamespace(
            base_ref=VERIFIER.BASE_REF,
            base_tip="b" * 40,
            head_commit="a" * 40,
        )
        engine = {"git_tree_entry": mock.Mock(side_effect=("", "candidate-blob"))}
        with self.assertRaisesRegex(RuntimeError, "absent from the pinned Base"):
            VERIFIER.require_controller_binding(engine, change)
        engine["git_tree_entry"] = mock.Mock(side_effect=("base-blob", ""))
        with self.assertRaisesRegex(RuntimeError, "missing from the candidate"):
            VERIFIER.require_controller_binding(engine, change)
        engine["git_tree_entry"] = mock.Mock(side_effect=("base-blob", "base-blob"))
        self.assertIsNone(VERIFIER.require_controller_binding(engine, change))

    def test_evidence_verification_uses_a_narrow_base_policy_override(self) -> None:
        change = SimpleNamespace(base_ref=VERIFIER.BASE_REF, base_tip="b" * 40, head_commit="a" * 40)
        original_policy = mock.Mock()
        payload = {"fixture_manifest_bootstrap": False}
        engine = {
            "require_clean_head": mock.Mock(),
            "planned_change": mock.Mock(return_value=change),
            "git_tree_entry": mock.Mock(side_effect=("controller", "controller")),
            "require_trust_root_update_contract": mock.Mock(),
            "require_trusted_check_policy": original_policy,
            "verify_evidence": mock.Mock(return_value=payload),
        }
        with (
            mock.patch.object(VERIFIER, "refresh_public_base"),
            mock.patch.object(VERIFIER, "require_unchanged_base") as unchanged,
            mock.patch.object(VERIFIER, "require_cached_base_controller"),
        ):
            self.assertEqual(payload, VERIFIER.verify_trust_root_evidence(engine, {}, "b" * 40))
        self.assertIs(engine["require_trusted_check_policy"], original_policy)
        self.assertEqual(2, unchanged.call_count)
        engine["verify_evidence"].assert_called_once_with({})

    def test_install_seeds_only_an_unchanged_base_checkout(self) -> None:
        engine = {
            "require_clean_head": mock.Mock(),
        }
        with (
            mock.patch.object(VERIFIER, "refresh_public_base"),
            mock.patch.object(VERIFIER, "load_base_engine", return_value=(engine, "b" * 40, "c" * 40)),
            mock.patch.object(VERIFIER, "require_unchanged_base") as unchanged,
            mock.patch.object(VERIFIER, "require_base_checkout") as base_checkout,
            mock.patch.object(VERIFIER, "install_cached_base_controller") as install_cache,
            mock.patch.object(VERIFIER, "require_cached_base_controller") as cached,
        ):
            VERIFIER.install()
        base_checkout.assert_called_once_with("b" * 40)
        install_cache.assert_called_once_with("b" * 40)
        cached.assert_called_once_with("b" * 40)
        self.assertEqual(2, unchanged.call_count)
