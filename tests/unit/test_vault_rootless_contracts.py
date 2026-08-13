"""Regression contracts for capability-minimized Vault test ownership."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class VaultRootlessContractsTests(unittest.TestCase):
    def test_production_ownership_defaults_remain_root(self) -> None:
        bootstrap_defaults = yaml.safe_load(
            (ROOT / "roles/vault_bootstrap/defaults/main.yml").read_text(encoding="utf-8")
        )
        snapshot_defaults = yaml.safe_load(
            (ROOT / "roles/vault_raft_snapshot/defaults/main.yml").read_text(encoding="utf-8")
        )

        self.assertEqual("root", bootstrap_defaults["vault_bootstrap_target_escrow_owner"])
        self.assertEqual("root", bootstrap_defaults["vault_bootstrap_target_escrow_group"])
        self.assertEqual("root", snapshot_defaults["vault_raft_snapshot_restore_work_root_owner"])
        self.assertEqual("root", snapshot_defaults["vault_raft_snapshot_restore_work_root_group"])
        self.assertIs(False, snapshot_defaults["vault_raft_snapshot_restore_test_mode"])
        self.assertEqual("", snapshot_defaults["vault_raft_snapshot_restore_test_root"])

    def test_bootstrap_molecule_rejects_names_and_proves_numeric_metadata(self) -> None:
        converge = (ROOT / "molecule/vault-bootstrap-basic/converge.yml").read_text(encoding="utf-8")
        escrow_sync = (ROOT / "roles/vault_bootstrap/tasks/controller_escrow_sync.yml").read_text(encoding="utf-8")

        self.assertIn("vault_bootstrap_target_escrow_owner: invalid-owner", converge)
        self.assertIn("vault_bootstrap_target_escrow_group: invalid-group", converge)
        self.assertIn("Require exact numeric target escrow ownership and modes", converge)
        self.assertIn("item.stat.mode == ('0700' if", converge)
        self.assertIn("is match('^[0-9]+$')", escrow_sync)
        self.assertNotIn("is regex(", escrow_sync)
        self.assertIn("fail_msg:", escrow_sync)

    def test_snapshot_molecule_and_role_enforce_exact_work_root_metadata(self) -> None:
        converge = (ROOT / "molecule/vault-raft-snapshot-basic/converge.yml").read_text(encoding="utf-8")
        verify = (ROOT / "molecule/vault-raft-snapshot-basic/verify.yml").read_text(encoding="utf-8")
        restore = (ROOT / "roles/vault_raft_snapshot/tasks/restore_drill.yml").read_text(encoding="utf-8")

        self.assertIn("vault_raft_snapshot_restore_work_root_owner: invalid-owner", converge)
        self.assertIn("vault_raft_snapshot_restore_work_root_group: invalid-group", converge)
        self.assertIn("MOLECULE_EPHEMERAL_DIRECTORY') }}/vault-raft-restore", converge)
        self.assertIn("vault_raft_snapshot_molecule_restore_root }}/work", converge)
        self.assertIn("vault_raft_snapshot_molecule_numeric_production_root_refused", converge)
        self.assertIn("vault_raft_snapshot_molecule_forged_environment_refused", converge)
        self.assertIn("vault_raft_snapshot_molecule_trailing_slash_root_refused", converge)
        self.assertIn("vault_raft_snapshot_molecule_symlink_parent_refused", converge)
        self.assertIn("vault_raft_snapshot_molecule_restore_work_root", verify)
        self.assertNotIn("- /run/lit-vault-raft-molecule", verify)
        self.assertIn("Require exact isolated Vault restore-drill directory metadata", restore)
        self.assertIn("item.stat.mode | default('') == item.item.mode", restore)
        assertions = (ROOT / "roles/vault_raft_snapshot/tasks/assert.yml").read_text(encoding="utf-8")
        self.assertIn("^/run/[A-Za-z0-9._-]+$", assertions)
        self.assertIn("^/tmp/[A-Za-z0-9._/-]+$", assertions)
        self.assertNotIn("MOLECULE_EPHEMERAL_DIRECTORY", assertions)
        self.assertIn("vault_raft_snapshot_restore_test_mode is sameas true", assertions)
        self.assertIn("ansible_connection == 'local'", assertions)
        self.assertIn("_vault_raft_snapshot_restore_test_controller_identity.stdout | int > 0", assertions)
        self.assertIn("--canonicalize-missing", assertions)
        self.assertIn("not vault_raft_snapshot_restore_test_root.endswith('/')", assertions)


if __name__ == "__main__":
    unittest.main()
