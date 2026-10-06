"""SINGLE resource evidence and preallocation bounds, with no provider calls."""

import importlib.util
import json
import resource
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("single_resources_fixture", ROOT / "scripts/single_review_resources.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SingleResourcesTests(unittest.TestCase):
    def test_finite_cgroup_ancestor_binds_unlimited_leaf_and_large_host(self):
        for v2 in (True, False):
            maximum = "memory.max" if v2 else "memory.limit_in_bytes"
            current = "memory.current" if v2 else "memory.usage_in_bytes"
            files = {
                "/proc/meminfo": "MemAvailable: 134217728 kB\n",
                "/proc/self/cgroup": "0::/jobs/review\n" if v2 else "9:memory:/jobs/review\n",
                "/proc/self/mountinfo": "1 0 0:1 / /sys/fs/cgroup rw - "
                + ("cgroup2 cgroup rw" if v2 else "cgroup cgroup rw,memory"),
            }
            for directory in ("/sys/fs/cgroup", "/sys/fs/cgroup/jobs/review"):
                files[directory + "/" + maximum] = "max" if v2 else str(2**63 - 1)
                files[directory + "/" + current] = "0"
            files["/sys/fs/cgroup/jobs/" + maximum] = str(256 * 1024**2)
            files["/sys/fs/cgroup/jobs/" + current] = str(128 * 1024**2)
            with (
                self.subTest(v2=v2),
                patch.object(Path, "read_text", lambda p, files=files, **kw: files[str(p)]),
                patch.object(resource, "getrlimit", return_value=(resource.RLIM_INFINITY, resource.RLIM_INFINITY)),
            ):
                contract = MODULE.memory_contract()
            self.assertEqual(128 * 1024**2, contract["observed"]["cgroup_ancestor_1_available_bytes"])
            self.assertEqual(64 * 1024**2, contract["reserved_bytes"])
            self.assertLess(contract["max_wire_bytes"], 2 * 1024**2)

    def test_v2_global_root_has_no_limit_but_child_and_subtree_limits_remain_required(self):
        files = {
            "/proc/self/cgroup": "0::/jobs/review\n",
            "/proc/self/mountinfo": "1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw",
            "/sys/fs/cgroup/cgroup.controllers": "cpu memory pids",
            "/sys/fs/cgroup/jobs/review/memory.max": "max",
            "/sys/fs/cgroup/jobs/memory.max": str(256 * 1024**2),
            "/sys/fs/cgroup/jobs/memory.current": str(128 * 1024**2),
        }

        def read(path, **kwargs):
            if str(path) not in files:
                raise FileNotFoundError(str(path))
            return files[str(path)]

        with patch.object(Path, "read_text", read):
            self.assertEqual({"cgroup_ancestor_1_available_bytes": 128 * 1024**2}, MODULE.cgroup_headroom())
            del files["/sys/fs/cgroup/jobs/review/memory.max"]
            with self.assertRaises(FileNotFoundError):
                MODULE.cgroup_headroom()
            files["/proc/self/cgroup"] = "0::/jobs\n"
            files["/proc/self/mountinfo"] = "1 0 0:1 /jobs /sys/fs/cgroup rw - cgroup2 cgroup rw"
            with self.assertRaises(FileNotFoundError):
                MODULE.cgroup_headroom()

    def test_namespaced_mount_root_retains_its_actual_limit(self):
        import os

        files = {
            "/proc/self/cgroup": "0::/\n",
            "/proc/self/mountinfo": "1 0 0:1 /jobs/review /sys/fs/cgroup rw - cgroup2 cgroup rw",
            "/sys/fs/cgroup/cgroup.procs": str(os.getpid()),
            "/sys/fs/cgroup/memory.max": str(256 * 1024**2),
            "/sys/fs/cgroup/memory.current": str(128 * 1024**2),
        }
        with patch.object(Path, "read_text", lambda p, files=files, **kw: files[str(p)]):
            self.assertEqual({"cgroup_ancestor_0_available_bytes": 128 * 1024**2}, MODULE.cgroup_headroom())

    def test_unknown_or_ambiguous_cgroup_fails_closed(self):
        for membership in ("", "0::/one\n0::/two\n", "0::/../escape\n"):

            def read(path, membership=membership, **kwargs):
                if str(path) == "/proc/self/cgroup":
                    return membership
                return "1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw"

            with (
                self.subTest(membership=membership),
                patch.object(Path, "read_text", read),
                self.assertRaises(ValueError),
            ):
                MODULE.cgroup_headroom()

    def test_lexical_preflight_limits_nodes_depth_and_ignores_string_punctuation(self):
        body = json.dumps({"text": '[{\\" punctuation }]' * 100_000}).encode()
        MODULE.preflight_json(body, 3, 1)
        for payload in (json.dumps([{}] * 80_000).encode(), b"[" * 65 + b"0" + b"]" * 65):
            with self.assertRaises(ValueError):
                MODULE.preflight_json(payload, MODULE.MAX_JSON_NODES, MODULE.MAX_JSON_DEPTH)

    def test_missing_memory_evidence_cannot_grant_admission(self):
        with patch.object(Path, "read_text", return_value=""), self.assertRaises(ValueError):
            MODULE.memory_contract()
