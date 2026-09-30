"""Validate PostgreSQL legacy-to-Quadlet transition contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles" / "postgres_deploy"


class PostgresSystemdPreservationTests(unittest.TestCase):
    def test_quadlet_takeover_fails_closed_for_unmanaged_pods(self) -> None:
        block = yaml.safe_load((ROLE / "tasks/systemd.yml").read_text(encoding="utf-8"))[0]["block"]
        tasks = {task["name"]: task for task in block}
        validation = tasks["Refuse unknown PostgreSQL lifecycle states"]
        collision = tasks["Refuse unmanaged PostgreSQL pod; remove it first"]
        stage = tasks["Stage the native PostgreSQL Quadlet before legacy shutdown"]
        stop = tasks["Stop and disable the exact legacy PostgreSQL unit before Quadlet takeover"]
        manage = tasks["Manage the native PostgreSQL Quadlet service"]

        self.assertEqual(collision["ansible.builtin.command"]["argv"][:3], ["podman", "pod", "exists"])
        self.assertIn("postgres_deploy_native_systemd_active", collision["failed_when"])
        self.assertLess(block.index(validation), block.index(collision))
        self.assertLess(block.index(collision), block.index(stage))
        self.assertLess(block.index(stage), block.index(stop))
        self.assertLess(block.index(stop), block.index(manage))
        self.assertEqual(manage["vars"]["podman_systemd_networks"], "{{ postgres_deploy_networks }}")
        self.assertFalse((ROLE / "templates/podman-kube@.service.j2").exists())


if __name__ == "__main__":
    unittest.main()
