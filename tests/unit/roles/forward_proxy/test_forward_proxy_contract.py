from __future__ import annotations

import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
ROLE_ROOT = REPOSITORY_ROOT / "roles" / "forward_proxy"


class ForwardProxyContractTests(unittest.TestCase):
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
        self.assertIn("docker.io/ubuntu/squid:6.6-24.04_beta@sha256:", defaults)
        self.assertIn("forward_proxy_image_pull_policy: Never", defaults)
        self.assertIn("hostNetwork: true", pod)
        self.assertIn("runAsUser: {{ forward_proxy_runtime_uid }}", pod)
        self.assertIn("initContainers:", pod)
        self.assertIn("chmod 1777 /squid-tmp", pod)
        self.assertIn("readOnlyRootFilesystem: true", pod)
        self.assertIn("capabilities:", pod)
        self.assertIn("name: lit.foundational.podman_systemd", tasks)
        self.assertIn("Verify the pinned Squid image was preloaded", tasks)
        self.assertIn("Wait for the local Squid listener", tasks)

    def test_steady_state_cannot_pull_the_proxy_image(self) -> None:
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        pod = (ROLE_ROOT / "templates" / "squid-pod.yml.j2").read_text()
        self.assertIn("forward_proxy_image_pull_policy == 'Never'", assertions)
        self.assertIn("imagePullPolicy: {{ forward_proxy_image_pull_policy }}", pod)

    def test_service_contract_requires_loopback_and_explicit_networks(self) -> None:
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        self.assertIn("'127.0.0.1' in forward_proxy_listen_addresses", assertions)
        self.assertIn("'127.0.0.1/32' in forward_proxy_allowed_clients", assertions)
        self.assertIn("/(?:[1-9]|[12][0-9]|3[0-2])\\Z", assertions)
        self.assertIn("192\\.168\\.", assertions)
        self.assertIn("172\\.(?:1[6-9]|2[0-9]|3[01])\\.", assertions)
        self.assertIn("/(?:[89]|[12][0-9]|3[0-2])\\Z", assertions)
        self.assertIn("/(?:1[6-9]|2[0-9]|3[0-2])\\Z", assertions)
        self.assertIn("25[0-5]", assertions)
        self.assertIn("'.' not in item.split('/')", assertions)
        self.assertIn("\\Z", assertions)

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
        self.assertIn("runtime_managed", tasks)
        self.assertIn("forward_proxy_previous_state_manifest.quadlet_checksum", tasks)
        self.assertIn("forward_proxy_manage_runtime | bool", tasks)
        self.assertIn("Refuse to adopt unowned forward proxy target paths", tasks)
        self.assertIn("not item.stat.exists", tasks)
        self.assertIn("Refuse unsafe forward proxy managed directories", tasks)
        self.assertNotIn("_forward_proxy_managed_paths", tasks)

    def test_check_mode_still_checks_image_without_waiting_for_listener(self) -> None:
        image_task = (ROLE_ROOT / "tasks" / "enabled.yml").read_text()
        apply_tasks = (ROLE_ROOT / "tasks" / "enabled_apply.yml").read_text()
        wait_task = apply_tasks.split("- name: Wait for the local Squid listener", maxsplit=1)[1]
        self.assertIn("check_mode: false", image_task)
        self.assertIn("not ansible_check_mode", wait_task)

    def test_readiness_and_updates_are_transactional(self) -> None:
        apply_tasks = (ROLE_ROOT / "tasks" / "enabled_apply.yml").read_text()
        main_tasks = (ROLE_ROOT / "tasks" / "main.yml").read_text()
        rollback = (ROLE_ROOT / "tasks" / "enabled_existing_rollback.yml").read_text()
        assertions = (ROLE_ROOT / "tasks" / "assert.yml").read_text()
        self.assertIn("Verify the managed Squid Pod is running", apply_tasks)
        self.assertLess(
            apply_tasks.index("Wait for the local Squid listener"),
            apply_tasks.index("Record exact forward proxy file and Quadlet ownership"),
        )
        self.assertIn("Restore previous forward proxy managed files", rollback)
        self.assertIn("Restart the restored previous forward proxy runtime", rollback)
        self.assertIn("Refuse to adopt a foreign Quadlet during runtime activation", main_tasks)
        self.assertNotIn("Remove a partial Quadlet", rollback)
        self.assertIn("regex_replace('^\\\\.', '') | length <= 253", assertions)

    def test_proxy_digest_is_renovated_in_defaults_and_molecule(self) -> None:
        renovate = (REPOSITORY_ROOT / "renovate.json").read_text()
        self.assertIn("roles/.*/defaults/main", renovate)
        self.assertIn("molecule/forward-proxy-tiny/", renovate)

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
