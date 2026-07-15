"""Regression tests for Vault backup/restore runtime command injection."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKUP_ROLE = ROOT / "roles" / "vault_backup_restore"
VALIDATE_ROLE = ROOT / "roles" / "vault_validate"
SCENARIO_VERIFY = ROOT / "molecule" / "vault-backup-restore-basic" / "verify.yml"
EVIDENCE_COLLECTOR = ROOT / "molecule" / "shared" / "vault" / "collect-test-application-evidence.yml"


class VaultBackupRestoreContractTests(unittest.TestCase):
    def test_runtime_commands_use_the_injected_podman_executable(self) -> None:
        for relative_path in (
            "tasks/inspect_runtime.yml",
            "tasks/start_runtime.yml",
            "tasks/stop_runtime.yml",
        ):
            with self.subTest(path=relative_path):
                source = (BACKUP_ROLE / relative_path).read_text(encoding="utf-8")
                self.assertIn('"{{ vault_backup_restore_podman_executable }}"', source)
                self.assertNotRegex(source, r"(?m)^\s+- podman\s*$")

        validation = (VALIDATE_ROLE / "tasks" / "main.yml").read_text(encoding="utf-8")
        self.assertEqual(2, validation.count('"{{ vault_validate_podman_executable }}"'))
        self.assertNotIn('ansible.builtin.command: "podman inspect', validation)

    def test_scenario_binds_the_fake_and_retains_stop_start_assertions(self) -> None:
        verify = SCENARIO_VERIFY.read_text(encoding="utf-8")
        self.assertIn(
            "vault_backup_restore_podman_executable: >-\n      {{ vault_backup_restore_molecule_root }}/bin/podman",
            verify,
        )
        self.assertIn("'pod stop vault' in", verify)
        self.assertIn("'pod start vault' in", verify)
        self.assertIn("vault_backup_restore_molecule_runtime_state.content", verify)
        self.assertIn("vault_backup_restore_molecule_backup_failure_observed", verify)
        self.assertIn("vault_backup_restore_molecule_rollback_observed", verify)

    def test_restore_validation_reuses_the_same_runtime_executable(self) -> None:
        restore = (BACKUP_ROLE / "tasks" / "restore.yml").read_text(encoding="utf-8")
        self.assertIn(
            'vault_validate_podman_executable: "{{ vault_backup_restore_podman_executable }}"',
            restore,
        )

    def test_local_evidence_fallback_is_collection_rooted(self) -> None:
        collector = EVIDENCE_COLLECTOR.read_text(encoding="utf-8")
        self.assertIn(
            "lookup('ansible.builtin.env', 'MOLECULE_PROJECT_DIRECTORY') | trim",
            collector,
        )
        self.assertIn(
            "lookup('ansible.builtin.env', 'MOLECULE_TEST_ARTIFACTS') | trim",
            collector,
        )
        self.assertIn(
            "vault_test_application_project_directory ~ '/artifacts/evidence'",
            collector,
        )
        self.assertNotIn("default('artifacts/evidence', true)", collector)
        self.assertIn(
            "vault_test_application_artifact_override | trim | length > 0",
            collector,
        )
        self.assertIn(
            "or vault_test_application_project_directory | trim | length > 0",
            collector,
        )

        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/artifacts/", gitignore.splitlines())


if __name__ == "__main__":
    unittest.main()
