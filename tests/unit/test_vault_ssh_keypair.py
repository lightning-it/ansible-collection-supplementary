"""Verify generation, reuse, refusal and tmpfs cleanup without a live Vault."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TASKS = str(ROOT / "roles/vault_secret_bundle/tasks/ssh_keypair.yml")


ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook")
if ANSIBLE_PLAYBOOK is None:
    raise RuntimeError("The pinned Ansible test runtime is required")


class VaultKeypairTests(unittest.TestCase):
    def execute(self, scenario):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            tasks = [{"ansible.builtin.import_tasks": TASKS}]
            if scenario == "reuse":
                tasks += [
                    {"ansible.builtin.set_fact": {"first_pair": "{{ vault_secret_bundle_effective }}"}, "no_log": True},
                    {"ansible.builtin.import_tasks": TASKS},
                    {
                        "ansible.builtin.assert": {"that": ["vault_secret_bundle_effective == first_pair"]},
                        "no_log": True,
                    },
                ]
            if scenario == "mismatch":
                tasks += [
                    {
                        "ansible.builtin.set_fact": {
                            "vault_secret_bundle_effective": (
                                "{{ vault_secret_bundle_effective | combine({'public': 'ssh-rsa wrong'}) }}"
                            )
                        },
                        "no_log": True,
                    },
                    {"ansible.builtin.import_tasks": TASKS},
                ]
            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "vault_secret_bundle_keypair": {"private_field": "private", "public_field": "public"},
                        "vault_secret_bundle_effective": {"public": "ssh-rsa PARTIAL_CANARY"}
                        if scenario == "partial"
                        else {},
                        "vault_secret_bundle_generate_missing": scenario != "readonly",
                    },
                    "tasks": tasks,
                }
            ]
            (path / "play.yml").write_text(yaml.safe_dump(play))
            (path / "ansible.cfg").write_text("[defaults]\n")
            ram_root = Path("/dev/shm")  # noqa: S108 - inspect the role-owned RAM cleanup boundary
            before = set(ram_root.glob("vault-ssh-keypair-*"))
            result = subprocess.run(  # noqa: S603 - execute only the controlled local Ansible fixture
                [ANSIBLE_PLAYBOOK, "-i", "localhost,", "-c", "local", str(path / "play.yml")],
                capture_output=True,
                check=False,
                text=True,
                timeout=60,
                env={**os.environ, "ANSIBLE_CONFIG": str(path / "ansible.cfg")},
            )
            self.assertEqual(set(ram_root.glob("vault-ssh-keypair-*")), before)
            output = result.stdout + result.stderr
            self.assertNotIn("BEGIN RSA PRIVATE KEY", output)
            self.assertNotIn("PARTIAL_CANARY", output)
            return result.returncode, output

    def test_pair_is_generated_once_and_reused_without_rotation(self):
        code, output = self.execute("reuse")
        self.assertEqual(code, 0, output)

    def test_readonly_missing_pair_fails(self):
        code, _output = self.execute("readonly")
        self.assertNotEqual(code, 0)

    def test_partial_pair_fails_before_generation(self):
        code, _output = self.execute("partial")
        self.assertNotEqual(code, 0)

    def test_wrong_public_key_fails_and_cleans_up_volatile_private_file(self):
        code, _output = self.execute("mismatch")
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
