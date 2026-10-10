"""Verify generation, reuse, refusal and tmpfs cleanup without a live Vault."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible import constants as C
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
TASKS = str(ROOT / "roles/vault_secret_bundle/tasks/ssh_keypair.yml")


ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook")
if ANSIBLE_PLAYBOOK is None:
    raise RuntimeError("The pinned Ansible test runtime is required")


class VaultKeypairTests(unittest.TestCase):
    def execute(self, scenario, check=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            collection = path / "ansible_collections/lit/supplementary"
            collection.parent.mkdir(parents=True)
            collection.symlink_to(ROOT, target_is_directory=True)
            existing = {}
            if check and scenario in ("reuse", "mismatch"):
                key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                existing = {
                    "private": key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.TraditionalOpenSSL,
                        serialization.NoEncryption(),
                    ).decode(),
                    "public": key.public_key()
                    .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
                    .decode(),
                }
                if scenario == "mismatch":
                    wrong = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                    existing["public"] = (
                        wrong.public_key()
                        .public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
                        .decode()
                    )
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
            if scenario == "mismatch" and not check:
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
                        else existing,
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
                [ANSIBLE_PLAYBOOK, "-i", "localhost,", "-c", "local", str(path / "play.yml")]
                + (["--check"] if check else []),
                capture_output=True,
                check=False,
                text=True,
                timeout=60,
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(path / "ansible.cfg"),
                    "ANSIBLE_COLLECTIONS_PATH": os.pathsep.join([str(path), *C.COLLECTIONS_PATHS]),
                },
            )
            self.assertEqual(set(ram_root.glob("vault-ssh-keypair-*")), before)
            output = result.stdout + result.stderr
            self.assertNotIn("BEGIN RSA PRIVATE KEY", output)
            self.assertNotIn("PARTIAL_CANARY", output)
            return result.returncode, output

    def test_pair_is_generated_once_and_reused_without_rotation(self):
        code, output = self.execute("reuse")
        self.assertEqual(code, 0, output)

    def test_check_mode_missing_pair_previews_without_generating_files(self):
        code, output = self.execute("missing", check=True)
        self.assertEqual(code, 0, output)
        self.assertIn("changed=1", output)

    def test_check_mode_existing_pair_is_verified_without_changes(self):
        code, output = self.execute("reuse", check=True)
        self.assertEqual(code, 0, output)
        self.assertIn("changed=0", output)

    def test_check_mode_rejects_mismatched_existing_pair(self):
        code, _output = self.execute("mismatch", check=True)
        self.assertNotEqual(code, 0)

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
