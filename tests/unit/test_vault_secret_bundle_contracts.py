"""Security contracts for atomic Vault secret bundle generation."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "roles" / "vault_secret_bundle" / "tasks" / "main.yml"


class VaultSecretBundleContractTests(unittest.TestCase):
    def test_transaction_tasks_execute_once_per_play_batch(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))

        self.assertTrue(tasks)
        self.assertEqual(tasks[0]["ansible.builtin.import_tasks"], "assert.yml")
        self.assertEqual(tasks[0]["tags"], "always")
        for task in tasks:
            with self.subTest(task=task.get("name")):
                self.assertIs(task.get("run_once"), True)

    def test_vault_write_uses_observed_kv_version_for_cas(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        write_task = next(task for task in tasks if "community.hashi_vault.vault_kv2_write" in task)
        write_options = write_task["community.hashi_vault.vault_kv2_write"]

        self.assertEqual(
            write_options["cas"],
            "{{ vault_secret_bundle_read.metadata.version | default(0) | int }}",
        )
        self.assertIs(write_task.get("run_once"), True)

    def test_approle_mount_uses_supported_module_parameter(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))

        module_names = (
            "community.hashi_vault.vault_kv2_get",
            "community.hashi_vault.vault_kv2_write",
        )
        for module_name in module_names:
            task = next(task for task in tasks if module_name in task)
            options = task[module_name]
            with self.subTest(module=module_name):
                self.assertEqual(
                    task["vars"]["ansible_python_interpreter"],
                    "{{ ansible_playbook_python }}",
                )
                self.assertEqual(
                    options["mount_point"],
                    "{{ vault_secret_bundle_auth_mount_point }}",
                )
                self.assertNotIn("auth_mount_point", options)


if __name__ == "__main__":
    unittest.main()
