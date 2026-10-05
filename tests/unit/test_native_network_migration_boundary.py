"""Exercise real native ownership assertions before a coupled migration fix."""

from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class NativeNetworkMigrationBoundaryTests(unittest.TestCase):
    def test_real_ownership_rejects_changed_networks_and_foreign_units(self):
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "Use the pinned Devtools container")
        tasks = []
        for role, label in (("keycloak_deploy", "Keycloak"), ("postgres_deploy", "PostgreSQL")):
            source = yaml.safe_load((ROOT / f"roles/{role}/tasks/systemd.yml").read_text())
            ownership = next(
                task
                for task in source[0]["block"]
                if task["name"] == f"Refuse unproven drift in an existing native {label} Quadlet"
            )
            for case, existing_networks, foreign_description, expected_rejected in (
                ("unchanged", ["private.network:ip=192.0.2.3"], False, False),
                ("old-default-network", [], False, True),
                ("foreign-unit", ["private.network:ip=192.0.2.3"], True, True),
            ):
                unit = "fixture-identity" if role == "keycloak_deploy" else "fixture-database"
                description = "Fixture service"
                manifest = f"/etc/podman/pods/{unit}.yml"
                lines = [
                    "[Unit]",
                    "Description=" + ("Foreign service" if foreign_description else description),
                    "After=network-online.target",
                    "Wants=network-online.target",
                    "[Kube]",
                    "Yaml=" + manifest,
                ]
                lines += ["Network=" + network for network in existing_networks]
                lines += ["[Install]", "WantedBy=multi-user.target"]
                variables = {
                    role + "_native_quadlet_file": {
                        "stat": {
                            "exists": True,
                            "isreg": True,
                            "islnk": False,
                            "mode": "0644",
                            "pw_name": "root",
                            "gr_name": "root",
                        }
                    },
                    role + "_native_quadlet_read": {
                        "content": base64.b64encode(("\n".join(lines) + "\n").encode()).decode()
                    },
                    role + "_native_drop_in_paths": {"rc": 0, "stdout": ""},
                    role + "_native_systemd_active": {"rc": 0, "stdout": "active"},
                    role + "_native_systemd_enabled": {"rc": 0, "stdout": "generated"},
                    role + "_native_fragment_path": {"rc": 0, "stdout": f"/run/systemd/generator/{unit}.service"},
                    role + "_systemd_unit_name": unit,
                    role + "_systemd_description": description,
                    role + "_pod_manifest_path": manifest,
                    role + "_systemd_enabled": True,
                    role + "_networks": ["private.network:ip=192.0.2.3"],
                }
                tasks += [
                    {"name": f"Reset rejection {role}/{case}", "ansible.builtin.set_fact": {"fixture_rejected": False}},
                    {
                        "name": f"Real ownership {role}/{case}",
                        "vars": variables,
                        "block": [ownership],
                        "rescue": [
                            {
                                "name": "Record expected rejection",
                                "ansible.builtin.set_fact": {"fixture_rejected": True},
                            }
                        ],
                    },
                    {
                        "name": f"Require exact outcome {role}/{case}",
                        "ansible.builtin.assert": {
                            "that": ["fixture_rejected is " + ("true" if expected_rejected else "false")],
                            "quiet": True,
                        },
                    },
                ]
        with tempfile.TemporaryDirectory(prefix="native-network-boundary-") as temporary:
            play = Path(temporary) / "ownership.yml"
            play.write_text(
                yaml.safe_dump(
                    [
                        {
                            "name": "Native network ownership regression",
                            "hosts": "localhost",
                            "gather_facts": False,
                            "tasks": tasks,
                        }
                    ]
                )
            )
            result = subprocess.run(  # noqa: S603 -- pinned executable and generated local fixture, no shell.
                [executable, "-i", "localhost,", "-c", "local", str(play)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
