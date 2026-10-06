"""Exercise complete streaming through the Supplementary engine and local policy."""

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .test_push_ready_engine import ENGINE, ROOT, run_git


class PortStreamingTests(unittest.TestCase):
    def test_secret_patterns_match_across_chunk_boundaries(self):
        patterns = (*ENGINE["SECRET_CONTENT_PATTERNS"], ENGINE["NPMRC_AUTH_PATTERN"])
        machine = ENGINE["StreamingPatterns"](patterns)
        for text in ("safe ä𐍈\n", "password" + " " * 70000 + "=" + "a" * 20, "ghp_" + "a" * 20):
            expected = sum(1 << i for i, pattern in enumerate(patterns) if pattern.search(text))
            for width in (1, 137, 65536):
                scanner = machine.scanner()
                for offset in range(0, len(text), width):
                    scanner.feed(text[offset : offset + width])
                self.assertEqual(expected, scanner.finish())

    def test_local_planning_fingerprint_scan_and_classification_never_materialize_patch(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve() / "repo"
            env = ENGINE["isolated_git_environment"]({"PATH": os.environ["PATH"]})
            run_git(repo, "init", "-q", environment=env)
            (repo / "docs").mkdir()
            (repo / "docs/change.txt").write_text("before\n")
            run_git(repo, "add", ".", environment=env)
            run_git(
                repo,
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.invalid",
                "commit",
                "-qm",
                "base",
                environment=env,
            )
            base = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], env=env, text=True).strip()  # noqa: S603, S607
            (repo / "docs/change.txt").write_text("safe ä𐍈 text\n" * 12000 + "permission\n")
            (repo / "untracked.txt").write_text("complete\n" * 1000)
            config = json.loads((ROOT / ".lit/push-ready.json").read_text())
            namespace = ENGINE["planned_change"].__globals__
            with (
                mock.patch.dict(
                    namespace,
                    {
                        "ROOT": repo,
                        "resolve_base": lambda *_a, **_kw: ("refs/remotes/origin/develop", base, base),
                        "secret_fixture_manifest_for_change": lambda *_a, **_kw: {},
                        "config_at_commit": lambda *_a: config,
                    },
                ),
                mock.patch.object(ENGINE["PatchSpool"], "as_text", side_effect=AssertionError("whole patch read")),
            ):
                change = ENGINE["planned_change"](config)
                self.addCleanup(change.patch.close)
                complete = b"".join(change.patch.chunks())
                self.assertIn(b"permission\n", complete)
                self.assertIn(b"+complete\n", complete)
                self.assertEqual(hashlib.sha256(complete).hexdigest(), change.diff_sha256)
                self.assertEqual(len(complete), ENGINE["review_size_evidence"](config, change)["bytes"])
                result = ENGINE["classify_review_profile"](change)
                self.assertEqual("trust-root-term:permission", result.reason)
                self.assertEqual("trust-root", result.profile)
                expected = {
                    "head": base,
                    "status": namespace["git_output"]("status", "--porcelain=v1", "--untracked-files=all", "-z"),
                    "diff": namespace["git_output"]("diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--"),
                    "untracked": namespace["untracked_file_hashes"](),
                }
                self.assertEqual(
                    hashlib.sha256(
                        json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
                    ).hexdigest(),
                    change.tree_fingerprint,
                )
