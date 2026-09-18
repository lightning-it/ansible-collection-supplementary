"""Security contracts for the containerized forward proxy role."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSERTS = ROOT / "roles" / "forward_proxy" / "tasks" / "assert.yml"
MAIN = ROOT / "roles" / "forward_proxy" / "tasks" / "main.yml"
READINESS = ROOT / "roles" / "forward_proxy" / "tasks" / "verify_runtime_ready.yml"
RESTORE = ROOT / "roles" / "forward_proxy" / "tasks" / "restore_managed_file.yml"
README = ROOT / "roles" / "forward_proxy" / "README.md"
VERIFY = ROOT / "molecule" / "forward-proxy-tiny" / "verify.yml"
CONVERGE = ROOT / "molecule" / "forward-proxy-tiny" / "converge.yml"
CLEANUP = ROOT / "molecule" / "forward-proxy-tiny" / "cleanup.yml"
RELEASE_ELIGIBILITY = ROOT / "molecule" / "forward-proxy-tiny" / "tasks" / "release_eligibility.yml"


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

    def test_disabled_unowned_invocation_skips_the_lock_boundary(self) -> None:
        main = MAIN.read_text(encoding="utf-8")
        converge = CONVERGE.read_text(encoding="utf-8")

        self.assertIn("Inspect forward proxy state before entering the mutation boundary", main)
        self.assertIn("forward_proxy_transition_scope_internal.required | bool", main)
        self.assertLess(
            main.index("Inspect forward proxy state before entering the mutation boundary"),
            main.index("Inspect the required forward proxy lock parent"),
        )
        self.assertIn("Exercise a disabled unowned invocation without a lock parent", converge)
        self.assertIn("disabled unowned invocation to remain mutation-free", converge)

    def test_readiness_uses_protocol_evidence_and_revalidates_runtime(self) -> None:
        readiness = READINESS.read_text(encoding="utf-8")

        self.assertIn("Require a Squid protocol response", readiness)
        self.assertIn("x-squid-error", readiness)
        self.assertIn("Reinspect the Pod identity after the Squid protocol probe", readiness)
        self.assertIn("Require the same captured runtime after the Squid protocol probe", readiness)

    def test_tiny_evidence_is_per_contract_and_disposition_bound(self) -> None:
        verify = VERIFY.read_text(encoding="utf-8")
        cleanup = CLEANUP.read_text(encoding="utf-8")
        release_eligibility = RELEASE_ELIGIBILITY.read_text(encoding="utf-8")
        self.assertIn("forward_proxy_contract_results", verify)
        self.assertIn("Keep every dynamic boolean inside one native expression", verify)
        self.assertIn("{% for contract in forward_proxy_contract_results %}", verify)
        self.assertIn("forward_proxy_failed_contracts", verify)
        self.assertIn("tasks_from: restore_managed_file.yml", verify)
        self.assertIn("Require exact rollback of the transaction candidate", verify)
        self.assertIn("managed-file-rollback", verify)
        self.assertIn("rollback-fixture-restored", verify)
        self.assertIn("Restore the original policy through the bound atomic path", verify)
        self.assertIn("lit.supplementary.atomic_path", verify)
        self.assertIn("Require a canonical controller-owned rollback parent", verify)
        self.assertLess(
            verify.index("Require exact rollback of the transaction candidate"),
            verify.index("Write final per-contract forward proxy JUnit result"),
        )
        self.assertIn("meta/role-coverage.yml", cleanup)
        self.assertIn("forward_proxy_junit_passed", cleanup)
        self.assertIn("tasks/release_eligibility.yml", cleanup)
        self.assertIn("forward_proxy_release_gate_junit_passed | bool", release_eligibility)
        self.assertIn("== 'supported'", release_eligibility)
        self.assertIn("failed JUnit result against a supported profile", verify)
        self.assertIn("passed JUnit against the authoritative experimental profile", verify)
        self.assertIn("experimental profile to remain ineligible for release", verify)
        self.assertIn("passed JUnit result against a supported profile", verify)
        self.assertIn('forward_proxy_release_gate_junit_passed: "False"', verify)
        self.assertIn('forward_proxy_release_gate_junit_passed: "True"', verify)
        self.assertIn("forward_proxy_junit_passed | bool", cleanup)
        self.assertNotIn("release_eligible: false", cleanup)


if __name__ == "__main__":
    unittest.main()
