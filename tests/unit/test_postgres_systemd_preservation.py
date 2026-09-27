"""Contract tests for PostgreSQL native Quadlet lifecycle ownership."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles" / "postgres_deploy"


class PostgresSystemdPreservationTests(unittest.TestCase):
    def test_native_quadlet_replaces_only_the_exact_legacy_instance(self) -> None:
        block = yaml.safe_load((ROLE / "tasks/systemd.yml").read_text())[0]["block"]

        legacy_active = next(task for task in block if task.get("register") == "postgres_deploy_legacy_systemd_active")
        self.assertEqual(
            legacy_active["ansible.builtin.command"]["argv"][:2],
            ["systemctl", "is-active"],
        )
        self.assertIs(legacy_active["changed_when"], False)
        self.assertIs(legacy_active["failed_when"], False)

        stage_index = next(
            index
            for index, task in enumerate(block)
            if task["name"] == "Stage the native PostgreSQL Quadlet before legacy shutdown"
        )
        legacy_stop = next(
            task
            for task in block
            if task["name"] == "Stop and disable the exact legacy PostgreSQL unit before Quadlet takeover"
        )
        legacy_stop_index = block.index(legacy_stop)
        self.assertLess(stage_index, legacy_stop_index)
        legacy_name = legacy_stop["ansible.builtin.systemd"]["name"]
        self.assertIn("postgres_deploy_legacy_systemd_name.stdout", legacy_name)
        self.assertEqual(legacy_stop["ansible.builtin.systemd"]["state"], "stopped")
        self.assertIs(legacy_stop["ansible.builtin.systemd"]["enabled"], False)

        quadlet = next(task for task in block if task["name"] == "Manage the native PostgreSQL Quadlet service")
        self.assertEqual(
            quadlet["ansible.builtin.include_role"]["name"],
            "lit.foundational.podman_systemd",
        )
        self.assertEqual(
            quadlet["vars"]["podman_systemd_quadlet_dir"],
            "{{ postgres_deploy_quadlet_dir }}",
        )
        self.assertIn("restarted", quadlet["vars"]["podman_systemd_action"])
        self.assertFalse((ROLE / "templates/podman-kube@.service.j2").exists())


if __name__ == "__main__":
    unittest.main()
