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
        validation = block[4]["ansible.builtin.assert"]["that"]
        collision = block[5]["failed_when"]
        self.assertEqual(block[5]["ansible.builtin.command"]["argv"][:3], ["podman", "pod", "exists"])
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
                "postgres_deploy_existing_pod": {"rc": pod_rc},
            }
            valid = all(self._evaluate(check, variables) for check in validation)
            actual = (valid, self._evaluate(collision, variables))
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
