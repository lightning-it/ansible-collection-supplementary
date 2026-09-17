"""Security contracts for the containerized forward proxy role."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSERTS = ROOT / "roles" / "forward_proxy" / "tasks" / "assert.yml"
RESTORE = ROOT / "roles" / "forward_proxy" / "tasks" / "restore_managed_file.yml"
README = ROOT / "roles" / "forward_proxy" / "README.md"
VERIFY = ROOT / "molecule" / "forward-proxy-tiny" / "verify.yml"
CLEANUP = ROOT / "molecule" / "forward-proxy-tiny" / "cleanup.yml"


class ForwardProxyContractTests(unittest.TestCase):
    def test_integer_boundaries_reject_yaml_booleans(self) -> None:
        asserts = ASSERTS.read_text(encoding="utf-8")

        for variable in (
            "forward_proxy_lock_timeout",
            "forward_proxy_readiness_timeout",
            "forward_proxy_upstream_port",
        ):
            with self.subTest(variable=variable):
                self.assertIn(f"{variable} is integer", asserts)
                self.assertIn(f"{variable} is not boolean", asserts)

    def test_rollback_uses_the_nested_stat_item_path(self) -> None:
        restore = RESTORE.read_text(encoding="utf-8")
        self.assertEqual(3, restore.count("forward_proxy_restore_entry.0.item.item.0.0"))
        self.assertNotIn("forward_proxy_restore_entry.0.item.0.0", restore)

    def test_readme_example_is_an_explicit_runnable_opt_in(self) -> None:
        readme = README.read_text(encoding="utf-8")
        self.assertIn("forward_proxy_enabled: true", readme)
        self.assertIn("forward_proxy_experimental_runtime_acceptance: true", readme)
        self.assertIn("forward_proxy_allowed_destination_domains:", readme)
        self.assertIn("pull policy is Never", readme)

    def test_tiny_evidence_is_per_contract_and_disposition_bound(self) -> None:
        verify = VERIFY.read_text(encoding="utf-8")
        cleanup = CLEANUP.read_text(encoding="utf-8")
        self.assertIn("forward_proxy_contract_results", verify)
        self.assertIn("{% for contract in forward_proxy_contract_results %}", verify)
        self.assertIn("forward_proxy_failed_contracts", verify)
        self.assertIn("tasks_from: restore_managed_file.yml", verify)
        self.assertIn("Require exact rollback of the transaction candidate", verify)
        self.assertIn("meta/role-coverage.yml", cleanup)
        self.assertIn("forward_proxy_junit_passed", cleanup)
        self.assertIn("== 'supported'", cleanup)
        self.assertNotIn("release_eligible: false", cleanup)


if __name__ == "__main__":
    unittest.main()
