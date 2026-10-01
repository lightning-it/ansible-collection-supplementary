"""Validate PostgreSQL legacy-to-Quadlet transition contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.conditional import Conditional
from ansible.template import Templar

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles" / "postgres_deploy"


class PostgresSystemdPreservationTests(unittest.TestCase):
    @staticmethod
    def _evaluate(condition: str, variables: dict) -> bool:
        loader = DataLoader()
        conditional = Conditional(loader=loader)
        conditional.when = [condition]
        return conditional.evaluate_conditional(Templar(loader=loader, variables=variables), variables)

    def test_real_lifecycle_tasks_cover_accepted_and_rejected_states(self) -> None:
        block = yaml.safe_load((ROLE / "tasks/systemd.yml").read_text(encoding="utf-8"))[0]["block"]
        task_map = {task["name"]: task for task in block}
        validation = task_map["Refuse unknown PostgreSQL lifecycle states"]["ansible.builtin.assert"]["that"]
        collision_task = task_map["Refuse unmanaged PostgreSQL pod; remove it first"]
        collision = collision_task["failed_when"]
        self.assertEqual(collision_task["ansible.builtin.command"]["argv"][:3], ["podman", "pod", "exists"])
        self.assertIn("postgres_deploy_native_systemd_active", collision)
        self.assertFalse((ROLE / "templates/podman-kube@.service.j2").exists())
        cases = (
            ((3, "inactive", 3, "inactive", 1), (True, False)),
            ((0, "active", 3, "inactive", 0), (True, False)),
            ((3, "inactive", 0, "active", 0), (True, False)),
            ((3, "inactive", 3, "inactive", 0), (True, True)),
            ((3, "inactive", 2, "activating", 1), (False, False)),
            ((3, "inactive", 3, "inactive", 7), (True, True)),
        )
        for (legacy_rc, legacy, native_rc, native, pod_rc), expected in cases:
            variables = {
                "postgres_deploy_legacy_systemd_active": {"rc": legacy_rc, "stdout": legacy},
                "postgres_deploy_legacy_systemd_enabled": {"rc": 1, "stdout": "disabled"},
                "postgres_deploy_native_systemd_active": {"rc": native_rc, "stdout": native},
                "postgres_deploy_native_systemd_enabled": {"rc": 1, "stdout": "disabled"},
                "postgres_deploy_existing_pod": {"rc": pod_rc},
            }
            valid = all(self._evaluate(check, variables) for check in validation)
            actual = (valid, self._evaluate(collision, variables))
            self.assertEqual(actual, expected)

        lifecycle_contract = "\n".join(str(item) for item in validation)
        for unsupported in ("static", "indirect", "transient", "linked"):
            self.assertNotIn(unsupported, lifecycle_contract)

        ownership = task_map["Refuse unproven drift in an existing native PostgreSQL Quadlet"]
        ownership_contract = "\n".join(str(item) for item in ownership["ansible.builtin.assert"]["that"])
        self.assertIn("postgres_deploy_native_quadlet_file.stat.isreg", ownership_contract)
        self.assertIn("postgres_deploy_native_quadlet_file.stat.islnk", ownership_contract)
        self.assertIn("Description=' ~ postgres_deploy_systemd_description", ownership_contract)
        self.assertIn("Yaml=' ~ postgres_deploy_pod_manifest_path", ownership_contract)
        self.assertIn("postgres_deploy_native_systemd_enabled", ownership_contract)


if __name__ == "__main__":
    unittest.main()
