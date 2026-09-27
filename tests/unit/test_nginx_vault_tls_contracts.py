"""Security contracts for NGINX Vault-only TLS custody."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "roles" / "nginx_config" / "defaults" / "main.yml"
ASSERTS = ROOT / "roles" / "nginx_config" / "tasks" / "assert.yml"
TASKS = ROOT / "roles" / "nginx_config" / "tasks" / "main.yml"


class NginxVaultTlsContractTests(unittest.TestCase):
    def test_local_tls_fallback_has_explicit_compatibility_switch(self) -> None:
        defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))

        self.assertIs(defaults["nginx_config_vault_allow_local_fallback"], False)
        self.assertIs(defaults["nginx_config_vault_issue_missing"], True)

    def test_waf_controls_are_rendered_at_server_and_location_boundaries(self) -> None:
        template = (ROOT / "roles" / "nginx_config" / "templates" / "vhost.conf.j2").read_text(encoding="utf-8")

        self.assertIn("nginx_config_waf_server_directives", template)
        self.assertIn("nginx_config_waf_location_directives", template)
        self.assertLess(
            template.index("nginx_config_waf_server_directives"),
            template.index("item.extra_directives"),
        )
        self.assertLess(
            template.index("nginx_config_waf_location_directives"),
            template.index("item.proxy_directives"),
        )
        self.assertEqual(template.count("nginx_config_waf_location_directives"), 3)

    def test_required_forwarded_headers_follow_consumer_directives(self) -> None:
        defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
        template = (ROOT / "roles" / "nginx_config" / "templates" / "vhost.conf.j2").read_text(encoding="utf-8")

        boundary = defaults["nginx_config_proxy_required_directives"]
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr", boundary)
        self.assertIn('proxy_set_header Forwarded ""', boundary)
        self.assertNotIn("$proxy_add_x_forwarded_for", "\n".join(boundary))
        self.assertEqual(template.count("nginx_config_proxy_required_directives"), 4)
        custom_proxy = template.index("item.proxy_directives | default(nginx_config_proxy_default_directives)")
        required_after_custom = template.index("nginx_config_proxy_required_directives", custom_proxy)
        self.assertGreater(required_after_custom, custom_proxy)

    def test_pki_inputs_are_required_only_when_issuance_is_enabled(self) -> None:
        tasks = yaml.safe_load(ASSERTS.read_text(encoding="utf-8"))
        task = next(
            item for item in tasks if item.get("name") == "Ensure Vault PKI issue inputs are present when enabled"
        )

        self.assertIn("not nginx_deploy_skip_config | bool", task["when"])
        self.assertIn("nginx_config_vault_issue_missing | bool", task["when"])
        assertions = task["ansible.builtin.assert"]["that"]
        self.assertTrue(any("nginx_config_vault_pki_path" in item for item in assertions))
        self.assertTrue(any("nginx_config_vault_pki_role" in item for item in assertions))

    def test_host_files_require_explicit_migration_fallback(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        fallback_tasks = [
            item
            for item in tasks
            if item.get("name")
            in {
                "Read local TLS certificate fallback",
                "Read local TLS private key fallback",
                "Set local TLS fallback content",
            }
        ]

        self.assertEqual(len(fallback_tasks), 3)
        for task in fallback_tasks:
            with self.subTest(task=task["name"]):
                self.assertIn(
                    "nginx_config_vault_allow_local_fallback | bool",
                    task["when"],
                )

    def test_stored_vault_identity_is_complete_when_pki_issue_is_disabled(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        task = next(
            item
            for item in tasks
            if item.get("name") == "Require a complete stored Vault TLS identity when issuance is disabled"
        )
        assertions = task["ansible.builtin.assert"]["that"]

        self.assertIn(
            "nginx_config_vault_cert_present | default(false) | bool",
            assertions,
        )
        self.assertIn(
            "nginx_config_vault_cert_identity_match | default(false) | bool",
            assertions,
        )
        self.assertIn(
            "nginx_config_vault_cert_ca_chain_stored | default([], true) | length > 0",
            assertions,
        )
        self.assertIn("not (nginx_config_vault_issue_missing | bool)", task["when"])

    def test_private_key_is_installed_with_mode_0600(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        task = next(item for item in tasks if item.get("name") == "Write TLS private key from Vault")

        self.assertEqual(task["ansible.builtin.copy"]["mode"], "0600")
        self.assertEqual(task["no_log"], "{{ nginx_config_tls_no_log }}")

    def test_nginx_lifecycle_has_one_persistent_controller(self) -> None:
        pod_tasks_path = ROOT / "roles" / "nginx_deploy" / "tasks" / "deploy_pod.yml"
        pod_tasks = yaml.safe_load(pod_tasks_path.read_text(encoding="utf-8"))
        pod_task_map = {task["name"]: task for task in pod_tasks}
        recreate = pod_task_map["Recreate Nginx pod from the desired manifest"]
        self.assertEqual(recreate["vars"]["kubeplay_action"], "recreate")
        self.assertIn("not nginx_deploy_manage_systemd | bool", recreate["when"])
        self.assertNotIn("block", recreate)
        self.assertNotIn("rescue", recreate)

        source = pod_tasks_path.read_text(encoding="utf-8")
        self.assertNotIn("Ignore kubeplay remove failure", source)
        self.assertNotIn("Ignore kubeplay run failure", source)

        systemd_path = ROOT / "roles" / "nginx_deploy" / "tasks" / "systemd.yml"
        systemd_tasks = yaml.safe_load(systemd_path.read_text(encoding="utf-8"))
        systemd_block = systemd_tasks[0]["block"]
        quadlet = next(task for task in systemd_block if task["name"] == "Manage the native Nginx Quadlet service")
        self.assertEqual(
            quadlet["ansible.builtin.include_role"]["name"],
            "lit.foundational.podman_systemd",
        )
        self.assertEqual(
            quadlet["vars"]["podman_systemd_manifest_path"],
            "{{ nginx_deploy_pod_manifest_path }}",
        )
        self.assertEqual(
            quadlet["vars"]["podman_systemd_quadlet_dir"],
            "{{ nginx_deploy_quadlet_dir }}",
        )
        self.assertEqual(
            quadlet["vars"]["podman_systemd_networks"],
            "{{ nginx_deploy_networks }}",
        )
        defaults = yaml.safe_load(
            (ROOT / "roles" / "nginx_deploy" / "defaults" / "main.yml").read_text(encoding="utf-8")
        )
        self.assertEqual(defaults["nginx_deploy_networks"], [])

        stage_index = next(
            index
            for index, task in enumerate(systemd_block)
            if task["name"] == "Stage the native Nginx Quadlet before legacy shutdown"
        )
        legacy_stop_index = next(
            index
            for index, task in enumerate(systemd_block)
            if task["name"] == "Stop and disable the exact legacy Nginx unit before Quadlet takeover"
        )
        self.assertLess(stage_index, legacy_stop_index)


if __name__ == "__main__":
    unittest.main()
