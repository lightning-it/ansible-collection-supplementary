from __future__ import annotations

import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ROLE_ROOT = REPOSITORY_ROOT / "roles" / "forward_proxy"


class ForwardProxyContractTests(unittest.TestCase):
    def test_complete_state_transition_has_bounded_per_host_mutual_exclusion(
        self,
    ) -> None:
        wrapper = (ROLE_ROOT / "tasks" / "main.yml").read_text()
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        defaults = (ROLE_ROOT / "defaults" / "main.yml").read_text()
        self.assertIn("Acquire the bounded per-host forward proxy transition lock", wrapper)
        self.assertIn("forward_proxy_lock_acquisition.rc == 0", wrapper)
        self.assertIn("include_tasks: transition.yml", wrapper)
        self.assertIn("Release the per-host forward proxy transition lock", wrapper)
        self.assertIn("forward_proxy_lock_timeout: 30", defaults)
        self.assertIn("forward_proxy_lock_timeout <= 300", assertions)
        self.assertIn("[A-Za-z0-9][A-Za-z0-9_.-]*", assertions)

    def test_role_contains_only_distribution_neutral_service_state(self) -> None:
        defaults = (ROLE_ROOT / "defaults" / "main.yml").read_text()
        tasks = "".join(path.read_text() for path in sorted((ROLE_ROOT / "tasks").glob("*.yml")))
        templates = {path.name for path in (ROLE_ROOT / "templates").iterdir()}
        self.assertEqual(templates, {"squid-pod.yml.j2", "squid.conf.j2"})
        self.assertNotIn("apt", defaults.lower())
        self.assertNotIn("dnf", defaults.lower())
        self.assertNotIn("ansible.builtin.apt", tasks)
        self.assertNotIn("ansible.builtin.dnf", tasks)
        self.assertNotIn("squid.service", tasks)

    def test_runtime_is_a_digest_pinned_non_root_container(self) -> None:
        defaults = (ROLE_ROOT / "defaults" / "main.yml").read_text()
        pod = (ROLE_ROOT / "templates" / "squid-pod.yml.j2").read_text()
        tasks = "".join(path.read_text() for path in sorted((ROLE_ROOT / "tasks").glob("enabled*.yml")))
        tasks += (ROLE_ROOT / "tasks" / "verify_runtime_ready.yml").read_text()
        self.assertRegex(
            defaults,
            r"docker\.io/ubuntu/squid:[A-Za-z0-9][A-Za-z0-9._-]*"
            r"@sha256:[a-f0-9]{64}",
        )
        self.assertIn("forward_proxy_image_pull_policy: Never", defaults)
        self.assertIn("hostNetwork: true", pod)
        self.assertIn("host: 127.0.0.1", pod)
        self.assertIn("runAsUser: {{ forward_proxy_runtime_uid }}", pod)
        self.assertIn("initContainers:", pod)
        self.assertIn("chmod 1777 /squid-tmp", pod)
        self.assertIn("readOnlyRootFilesystem: true", pod)
        self.assertIn("capabilities:", pod)
        self.assertIn("name: lit.foundational.podman_systemd", tasks)
        self.assertIn("Verify the pinned Squid image was preloaded", tasks)
        self.assertIn("Wait for the local Squid listener", tasks)
        self.assertIn("- /usr/bin/podman", tasks)
        self.assertNotIn("forward_proxy_podman_binary", defaults + tasks)

    def test_readme_keeps_the_mandatory_role_section_order(self) -> None:
        readme = (ROLE_ROOT / "README.md").read_text()
        ordered_headers = [
            "## Requirements",
            "## Variables",
            "## Dependencies",
            "## Example Playbook",
            "## License",
            "## Author",
        ]
        positions = [readme.index(header) for header in ordered_headers]
        self.assertEqual(positions, sorted(positions))
        self.assertGreater(readme.index("## Verification status"), readme.index("## Author"))

    def test_steady_state_cannot_pull_the_proxy_image(self) -> None:
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        pod = (ROLE_ROOT / "templates" / "squid-pod.yml.j2").read_text()
        self.assertIn("forward_proxy_image_pull_policy == 'Never'", assertions)
        self.assertIn("imagePullPolicy: {{ forward_proxy_image_pull_policy }}", pod)
        self.assertIn("[A-Za-z0-9._-]{0,127}", assertions)
        self.assertNotIn("squid:6\\.6-24\\.04_beta", assertions)

    def test_service_contract_requires_loopback_and_explicit_networks(self) -> None:
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        policy = (ROLE_ROOT / "templates" / "squid.conf.j2").read_text()
        self.assertIn("'127.0.0.1' in forward_proxy_listen_addresses", assertions)
        self.assertIn("'127.0.0.1/32' in forward_proxy_allowed_clients", assertions)
        self.assertIn("/(?:[1-9]|[12][0-9]|3[0-2])\\Z", assertions)
        self.assertIn("192\\.168\\.", assertions)
        self.assertIn("172\\.(?:1[6-9]|2[0-9]|3[01])\\.", assertions)
        self.assertIn("/(?:[89]|[12][0-9]|3[0-2])\\Z", assertions)
        self.assertIn("/(?:1[6-9]|2[0-9]|3[0-2])\\Z", assertions)
        self.assertIn("25[0-5]", assertions)
        self.assertIn("[1-9][0-9]?|0", assertions)
        self.assertNotIn("[1-9]?[0-9]", assertions)
        self.assertIn("2 ** (32 - (item.split('/')[1] | int))", assertions)
        self.assertIn("'.' not in item.split('/')", assertions)
        self.assertIn("\\Z", assertions)
        self.assertIn("acl lit_allowed_domains dstdomain -n", policy)
        self.assertNotIn("acl lit_allowed_domains dstdomain {{", policy)

        verify = (REPOSITORY_ROOT / "molecule" / "forward-proxy-tiny" / "verify.yml").read_text()
        rejection = (REPOSITORY_ROOT / "molecule" / "forward-proxy-tiny" / "tasks" / "reject-client.yml").read_text()
        self.assertIn("Prove unsafe client networks are rejected before rendering", verify)
        self.assertIn("forward_proxy_negative_results", verify)
        self.assertIn("forward_proxy.negative_policy", verify)
        self.assertIn("Preserve unsafe client rejection result", rejection)

    def test_non_root_rendering_is_contained_and_numeric_owners_are_canonical(self) -> None:
        defaults = (ROLE_ROOT / "defaults" / "main.yml").read_text()
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        main = (ROLE_ROOT / "tasks" / "transition.yml").read_text()
        directory_guard = (ROLE_ROOT / "tasks" / "ensure_directory.yml").read_text()
        argument_spec = (ROLE_ROOT / "meta" / "argument_specs.yml").read_text()
        self.assertIn("forward_proxy_render_root: /tmp", defaults)
        self.assertIn("forward_proxy_render_root", argument_spec)
        self.assertIn("Contain non-root render-only output beneath its explicit root", assertions)
        self.assertIn("item.startswith(forward_proxy_render_root.rstrip('/') ~ '/')", assertions)
        self.assertIn("|0|[1-9][0-9]{0,9}", assertions)
        self.assertNotIn("|[0-9]{1,10}", assertions)
        self.assertIn("forward_proxy_trusted_parent_paths", defaults)
        self.assertIn("forward_proxy_trusted_parent_paths", argument_spec)
        self.assertIn("Create and revalidate every trusted forward proxy parent boundary", main)
        self.assertIn("forward_proxy_enabled | bool or forward_proxy_state_marker.stat.exists", main)
        self.assertIn("forward_proxy_directory_path == forward_proxy_render_root", main)
        self.assertIn("forward_proxy_directory_path.startswith(forward_proxy_render_root", main)
        self.assertIn("/usr/bin/realpath", directory_guard)
        self.assertIn("forward_proxy_directory_realpath.stdout == forward_proxy_directory_path", directory_guard)
        self.assertIn("forward_proxy_planned_directories_internal", directory_guard)
        self.assertIn("Initialize the check-mode forward proxy directory plan", main)
        self.assertIn("Require parent-before-child trusted directory ordering", assertions)
        self.assertIn("forward_proxy_trusted_parent_paths[:ansible_loop.index0]", assertions)

    def test_upstream_hostname_is_validated_label_by_label(self) -> None:
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        self.assertIn("forward_proxy_upstream_host | length <= 253", assertions)
        self.assertIn("forward_proxy_upstream_host.split('.')", assertions)
        self.assertIn("[A-Za-z0-9-]{0,61}", assertions)

    def test_disabled_state_cleans_only_role_owned_state(self) -> None:
        tasks = "".join(path.read_text() for path in sorted((ROLE_ROOT / "tasks").glob("*.yml")))
        variables = (ROLE_ROOT / "vars" / "main.yml").read_text()
        self.assertIn("Inspect the forward proxy managed-state marker", tasks)
        self.assertIn("forward_proxy_previous_state_manifest.managed_paths", tasks)
        self.assertIn("lit.supplementary.forward_proxy.managed-state/v4", tasks)
        self.assertNotIn("managed-state/v1", variables)
        self.assertIn("checksum_algorithm: sha256", tasks)
        self.assertIn("item.stat.isreg", tasks)
        self.assertIn("item.stat.islnk", tasks)
        self.assertIn("item.stat.mode", tasks)
        self.assertIn("item.stat.pw_name", tasks)
        self.assertIn("item.stat.gr_name", tasks)
        self.assertIn("first-run rollback", tasks)
        self.assertIn("enabled_first_run_rollback.yml", tasks)
        self.assertIn("enabled_existing_rollback.yml", tasks)
        self.assertIn("verify_runtime_absent.yml", tasks)
        self.assertIn("runtime_managed", tasks)
        self.assertIn("forward_proxy_previous_state_manifest.quadlet_checksum", tasks)
        self.assertIn("forward_proxy_manage_runtime | bool", tasks)
        self.assertIn("Refuse to adopt unowned forward proxy target paths", tasks)
        self.assertIn("not item.stat.exists", tasks)
        self.assertIn("Refuse an absent anchor or unsafe existing proxy directory", tasks)
        self.assertNotIn("_forward_proxy_managed_paths", tasks)
        rollback = (ROLE_ROOT / "tasks" / "enabled_first_run_rollback.yml").read_text()
        self.assertIn("Require exact transaction checksum and ownership before rollback", rollback)
        self.assertIn("forward_proxy_state_marker_payload_internal | hash('sha256')", rollback)
        self.assertIn("forward_proxy_state_marker_payload_internal is defined", rollback)
        self.assertIn("item.stat.isreg", rollback)
        self.assertIn("item.stat.islnk", rollback)
        self.assertIn("item.stat.checksum", rollback)
        self.assertIn("forward_proxy_managed_asset_stats.results", rollback)
        self.assertIn("forward_proxy_directory_creation_allowed: false", rollback)

    def test_dangling_symlinks_cannot_cross_first_run_boundaries(self) -> None:
        main = (ROLE_ROOT / "tasks" / "transition.yml").read_text()
        directory_guard = (ROLE_ROOT / "tasks" / "ensure_directory.yml").read_text()
        rollback = (ROLE_ROOT / "tasks" / "enabled_first_run_rollback.yml").read_text()
        self.assertIn("+ [forward_proxy_state_marker_path]", main)
        self.assertIn("not item.stat.islnk | default(false)", main)
        self.assertGreaterEqual(
            directory_guard.count("not forward_proxy_directory_before.stat.islnk | default(false)"),
            3,
        )
        self.assertGreaterEqual(rollback.count("not item.stat.islnk | default(false)"), 2)

    def test_first_run_rollback_matches_the_selected_runtime_mode(self) -> None:
        rollback = (ROLE_ROOT / "tasks" / "enabled_first_run_rollback.yml").read_text()
        self.assertIn("forward_proxy_managed_directories_internal", rollback)
        self.assertIn("forward_proxy_manage_runtime | bool", rollback)
        self.assertEqual(
            rollback.count("if forward_proxy_manage_runtime | bool else []"),
            2,
        )

    def test_first_runtime_activation_never_adopts_or_removes_a_foreign_identity(
        self,
    ) -> None:
        apply_tasks = (ROLE_ROOT / "tasks" / "enabled_apply.yml").read_text()
        rollback = (ROLE_ROOT / "tasks" / "enabled_first_run_rollback.yml").read_text()
        self.assertIn(
            "Inspect a same-named systemd unit before first runtime activation",
            apply_tasks,
        )
        self.assertIn("list-unit-files", apply_tasks)
        self.assertIn(
            "forward_proxy_first_run_systemd_unit_files.stdout_lines | length == 0",
            apply_tasks,
        )
        self.assertIn("forward_proxy_first_run_pod_state.rc == 1", apply_tasks)
        self.assertIn(
            "Authorize rollback only for the proven-absent new runtime identity",
            apply_tasks,
        )
        authorization = "forward_proxy_new_runtime_removal_authorization_internal | default({})"
        self.assertGreaterEqual(rollback.count(authorization), 2)
        existing_rollback = (ROLE_ROOT / "tasks" / "enabled_existing_rollback.yml").read_text()
        self.assertGreaterEqual(existing_rollback.count(authorization), 2)
        wrapper = (ROLE_ROOT / "tasks" / "main.yml").read_text()
        self.assertIn("Reset runtime rollback authorization", wrapper)
        self.assertIn("authorized: false", wrapper)
        self.assertIn("state_marker_path:", apply_tasks)
        self.assertIn("quadlet_path:", apply_tasks)
        self.assertIn(
            "not forward_proxy_previous_state_manifest.runtime_managed",
            apply_tasks,
        )

    def test_check_mode_never_materializes_the_runtime_ownership_payload(self) -> None:
        apply_tasks = (ROLE_ROOT / "tasks" / "enabled_apply.yml").read_text()
        marker_task = apply_tasks.split(
            "- name: Prepare the exact forward proxy ownership marker payload",
            maxsplit=1,
        )[1].split("- name: Record exact forward proxy file", maxsplit=1)[0]
        self.assertIn("when: not ansible_check_mode", marker_task)

    def test_render_only_does_not_probe_or_create_runtime_state(self) -> None:
        main = (ROLE_ROOT / "tasks" / "transition.yml").read_text()
        apply_tasks = (ROLE_ROOT / "tasks" / "enabled_apply.yml").read_text()
        verify = (REPOSITORY_ROOT / "molecule" / "forward-proxy-tiny" / "verify.yml").read_text()
        self.assertIn(
            "([forward_proxy_quadlet_path] if forward_proxy_manage_runtime | bool else [])",
            main,
        )
        self.assertIn("forward_proxy_manage_runtime: false", verify)
        self.assertIn("forward_proxy_config_path:", verify)
        self.assertIn("forward_proxy_pod_manifest_path:", verify)
        self.assertIn("forward_proxy_state_marker_path:", verify)
        self.assertNotIn("Create forward proxy managed directories", apply_tasks)

    def test_runtime_removal_revalidates_the_quadlet_parent_chain(self) -> None:
        main = (ROLE_ROOT / "tasks" / "transition.yml").read_text()
        self.assertIn("Require the declared Quadlet parent chain before runtime removal", main)
        self.assertIn("Revalidate the Quadlet parent chain before runtime removal", main)
        self.assertIn("forward_proxy_directory_creation_allowed: false", main)
        self.assertIn("forward_proxy_previous_state_manifest.runtime_managed | bool", main)
        self.assertIn("not forward_proxy_manage_runtime | bool", main)

    def test_every_runtime_removal_has_an_explicit_absence_postcondition(self) -> None:
        main = (ROLE_ROOT / "tasks" / "transition.yml").read_text()
        apply_tasks = (ROLE_ROOT / "tasks" / "enabled_apply.yml").read_text()
        first_rollback = (ROLE_ROOT / "tasks" / "enabled_first_run_rollback.yml").read_text()
        existing_rollback = (ROLE_ROOT / "tasks" / "enabled_existing_rollback.yml").read_text()
        absence = (ROLE_ROOT / "tasks" / "verify_runtime_absent.yml").read_text()
        for task_text in (main, apply_tasks, first_rollback, existing_rollback):
            self.assertIn("verify_runtime_absent.yml", task_text)
        self.assertIn("/usr/bin/systemctl", absence)
        self.assertIn("--property=LoadState", absence)
        self.assertIn("list-unit-files", absence)
        self.assertIn("stdout | trim) == 'not-found'", absence)
        self.assertIn("stdout_lines | length == 0", absence)
        self.assertIn("/usr/bin/podman", absence)
        self.assertIn("pod", absence)
        self.assertIn("exists", absence)
        self.assertIn("forward_proxy_runtime_pod_absence.rc != 1", absence)
        self.assertIn("Inspect the removed forward proxy Quadlet", absence)
        self.assertIn("not forward_proxy_runtime_quadlet_absence.stat.exists", absence)
        self.assertIn("not forward_proxy_runtime_quadlet_absence.stat.islnk", absence)

    def test_managed_files_cannot_overlap_directories_or_each_other(self) -> None:
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        self.assertIn("select('match', '^' ~ (item | regex_escape) ~ '/')", assertions)
        self.assertIn("item != forward_proxy_quadlet_dir", assertions)
        self.assertIn("not forward_proxy_quadlet_dir.startswith", assertions)
        self.assertIn("not item.startswith(forward_proxy_quadlet_dir.rstrip('/')", assertions)

    def test_lock_cleanup_cannot_remove_managed_state(self) -> None:
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        self.assertIn(
            "Keep the transition lock outside every managed proxy boundary",
            assertions,
        )
        self.assertIn(
            "not item.startswith(forward_proxy_lock_path.rstrip('/') ~ '/')",
            assertions,
        )
        self.assertIn(
            "not forward_proxy_lock_path.startswith(item.rstrip('/') ~ '/')",
            assertions,
        )

    def test_render_writes_revalidate_parents_and_never_follow_links(self) -> None:
        apply_tasks = (ROLE_ROOT / "tasks" / "enabled_apply.yml").read_text()
        self.assertGreaterEqual(
            apply_tasks.count("forward_proxy_directory_creation_allowed: false"),
            3,
        )
        self.assertGreaterEqual(apply_tasks.count("follow: false"), 2)
        self.assertGreaterEqual(apply_tasks.count("unsafe_writes: false"), 3)
        self.assertIn("lookup('ansible.builtin.template', 'squid.conf.j2')", apply_tasks)
        self.assertIn("lookup('ansible.builtin.template', 'squid-pod.yml.j2')", apply_tasks)
        self.assertIn("Revalidate the state marker parent chain", apply_tasks)

    def test_existing_rollback_revalidates_every_write_boundary(self) -> None:
        rollback = (ROLE_ROOT / "tasks" / "enabled_existing_rollback.yml").read_text()
        self.assertIn(
            "Revalidate trusted proxy directories before existing-state rollback",
            rollback,
        )
        self.assertIn("Reinspect existing-state rollback destinations", rollback)
        self.assertIn("Require safe existing-state rollback destinations", rollback)
        self.assertGreaterEqual(rollback.count("follow: false"), 4)
        self.assertGreaterEqual(rollback.count("unsafe_writes: false"), 3)
        restored_runtime = rollback.split(
            "- name: Restart the restored previous forward proxy runtime",
            maxsplit=1,
        )[1].split(
            "- name: Prove the restored previous forward proxy runtime is ready",
            maxsplit=1,
        )[0]
        self.assertIn("not ansible_check_mode", restored_runtime)

    def test_trusted_parent_chains_are_complete_and_canonical(self) -> None:
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        directory_guard = (ROLE_ROOT / "tasks" / "ensure_directory.yml").read_text()
        wrapper = (ROLE_ROOT / "tasks" / "main.yml").read_text()
        self.assertIn("item | dirname == '/'", assertions)
        self.assertIn("Bind internal proxy paths to their canonical derivation", assertions)
        self.assertIn("Resolve the existing immediate parent canonically", directory_guard)
        self.assertIn("forward_proxy_directory_parent.stat.mode", directory_guard)
        self.assertIn("forward_proxy_directory_parent_realpath.stdout", directory_guard)
        self.assertIn("Inspect the required forward proxy lock parent", wrapper)
        self.assertIn("not ansible_check_mode", wrapper)

    def test_disable_runtime_removal_is_skipped_in_check_mode(self) -> None:
        transition = (ROLE_ROOT / "tasks" / "transition.yml").read_text()
        removal = transition.split(
            "- name: Remove a previously managed forward proxy runtime when disabled",
            maxsplit=1,
        )[1].split(
            "- name: Prove the disabled runtime is absent before deleting owned state",
            maxsplit=1,
        )[0]
        self.assertIn("not ansible_check_mode", removal)

    def test_readme_labels_render_only_example_without_claiming_activation(self) -> None:
        readme = (ROLE_ROOT / "README.md").read_text()
        self.assertIn("Render the LIT forward proxy service definition", readme)
        self.assertIn("It does not create a Quadlet or start", readme)
        self.assertIn("forward_proxy_experimental_runtime_acceptance: true", readme)

    def test_check_mode_still_checks_image_without_waiting_for_listener(self) -> None:
        image_task = (ROLE_ROOT / "tasks" / "enabled.yml").read_text()
        apply_tasks = (ROLE_ROOT / "tasks" / "enabled_apply.yml").read_text()
        self.assertIn("check_mode: false", image_task)
        self.assertIn("verify_runtime_ready.yml", apply_tasks)
        self.assertIn("Prepare the exact forward proxy ownership marker payload", apply_tasks)
        self.assertIn('content: "{{ forward_proxy_state_marker_payload_internal }}"', apply_tasks)
        self.assertIn("not ansible_check_mode", apply_tasks)

    def test_readiness_and_updates_are_transactional(self) -> None:
        apply_tasks = (ROLE_ROOT / "tasks" / "enabled_apply.yml").read_text()
        readiness = (ROLE_ROOT / "tasks" / "verify_runtime_ready.yml").read_text()
        main_tasks = (ROLE_ROOT / "tasks" / "transition.yml").read_text()
        rollback = (ROLE_ROOT / "tasks" / "enabled_existing_rollback.yml").read_text()
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        self.assertIn("verify_runtime_ready.yml", apply_tasks)
        self.assertIn("Verify the managed Squid Pod is running", readiness)
        self.assertLess(
            apply_tasks.index("Prove the managed forward proxy runtime is ready"),
            apply_tasks.index("Record exact forward proxy file and Quadlet ownership"),
        )
        self.assertIn("Restore previous forward proxy managed files", rollback)
        self.assertIn("Restart the restored previous forward proxy runtime", rollback)
        self.assertIn("Prove the restored previous forward proxy runtime is ready", rollback)
        self.assertIn("verify_runtime_ready.yml", rollback)
        self.assertIn("Wait for the local Squid listener", readiness)
        self.assertIn("Refuse to adopt a foreign Quadlet during runtime activation", main_tasks)
        self.assertNotIn("Remove a partial Quadlet", rollback)
        self.assertIn("regex_replace('^\\.', '') | length <= 253", assertions)

    def test_proxy_digest_is_renovated_in_defaults_and_molecule(self) -> None:
        renovate = (REPOSITORY_ROOT / "renovate.json").read_text()
        self.assertIn("roles/.*/defaults/main", renovate)
        self.assertIn("molecule/forward-proxy-tiny/", renovate)

    def test_tiny_scenario_produces_junit_and_redacted_evidence(self) -> None:
        registry = (REPOSITORY_ROOT / "meta" / "role-coverage.yml").read_text()
        molecule = (REPOSITORY_ROOT / "molecule" / "forward-proxy-tiny" / "molecule.yml").read_text()
        verify = (REPOSITORY_ROOT / "molecule" / "forward-proxy-tiny" / "verify.yml").read_text()
        cleanup = (REPOSITORY_ROOT / "molecule" / "forward-proxy-tiny" / "cleanup.yml").read_text()
        scenario = registry.split("  forward-proxy-tiny:", maxsplit=1)[1].split("\n  gitlab-runner-basic:", maxsplit=1)[
            0
        ]
        self.assertIn("junit: true", scenario)
        self.assertIn("allure: false", scenario)
        self.assertIn("evidence: true", scenario)
        self.assertIn('state: "experimental"', scenario)
        self.assertIn('implementation: "partial"', scenario)
        self.assertIn("local pre-merge evidence only", scenario)
        self.assertIn("cleanup: cleanup.yml", molecule)
        self.assertIn("forward-proxy-tiny.xml", verify)
        self.assertIn("Evaluate each service and upstream contract independently", verify)
        self.assertIn("Exercise cleanup without losing its failure evidence", verify)
        self.assertIn("forward_proxy_cleanup_execution_result", verify)
        self.assertIn("follow: false", verify)
        self.assertIn("not item.stat.islnk", verify)
        self.assertIn("Fail after preserving every forward proxy assertion result", verify)
        self.assertIn("evidence/forward-proxy-tiny.yml", cleanup)
        self.assertIn("forward_proxy_junit_passed", cleanup)
        self.assertIn("scripts.quality_evidence import parse_junit", cleanup)
        self.assertIn("junit_status:", cleanup)
        self.assertIn("release_eligible: false", cleanup)
        self.assertIn("redacted: true", cleanup)

    def test_live_runtime_remains_explicitly_blocked_until_acceptance(self) -> None:
        defaults = (ROLE_ROOT / "defaults" / "main.yml").read_text()
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        argument_spec = (ROLE_ROOT / "meta" / "argument_specs.yml").read_text()
        readme = (ROLE_ROOT / "README.md").read_text()
        self.assertIn("forward_proxy_experimental_runtime_acceptance: false", defaults)
        self.assertIn("forward_proxy_experimental_runtime_acceptance is boolean", assertions)
        self.assertIn("or forward_proxy_experimental_runtime_acceptance", assertions)
        self.assertIn("forward_proxy_experimental_runtime_acceptance", argument_spec)
        self.assertIn("controlled Wunderbox runtime acceptance", readme)

    def test_squid_is_readonly_runtime_compatible(self) -> None:
        template = (ROLE_ROOT / "templates" / "squid.conf.j2").read_text()
        self.assertIn("pid_filename /tmp/squid.pid", template)
        self.assertIn("cache_dir null /tmp", template)
        self.assertIn("access_log stdio:/dev/stdout", template)
        self.assertIn("cache_log /dev/stderr", template)
        self.assertNotIn("/var/log/squid", template)

    def test_quadlet_identity_and_el_volume_contract_are_exact(self) -> None:
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        pod = (ROLE_ROOT / "templates" / "squid-pod.yml.j2").read_text()
        self.assertIn("forward_proxy_quadlet_dir ~ '/' ~ forward_proxy_unit_name", assertions)
        self.assertIn("selinuxRelabel: true", pod)
        self.assertIn("emptyDir: {}", pod)


if __name__ == "__main__":
    unittest.main()
