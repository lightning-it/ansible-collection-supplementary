"""Security contracts for the containerized forward proxy role."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSERTS = ROOT / "roles" / "forward_proxy" / "tasks" / "assert.yml"
MAIN = ROOT / "roles" / "forward_proxy" / "tasks" / "main.yml"
TRANSITION = ROOT / "roles" / "forward_proxy" / "tasks" / "transition.yml"
ENSURE_DIRECTORY = ROOT / "roles" / "forward_proxy" / "tasks" / "ensure_directory.yml"
ENABLED = ROOT / "roles" / "forward_proxy" / "tasks" / "enabled.yml"
ENABLED_APPLY = ROOT / "roles" / "forward_proxy" / "tasks" / "enabled_apply.yml"
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
            "forward_proxy_port",
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

    def test_tiny_rollback_decodes_slurped_content_exactly_once_in_role(self) -> None:
        verify = VERIFY.read_text(encoding="utf-8")
        restore = RESTORE.read_text(encoding="utf-8")

        self.assertIn(
            'forward_proxy_restore_entry:\n              - content: "{{ forward_proxy_squid_config.content }}"',
            verify,
        )
        self.assertNotIn(
            "forward_proxy_restore_entry:\n"
            '              - content: "{{ forward_proxy_squid_config.content | b64decode }}"',
            verify,
        )
        self.assertEqual(
            1,
            restore.count("forward_proxy_restore_entry.0.content | b64decode"),
        )

    def test_readme_example_is_an_explicit_runnable_opt_in(self) -> None:
        readme = README.read_text(encoding="utf-8")
        self.assertIn("`lit.foundational` 1.32.0 or newer", readme)
        self.assertIn("`podman_systemd`", readme)
        self.assertIn("forward_proxy_enabled: true", readme)
        self.assertIn("forward_proxy_experimental_runtime_acceptance: true", readme)
        self.assertIn("forward_proxy_allowed_destination_domains:", readme)
        self.assertIn("pull policy is Never", readme)

    def test_disabled_unowned_invocation_skips_the_lock_boundary(self) -> None:
        main = MAIN.read_text(encoding="utf-8")
        converge = CONVERGE.read_text(encoding="utf-8")

        self.assertIn("Inspect forward proxy state before entering the mutation boundary", main)
        self.assertIn("Inspect a concurrent forward proxy transition without creating a lock", main)
        self.assertIn("Reinspect forward proxy state after the concurrent-lock observation", main)
        self.assertIn("forward_proxy_transition_scope_internal.required | bool", main)
        self.assertLess(
            main.index("Inspect forward proxy state before entering the mutation boundary"),
            main.index("Inspect a concurrent forward proxy transition without creating a lock"),
        )
        self.assertLess(
            main.index("Inspect a concurrent forward proxy transition without creating a lock"),
            main.index("Reinspect forward proxy state after the concurrent-lock observation"),
        )
        self.assertLess(
            main.index("Reinspect forward proxy state after the concurrent-lock observation"),
            main.index("Inspect the required forward proxy lock parent"),
        )
        self.assertIn("forward_proxy_invocation_lock.stat.exists", main)
        self.assertIn("forward_proxy_invocation_state_marker_after_lock.stat.exists", main)
        self.assertIn("forward_proxy_transition_initialized_internal: false", main)
        self.assertIn("Exercise a disabled unowned invocation without a lock parent", converge)
        self.assertIn("disabled unowned invocation to remain mutation-free", converge)

    def test_check_mode_reports_each_planned_directory_creation(self) -> None:
        ensure_directory = ENSURE_DIRECTORY.read_text(encoding="utf-8")

        planned = ensure_directory.index("Carry the planned forward proxy directory through check mode")
        following = ensure_directory.index("Reinspect the trusted proxy directory before privileged writes")
        self.assertIn("changed_when: true", ensure_directory[planned:following])

    def test_disabled_runtime_fails_closed_without_owned_quadlet_evidence(self) -> None:
        transition = TRANSITION.read_text(encoding="utf-8")

        missing = transition.index("Fail closed when runtime-managed Quadlet evidence is missing")
        capture = transition.index("Capture the existing runtime identity before any runtime mutation")
        revalidate = transition.index("Revalidate the existing runtime at the disabled-state removal boundary")
        remove = transition.index("Remove a previously managed forward proxy runtime when disabled")
        absent = transition.index("Prove the disabled runtime is absent before deleting owned state")
        self.assertLess(missing, capture)
        self.assertLess(capture, revalidate)
        self.assertLess(revalidate, remove)
        self.assertLess(remove, absent)
        self.assertIn("forward_proxy_previous_quadlet_stat.stat.exists", transition[missing:capture])
        self.assertNotIn(
            "or forward_proxy_previous_quadlet_stat.stat.exists",
            transition[capture:revalidate],
        )

    def test_check_mode_reports_the_owned_disable_transition(self) -> None:
        transition = TRANSITION.read_text(encoding="utf-8")

        planned = transition.index("Report the planned owned forward proxy disable transition in check mode")
        capture = transition.index("Capture the existing runtime identity before any runtime mutation")
        section = transition[planned:capture]
        self.assertIn("changed_when: true", section)
        self.assertIn("ansible_check_mode", section)
        self.assertIn("not forward_proxy_enabled | bool", section)
        self.assertIn("forward_proxy_state_marker.stat.exists", section)

    def test_readiness_uses_protocol_evidence_and_revalidates_runtime(self) -> None:
        readiness = READINESS.read_text(encoding="utf-8")

        self.assertIn("Require a Squid protocol response", readiness)
        self.assertIn("Require the Ansible-discovered target Python interpreter", readiness)
        self.assertIn('"{{ ansible_facts.discovered_interpreter_python }}"', readiness)
        self.assertNotIn("- /usr/bin/python3", readiness)
        self.assertIn("x-squid-error", readiness)
        self.assertIn('while b"\\r\\n\\r\\n" not in response', readiness)
        self.assertIn('has_complete_headers = b"\\r\\n\\r\\n" in response', readiness)
        self.assertIn("if has_complete_headers and response.startswith", readiness)
        self.assertIn("len(response) > 65536", readiness)
        self.assertIn("Reinspect the Pod identity after the Squid protocol probe", readiness)
        self.assertIn("Require the same captured runtime after the Squid protocol probe", readiness)

    def test_runtime_image_preflight_precedes_every_enabled_state_mutation(self) -> None:
        transition = TRANSITION.read_text(encoding="utf-8")
        enabled = ENABLED.read_text(encoding="utf-8")
        enabled_apply = ENABLED_APPLY.read_text(encoding="utf-8")

        preflight = "Verify the pinned Squid image before any enabled-state mutation"
        first_directory_mutation = "Create and revalidate every trusted forward proxy parent boundary"
        enabled_transition = "Apply the enabled forward proxy state"

        self.assertIn(preflight, transition)
        self.assertIn("forward_proxy_enabled | bool", transition)
        self.assertIn("forward_proxy_manage_runtime | bool", transition)
        self.assertIn(first_directory_mutation, transition)
        self.assertIn(enabled_transition, transition)
        self.assertLess(transition.index(preflight), transition.index(first_directory_mutation))
        self.assertLess(transition.index(preflight), transition.index(enabled_transition))
        self.assertNotIn("Verify the pinned Squid image was preloaded", enabled)
        self.assertNotIn("forward_proxy_transition_initialized_internal: true", transition)
        self.assertEqual(2, enabled_apply.count("forward_proxy_transition_initialized_internal: true"))
        self.assertLess(
            enabled_apply.index("Refuse a foreign same-named runtime before any managed-file write"),
            enabled_apply.index("Enter the rollback boundary before writing the Squid policy"),
        )
        self.assertLess(
            enabled_apply.index("Enter the rollback boundary before writing the Squid policy"),
            enabled_apply.index("Render the Squid policy with an atomic no-follow write"),
        )
        self.assertLess(
            enabled_apply.index("Enter the rollback boundary before writing the Squid policy"),
            enabled_apply.index("Render the digest-pinned Squid Pod manifest with an atomic no-follow write"),
        )
        self.assertLess(
            enabled_apply.index("Enter the rollback boundary before writing the Squid policy"),
            enabled_apply.index("Manage the persistent Squid container service"),
        )
        self.assertLess(
            enabled_apply.index("Enter the rollback boundary before removing the previous runtime"),
            enabled_apply.index("Remove the previous runtime when switching to render-only mode"),
        )
        self.assertIn("No rollback was attempted", enabled)
        self.assertEqual(
            3,
            enabled.count("forward_proxy_transition_initialized_internal | default(false) | bool"),
        )

    def test_tiny_evidence_is_per_contract_and_disposition_bound(self) -> None:
        verify = VERIFY.read_text(encoding="utf-8")
        cleanup = CLEANUP.read_text(encoding="utf-8")
        release_eligibility = RELEASE_ELIGIBILITY.read_text(encoding="utf-8")
        self.assertIn("forward_proxy_contract_results", verify)
        self.assertIn("Write provisional fail-closed forward proxy JUnit result", verify)
        self.assertIn("forward proxy Tiny verification did not complete", verify)
        self.assertIn('errors="1"', verify)
        self.assertIn('<error message="forward proxy Tiny verification did not complete"/>', verify)
        self.assertLess(
            verify.index("Write provisional fail-closed forward proxy JUnit result"),
            verify.index("Read rendered Squid policy"),
        )
        self.assertLess(
            verify.index("Read rendered Squid policy"),
            verify.index("Write final per-contract forward proxy JUnit result"),
        )
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
