"""Execute real snapshot assertions/facts with credential-free read-only fixtures."""

import base64
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "roles/keycloak_deploy/tasks"


class NativeNetworkSnapshotContractTests(unittest.TestCase):
    def test_real_snapshot_expressions_preserve_original_bytes_and_parent_identity(self):
        source = yaml.safe_load((TASKS / "native_network_snapshot_file.yml").read_text())
        tasks = []
        for name in ("keycloak", "postgres"):
            for kind, mode in (("quadlet", "0644"), ("manifest", "0600")):
                content = "synthetic original " + name + " " + kind + "\n"
                path = "/etc/fixture/" + name + (".kube" if kind == "quadlet" else ".yml")
                values = {
                    "keycloak_deploy_migration_component": name,
                    "keycloak_deploy_migration_snapshot_file": {"path": path, "kind": kind, "mode": mode},
                    "keycloak_deploy_migration_file_stat": {
                        "stat": {
                            "isreg": True,
                            "islnk": False,
                            "uid": 0,
                            "gid": 0,
                            "mode": mode,
                            "checksum": hashlib.sha256(content.encode()).hexdigest(),
                        }
                    },
                    "keycloak_deploy_migration_parent_stat": {
                        "stat": {
                            "isdir": True,
                            "islnk": False,
                            "uid": 0,
                            "wgrp": False,
                            "woth": False,
                            "dev": 11,
                            "inode": 22,
                        }
                    },
                    "keycloak_deploy_migration_snapshot_read": {"content": base64.b64encode(content.encode()).decode()},
                }
                tasks.append({"name": "Inject fixed noncredential observation", "ansible.builtin.set_fact": values})
                # Execute the actual role assertions and fact builder, not an implementation model.
                tasks.extend(
                    task
                    for task in source
                    if any(key in task for key in ("ansible.builtin.assert", "ansible.builtin.set_fact"))
                )
        tasks.append(
            {
                "name": "Require all original bytes and exact parent bindings",
                "ansible.builtin.assert": {
                    "that": [
                        "keycloak_deploy_migration_snapshot_files | length == 4",
                        "keycloak_deploy_migration_snapshot_files[0].original == "
                        "'synthetic original keycloak quadlet\\n'",
                        "keycloak_deploy_migration_snapshot_files[3].original == "
                        "'synthetic original postgres manifest\\n'",
                        "keycloak_deploy_migration_snapshot_files[0].parent_identities['/etc/fixture'].device == 11",
                        "keycloak_deploy_migration_snapshot_files[0].parent_identities['/etc/fixture'].inode == 22",
                    ],
                    "quiet": True,
                },
            }
        )
        with tempfile.TemporaryDirectory(prefix="native-snapshot-fixture-") as temporary:
            play = Path(temporary) / "snapshot.yml"
            play.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "gather_facts": False,
                            "vars": {
                                "keycloak_deploy_migration_snapshot_files": [],
                                "keycloak_deploy_migration_quadlet_read": {},
                                "keycloak_deploy_migration_manifest_read": {},
                            },
                            "tasks": tasks,
                        }
                    ]
                )
            )
            executable = shutil.which("ansible-playbook")
            self.assertIsNotNone(executable, "Run in pinned Devtools")
            environment = dict(os.environ, ANSIBLE_NOCOLOR="1")
            result = subprocess.run(  # noqa: S603 -- pinned executable and generated local fixture, no shell.
                [executable, "-i", "localhost,", "-c", "local", str(play)],
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
