"""Reject inline/missing credentials and exercise private runtime resolution."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles/guacamole_deploy"
CANARY = "CONNECTION_CREDENTIAL_CANARY"


ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook")
if ANSIBLE_PLAYBOOK is None:
    raise RuntimeError("The pinned Ansible test runtime is required")


class ConnectionCredentialTests(unittest.TestCase):
    def execute(self, fields, secrets, parameters=None, expected_success=True):
        contract = next(
            x
            for x in yaml.safe_load((ROLE / "tasks/assert.yml").read_text())
            if x["name"] == "Validate declared Guacamole connection contracts"
        )
        resolver = next(
            x
            for x in yaml.safe_load((ROLE / "tasks/reconcile_connection.yml").read_text())
            if x["name"] == "Resolve connection credentials only from the runtime secret bundle"
        )
        connection = {"name": "fixture", "protocol": "ssh", "parameters": parameters or {}, "credential_fields": fields}
        with tempfile.TemporaryDirectory(prefix="guacamole-credential-") as directory:
            path = Path(directory)
            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "guacamole_deploy_connections": [connection],
                        "guacamole_deploy_connection": connection,
                        "guacamole_deploy_secrets": secrets,
                    },
                    "tasks": [
                        contract,
                        resolver,
                        {
                            "ansible.builtin.assert": {
                                "that": [
                                    "guacamole_deploy_connection_parameters_runtime == "
                                    "{'private-key': guacamole_deploy_secrets['sshkey']}"
                                ]
                            },
                            "no_log": True,
                        },
                    ],
                }
            ]
            (path / "play.yml").write_text(yaml.safe_dump(play))
            (path / "ansible.cfg").write_text("[defaults]\n")
            result = subprocess.run(  # noqa: S603 - execute only the controlled local Ansible fixture
                [ANSIBLE_PLAYBOOK, "-i", "localhost,", "-c", "local", str(path / "play.yml")],
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(path / "ansible.cfg"),
                    "ANSIBLE_LOCAL_TEMP": str(path / "ansible"),
                },
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
        self.assertNotIn(CANARY, result.stdout + result.stderr)
        if expected_success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)

    def test_runtime_field_resolves_without_log_disclosure(self):
        self.execute({"private-key": "sshkey"}, {"sshkey": CANARY})

    def test_absent_runtime_field_fails(self):
        self.execute({"private-key": "missing"}, {"sshkey": CANARY}, expected_success=False)

    def test_unapproved_parameter_cannot_be_overridden(self):
        self.execute({"hostname": "sshkey"}, {"sshkey": CANARY}, expected_success=False)

    def test_inline_private_key_is_forbidden(self):
        self.execute({}, {"sshkey": CANARY}, parameters={"private-key": CANARY}, expected_success=False)

    def test_blank_runtime_credential_fails(self):
        self.execute({"private-key": "sshkey"}, {"sshkey": "  "}, expected_success=False)


if __name__ == "__main__":
    unittest.main()
