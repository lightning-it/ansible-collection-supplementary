"""Real Git/workspace regressions for the two native resource-bound findings."""

import hashlib
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from .test_protected_review_instructions import GitPolicies
except ImportError:
    from test_protected_review_instructions import GitPolicies

ROOT = Path(__file__).resolve().parents[2]


class ReviewResourceBoundaryTests(unittest.TestCase):
    def test_workspace_scan_budget_is_aggregate_across_tracked_files(self):
        script = ROOT / "default/scripts/lit-push-ready.py"
        if not script.exists():
            script = ROOT / "scripts/lit-push-ready.py"
        spec = importlib.util.spec_from_file_location("scan_budget_engine", script)
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        self.assertEqual(500_000_000, engine.MAX_TRACKED_WORKSPACE_SCAN_BYTES)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
            subprocess.run(["git", "init", "-q", str(root)], env=env, check=True)  # noqa: S603, S607 -- fixed repository/fixture command and isolated environment.
            for name in ("a.txt", "b.txt"):
                (root / name).write_bytes(b"plain\n")
            subprocess.run(["git", "-C", str(root), "add", "."], env=env, check=True)  # noqa: S603, S607 -- fixed repository/fixture command and isolated environment.
            with patch.object(engine, "MAX_TRACKED_WORKSPACE_SCAN_BYTES", 12), patch.object(engine, "CHUNK_BYTES", 2):
                engine.streaming_workspace_safe(root, {})
                (root / "c.txt").write_bytes(b"plain\n")
                subprocess.run(["git", "-C", str(root), "add", "."], env=env, check=True)  # noqa: S603, S607 -- fixed repository/fixture command and isolated environment.
                with self.assertRaisesRegex(RuntimeError, "tracked workspace scan.*resource budget"):
                    engine.streaming_workspace_safe(root, {})

    def policy_fixture(self, directory):
        fixture = GitPolicies(Path(directory))
        agents = "Protected policy.\n"
        fixture.files = {
            "AGENTS.md": agents,
            ".github/copilot-instructions.md": "<!-- AGENTS_SHA256: "
            + hashlib.sha256(agents.encode()).hexdigest()
            + " -->\n",
            "src/AGENTS.md": "Scoped source policy.\n",
            ".github/instructions/python.instructions.md": '---\napplyTo: "**/*.py"\n---\nPython policy.\n',
        }
        return fixture

    def add_paths(self, fixture, paths):
        fixture.commit()
        blob = fixture.git("hash-object", "-w", "--stdin", data=b"Unrelated file.\n")
        records = b"".join(b"100644 " + blob + b"\t" + path + b"\0" for path in paths)
        fixture.git("update-index", "-z", "--index-info", data=records)
        tree = fixture.git("write-tree").decode()
        return fixture.git("commit-tree", tree, data=b"Inventory fixture\n").decode()

    def test_over_one_mb_unrelated_tree_preserves_complete_small_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.policy_fixture(directory)
            base = fixture.commit()
            expected = fixture.bundle(base)["files"]
            revision = self.add_paths(fixture, [f"data/{index:05}-{'x' * 80}.txt".encode() for index in range(9000)])
            listing = fixture.git("ls-tree", "-r", "-z", revision)
            self.assertGreater(len(listing), fixture.module.MAX_PROTECTED_ASSET_BYTES)
            actual = fixture.bundle(revision)
            self.assertEqual(revision, actual["source_sha"])
            self.assertEqual(expected, actual["files"])

    def test_unrelated_non_utf8_path_is_filtered_before_decoding(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.policy_fixture(directory)
            expected = fixture.bundle(fixture.commit())["files"]
            revision = self.add_paths(fixture, [b"data/non-utf8-\xff.txt"])
            self.assertEqual(expected, fixture.bundle(revision)["files"])
            selected = self.add_paths(fixture, [b"scope-\xff/AGENTS.md"])
            with self.assertRaises(UnicodeDecodeError):
                fixture.bundle(selected)

    def test_selected_instruction_inventory_and_content_remain_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self.policy_fixture(directory)
            revision = self.add_paths(
                fixture, [f"scope/{index:05}-{'x' * 80}/AGENTS.md".encode() for index in range(9000)]
            )
            with self.assertRaisesRegex(fixture.module.MaterializationError, "protected byte limit"):
                fixture.bundle(revision)
            files = fixture.files | {"src/AGENTS.md": "x" * fixture.module.MAX_PROTECTED_ASSET_BYTES}
            revision = fixture.commit(files)
            with self.assertRaisesRegex(fixture.module.MaterializationError, "metadata exceeds its resource limit"):
                fixture.bundle(revision)
