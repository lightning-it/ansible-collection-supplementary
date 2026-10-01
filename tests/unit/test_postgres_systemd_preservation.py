"""Validate PostgreSQL legacy-to-Quadlet transition contracts."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles" / "postgres_deploy"


class PostgresSystemdPreservationTests(unittest.TestCase):
    def test_real_lifecycle_tasks_cover_accepted_and_rejected_states(self) -> None:
        block = yaml.safe_load((ROLE / "tasks/systemd.yml").read_text(encoding="utf-8"))[0]["block"]
        task_map = {task["name"]: task for task in block}
        validation = task_map["Refuse unknown PostgreSQL lifecycle states"]["ansible.builtin.assert"]["that"]
        collision_task = task_map["Refuse unmanaged PostgreSQL pod; remove it first"]
        collision = collision_task["failed_when"]
        self.assertEqual(collision_task["ansible.builtin.command"]["argv"][:3], ["podman", "pod", "exists"])
        self.assertIn("postgres_deploy_native_systemd_active", collision)
        self.assertFalse((ROLE / "templates/podman-kube@.service.j2").exists())
        lifecycle_contract = str(validation)
        for contract in ("legacy_systemd_active", "native_systemd_active"):
            self.assertIn(contract, lifecycle_contract)
        for unsupported in ("activating", "static", "indirect", "transient", "linked"):
            self.assertNotIn(unsupported, lifecycle_contract)
        ownership = task_map["Refuse unproven drift in an existing native PostgreSQL Quadlet"]
        ownership_contract = "\n".join(str(item) for item in ownership["ansible.builtin.assert"]["that"])
        for contract in ("isreg", "islnk", "Description=", "Yaml=", "native_systemd_enabled"):
            self.assertIn(contract, ownership_contract)
        transaction = task_map["Cut over to native PostgreSQL Quadlet with rollback"]
        self.assertEqual(transaction["block"][0]["name"], "Render the transactional PostgreSQL Pod manifest")
        rescue_source = "\n".join(str(task) for task in transaction["rescue"])
        for contract in (
            "exact pre-transaction PostgreSQL Pod manifest",
            "transaction-created PostgreSQL Pod manifest",
            "generated native PostgreSQL service",
            "native PostgreSQL inactivity",
            "exact legacy PostgreSQL service",
        ):
            self.assertIn(contract, rescue_source)
        pod_tasks = yaml.safe_load((ROLE / "tasks/deploy_pod.yml").read_text(encoding="utf-8"))
        manifest_render = next(task for task in pod_tasks if task["name"].startswith("Render PostgreSQL Pod manifest"))
        self.assertIn("not postgres_deploy_manage_systemd", manifest_render["when"])


if __name__ == "__main__":
    unittest.main()
