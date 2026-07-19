"""Regression tests for exact-owned Incus network and instance lifecycle policy."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "molecule" / "shared" / "incus"
PARTIAL_RUNTIME_SCENARIOS = (
    "atlas-observability-incus_heavy",
    "rsyslog-lifecycle-incus_heavy",
    "samba-lifecycle-incus_heavy",
)


def load_play_tasks(name: str) -> list[dict[str, Any]]:
    payload = yaml.safe_load((SHARED / name).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise AssertionError(f"{name} is not an Ansible playbook")
    tasks = payload[0].get("tasks")
    if not isinstance(tasks, list):
        raise AssertionError(f"{name} has no task list")
    return tasks


def task_named(tasks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    matches = [task for task in tasks if task.get("name") == name]
    if len(matches) != 1:
        raise AssertionError(f"expected one task named {name!r}, got {len(matches)}")
    return matches[0]


class IncusLifecycleTests(unittest.TestCase):
    def test_nested_containers_use_isolated_idmaps(self) -> None:
        for molecule_file in sorted((ROOT / "molecule").glob("*/molecule.yml")):
            config = yaml.safe_load(molecule_file.read_text(encoding="utf-8"))
            for platform in config.get("platforms", []):
                instance_config = {item["key"]: item["value"] for item in platform.get("config", [])}
                if instance_config.get("security.nesting") != "true":
                    continue
                with self.subTest(scenario=molecule_file.parent.name):
                    self.assertEqual(
                        "true",
                        instance_config.get("security.idmap.isolated"),
                        "nested Incus containers must not share per-UID kernel quotas",
                    )

    def test_network_and_instance_ownership_is_atomic(self) -> None:
        tasks = load_play_tasks("create.yml")
        network_create = task_named(tasks, "Create the managed network with atomic exact-owner labels")
        network_argv = str(network_create["ansible.builtin.command"]["argv"])
        self.assertIn("'incus', 'network', 'create'", network_argv)
        self.assertIn("user.lit-molecule-owner=", network_argv)
        self.assertEqual(3, network_create["retries"])
        self.assertEqual(10, network_create["delay"])
        self.assertEqual("molecule_incus_network_create.rc == 0", network_create["until"])

        instance_init = task_named(
            tasks,
            "Initialize missing Incus instances with atomic owner labels and network attachment",
        )
        instance_argv = str(instance_init["ansible.builtin.command"]["argv"])
        self.assertIn("['incus', 'init'", instance_argv)
        self.assertIn("['--network', molecule_incus_network_effective]", instance_argv)
        self.assertIn("user.lit-molecule-owner=", instance_argv)
        self.assertIn("user.lit-molecule-repository=", instance_argv)

    def test_every_attachment_is_verified_before_any_start(self) -> None:
        tasks = load_play_tasks("create.yml")
        names = [str(task.get("name", "")) for task in tasks]
        verify_index = names.index("Verify every instance is attached to the exact-owned network before start")
        start_index = names.index("Start Incus instances")
        self.assertLess(verify_index, start_index)
        self.assertIn("molecule_incus_network_attachments.stdout", str(tasks[verify_index]))

    def test_destroy_is_owner_filtered_and_has_a_fail_closed_postcondition(
        self,
    ) -> None:
        tasks = load_play_tasks("destroy.yml")
        delete_instances = task_named(tasks, "Delete only Incus instances owned by this exact test run")
        self.assertEqual(
            "{{ molecule_incus_instance_owners_at_delete.results }}",
            delete_instances["loop"],
        )
        revalidate_instances = task_named(tasks, "Revalidate ownership immediately before instance deletion")
        self.assertEqual(
            "{{ molecule_incus_exact_owned_instance_names }}",
            revalidate_instances["loop"],
        )
        self.assertIn("molecule_incus_owner_effective", str(delete_instances["when"]))
        delete_network = task_named(tasks, "Delete only the network owned by this exact test run")
        self.assertIn("molecule_incus_network_owner_at_delete.stdout", str(delete_network["when"]))

        postcondition = task_named(tasks, "Fail closed when exact-owned Incus resources remain")
        assertions = postcondition["ansible.builtin.assert"]["that"]
        self.assertIn("molecule_incus_remaining_exact_owned_instances | length == 0", assertions)
        self.assertIn("molecule_incus_remaining_exact_owned_networks | length == 0", assertions)
        self.assertIn("molecule_incus_remaining_network_owner", str(assertions))

    def test_network_lifecycle_evidence_is_recorded_in_every_phase(self) -> None:
        create = (SHARED / "create.yml").read_text(encoding="utf-8")
        cleanup = (SHARED / "cleanup.yml").read_text(encoding="utf-8")
        destroy = (SHARED / "destroy.yml").read_text(encoding="utf-8")
        self.assertIn("-network-ready.json", create)
        self.assertIn("attachment_verified_before_start", create)
        self.assertIn("-network.json", cleanup)
        self.assertIn('"firewall_controller"', cleanup)
        self.assertIn('"firewalld_runtime_zone"', cleanup)
        self.assertIn("-network-destroy.json", destroy)
        self.assertIn("exact_owned_network_remaining", destroy)

    def test_firewalld_binding_is_runtime_scoped_and_destroyed_first(self) -> None:
        create_tasks = load_play_tasks("create.yml")
        create_names = [str(task.get("name", "")) for task in create_tasks]
        inspect = task_named(create_tasks, "Inspect any existing runtime firewalld bridge binding")
        bind = task_named(
            create_tasks,
            "Bind only the exact-owned bridge to the runtime firewalld zone",
        )
        verify = task_named(create_tasks, "Verify the exact runtime firewalld bridge binding")
        for task in (inspect, bind, verify):
            self.assertTrue(task["become"])
            rendered = str(task)
            self.assertIn("molecule_incus_network_effective", rendered)
            self.assertNotIn("--permanent", rendered)
        self.assertLess(
            create_names.index("Refuse a conflicting runtime firewalld bridge binding"),
            create_names.index("Bind only the exact-owned bridge to the runtime firewalld zone"),
        )
        network_create = task_named(create_tasks, "Create the managed network with atomic exact-owner labels")
        network_argv = str(network_create["ansible.builtin.command"]["argv"])
        self.assertIn("ipv4.firewall=", network_argv)
        self.assertIn("user.lit-molecule-firewalld-zone=", network_argv)

        destroy_tasks = load_play_tasks("destroy.yml")
        destroy_names = [str(task.get("name", "")) for task in destroy_tasks]
        removal = task_named(destroy_tasks, "Remove only the exact bridge runtime firewalld binding")
        self.assertTrue(removal["become"])
        self.assertNotIn("--permanent", str(removal))
        self.assertIn("molecule_incus_owner_effective", str(removal["when"]))
        self.assertLess(
            destroy_names.index("Verify the runtime firewalld binding is absent before network deletion"),
            destroy_names.index("Delete only the network owned by this exact test run"),
        )

    def test_network_readiness_proves_lease_route_and_dns(self) -> None:
        tasks = load_play_tasks("create.yml")
        names = [str(task.get("name", "")) for task in tasks]
        start = names.index("Start Incus instances")
        lease = names.index("Wait for an Incus-managed IPv4 lease")
        route = names.index("Verify a guest default IPv4 route")
        dns = names.index("Verify guest DNS through the exact-owned bridge")
        evidence = names.index("Record exact-owned network creation and attachment evidence")
        self.assertLess(start, lease)
        self.assertLess(lease, route)
        self.assertLess(route, dns)
        self.assertLess(dns, evidence)
        create = (SHARED / "create.yml").read_text(encoding="utf-8")
        self.assertIn('"ipv4_leases"', create)
        self.assertIn('"default_routes"', create)
        self.assertIn('"dns_verified": true', create)

    def test_local_identity_is_persisted_across_phases_and_cleared_after_destroy(
        self,
    ) -> None:
        for name in ("create.yml", "cleanup.yml", "destroy.yml"):
            with self.subTest(playbook=name):
                text = (SHARED / name).read_text(encoding="utf-8")
                self.assertIn("MOLECULE_EPHEMERAL_DIRECTORY", text)
                self.assertIn("['--state-file', molecule_incus_local_state_file]", text)

        destroy_tasks = load_play_tasks("destroy.yml")
        names = [str(task.get("name", "")) for task in destroy_tasks]
        self.assertGreater(
            names.index("Remove persisted local identity only after successful cleanup"),
            names.index("Fail closed when exact-owned Incus resources remain"),
        )

    def test_partial_static_networking_is_retired_and_ci_names_are_per_run(
        self,
    ) -> None:
        for scenario in PARTIAL_RUNTIME_SCENARIOS:
            with self.subTest(scenario=scenario):
                root = ROOT / "molecule" / scenario
                config = yaml.safe_load((root / "molecule.yml").read_text(encoding="utf-8"))
                platform = config["platforms"][0]
                self.assertNotIn("ipv4_address", platform)
                self.assertNotIn("ipv4_gateway", platform)
                self.assertNotIn("dns_servers", platform)
                self.assertIn("${MOLECULE_TEST_INSTANCE:-", platform["name"])
                self.assertIn(
                    "../shared/incus/create.yml",
                    (root / "create.yml").read_text(encoding="utf-8"),
                )

        action = (ROOT / ".github" / "actions" / "run-quality-profile" / "action.yml").read_text(encoding="utf-8")
        self.assertIn('echo "MOLECULE_TEST_INSTANCE=$instance"', action)
        self.assertIn('echo "MOLECULE_TEST_IMAGE=$TEST_IMAGE"', action)
        self.assertIn("dependencies.mkdir(parents=True, exist_ok=True)", action)

    def test_quality_action_prunes_only_superseded_exact_owned_resources(
        self,
    ) -> None:
        action = (ROOT / ".github" / "actions" / "run-quality-profile" / "action.yml").read_text(encoding="utf-8")

        self.assertIn("scripts/prune_stale_incus_resources.py", action)
        self.assertLess(
            action.index("command -v incus"),
            action.index("scripts/prune_stale_incus_resources.py"),
        )
        self.assertLess(
            action.index("scripts/prune_stale_incus_resources.py"),
            action.index("molecule test"),
        )

        helper = (ROOT / "scripts" / "prune_stale_incus_resources.py").read_text(encoding="utf-8")
        self.assertIn("run_id != current_run_id", helper)
        self.assertIn("config.get(REPOSITORY_KEY) == repository", helper)
        self.assertIn("bool(config.get(OWNER_KEY))", helper)
        self.assertIn("or used_by", helper)
        self.assertIn('shutil.which("incus")', helper)
        self.assertIn("except (FileNotFoundError, subprocess.CalledProcessError):", helper)

    def test_legacy_static_entrypoint_fails_before_create(self) -> None:
        payload = yaml.safe_load((SHARED / "create-static-network.yml").read_text(encoding="utf-8"))
        self.assertEqual(
            "Reject the retired after-start static-network lifecycle",
            payload[0]["name"],
        )
        self.assertIn("ansible.builtin.assert", payload[0]["tasks"][0])
        self.assertIn("ansible.builtin.import_playbook", payload[1])


if __name__ == "__main__":
    unittest.main()
