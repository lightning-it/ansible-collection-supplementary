"""Execute exact username/tier selection and API-error credential cleanup."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CANARY = "OFFLINE_PRIVATE_CREDENTIAL_CANARY" + "X" * 32


class CredentialSelectionTests(unittest.TestCase):
    def execute(self, tasks, values, success=True):
        with tempfile.TemporaryDirectory(dir=os.environ["HOME"]) as temporary:
            directory = Path(temporary)
            config = directory / "ansible.cfg"
            config.write_text("[defaults]\n")
            play = directory / "play.yml"
            play.write_text(
                yaml.safe_dump([{"hosts": "localhost", "gather_facts": False, "vars": values, "tasks": tasks}])
            )
            result = subprocess.run(  # noqa: S603 - controlled local Ansible fixture
                [shutil.which("ansible-playbook"), "-i", "localhost,", "-c", "local", str(play)],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                env={**os.environ, "ANSIBLE_CONFIG": str(config), "ANSIBLE_LOCAL_TEMP": str(directory / "ansible")},
            )
        output = result.stdout + result.stderr
        self.assertNotIn(CANARY, output)
        if success:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0)

    def test_same_username_in_two_tiers_selects_only_exact_tier(self):
        sequence = yaml.safe_load((ROOT / "roles/vault_connection_credentials/tasks/read_source.yml").read_text())[1]
        tasks = [{"block": sequence["block"][1:], "always": sequence["always"]}]
        values = {
            "vault_connection_credentials_source": {
                "username": "p1000u",
                "tier": "tier-2",
                "subject": "fixture",
                "purpose": "desktop",
                "destination": "password",
            },
            "vault_connection_credentials_document": {
                "secret": {
                    "schema_version": 1,
                    "subject": "fixture",
                    "purpose": "desktop",
                    "accounts": [
                        {"username": "p1000u", "tier": "tier-1", "password": "FOREIGN" * 8},
                        {"username": "p1000u", "tier": "tier-2", "password": CANARY},
                    ],
                }
            },
            "vault_connection_credentials_result": {},
            "fixture_expected": CANARY,
        }
        tasks.append(
            {
                "ansible.builtin.assert": {
                    "that": [
                        "vault_connection_credentials_result.password == fixture_expected",
                        "vault_connection_credentials_document == {}",
                        "vault_connection_credentials_matches == []",
                    ]
                },
                "no_log": True,
            }
        )
        self.execute(tasks, values)
        values["vault_connection_credentials_document"]["secret"]["accounts"].append(
            {"username": "p1000u", "tier": "tier-2", "password": CANARY}
        )
        self.execute(tasks, values, success=False)

    def test_guacamole_api_failure_clears_private_parameters(self):
        reconciliation = yaml.safe_load((ROOT / "roles/guacamole_deploy/tasks/reconcile_connection.yml").read_text())
        tasks = [
            {
                "block": reconciliation,
                "rescue": [
                    {"ansible.builtin.assert": {"that": ["vault_fixture_expected_failure | bool"]}},
                    {"ansible.builtin.set_fact": {"fixture_failure_observed": True}},
                ],
            },
            {
                "ansible.builtin.assert": {
                    "that": [
                        "fixture_failure_observed | default(false) | bool",
                        "guacamole_deploy_connection_parameters_runtime == {}",
                    ]
                }
            },
        ]
        self.execute(
            tasks,
            {
                "vault_fixture_expected_failure": True,
                "guacamole_deploy_existing_connections": {"json": {}},
                "guacamole_deploy_api_url": "http://127.0.0.1:1",
                "guacamole_deploy_validate_certs": True,
                "guacamole_deploy_api_login": {"json": {"dataSource": "postgresql", "authToken": "OFFLINE"}},
                "guacamole_deploy_connection": {
                    "name": "fixture",
                    "protocol": "rdp",
                    "credential_fields": {"password": "password"},
                },
                "guacamole_deploy_secrets": {"password": CANARY},
            },
        )


if __name__ == "__main__":
    unittest.main()
