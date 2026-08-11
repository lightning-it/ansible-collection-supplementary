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

        self.assertIs(defaults["nginx_config_vault_allow_local_fallback"], True)
        self.assertIs(defaults["nginx_config_vault_issue_missing"], True)

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
        self.assertIn("not (nginx_config_vault_issue_missing | bool)", task["when"])

    def test_private_key_is_installed_with_mode_0600(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        task = next(item for item in tasks if item.get("name") == "Write TLS private key from Vault")

        self.assertEqual(task["ansible.builtin.copy"]["mode"], "0600")
        self.assertEqual(task["no_log"], "{{ nginx_config_tls_no_log }}")


if __name__ == "__main__":
    unittest.main()
