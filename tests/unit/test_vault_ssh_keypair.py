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
PREFLIGHT = str(ROOT / "roles/vault_secret_bundle/tasks/keypair_preflight.yml")


ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook")
if ANSIBLE_PLAYBOOK is None:
    raise RuntimeError("The pinned Ansible test runtime is required")

SAFE_FAILURE_CATEGORY = (
    "Keypair fixture failure category: {{ "
    "'python_dependency' if fixture_failure_text "
    "is search('Failed to import|required Python|ImportError|No module named') else "
    "'filesystem_permission' if fixture_failure_text "
    "is search('Permission denied|Read-only file system') else "
    "'unsupported_parameters' if fixture_failure_text is search('Unsupported parameters for') else "
    "'unsupported_algorithm' if fixture_failure_text is search('UnsupportedAlgorithm') else "
    "'invalid_private_key' if fixture_failure_text "
    "is search('not a supported private key type|InvalidPrivateKeyFileError') else "
    "'unsupported_key_type' if fixture_failure_text is search('Key type .* is not supported|InvalidKeyTypeError') else "
    "'module_resolution' if fixture_failure_text is search('could not resolve|module_utils') else "
    "'attribute_error' if fixture_failure_text is search('AttributeError:') else "
    "'type_error' if fixture_failure_text is search('TypeError:') else "
    "'value_error' if fixture_failure_text is search('ValueError:') else "
    "'runtime_error' if fixture_failure_text is search('RuntimeError:') else "
    "'os_error' if fixture_failure_text is search('OSError:|FileNotFoundError:') else "
    "'unsupported_key' if fixture_failure_text "
    "is search('not supported|Unsupported|invalid key') else "
    "'other_censored_failure' }}"
)

SAFE_FAILURE_INPUT = (
    "{{ [ansible_failed_result.msg | default(''), "
    "ansible_failed_result.module_stderr | default(''), "
    "ansible_failed_result.stderr | default(''), "
    "ansible_failed_result.exception | default('')] | join(' ') }}"
)


class VaultKeypairTests(unittest.TestCase):
    def execute(self, scenario, check=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            collection = path / "ansible_collections/lit/supplementary"
            collection.parent.mkdir(parents=True)
            collection.symlink_to(ROOT, target_is_directory=True)
            existing = {"private": "", "public": ""} if scenario == "blank" else {}
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
            tasks = [{"ansible.builtin.import_tasks": PREFLIGHT}, {"ansible.builtin.import_tasks": TASKS}]
            if scenario == "reuse":
                tasks += [
                    {"ansible.builtin.set_fact": {"first_pair": "{{ vault_secret_bundle_effective }}"}, "no_log": True},
                    {"ansible.builtin.import_tasks": PREFLIGHT},
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
                    {"ansible.builtin.import_tasks": PREFLIGHT},
                    {"ansible.builtin.import_tasks": TASKS},
                ]
            diagnostic_messages = {
                "diagnostic": "PARTIAL_CANARY",
                "diagnostic_parameters": "Unsupported parameters for (module): PARTIAL_CANARY",
                "diagnostic_algorithm": "UnsupportedAlgorithm: PARTIAL_CANARY",
                "diagnostic_private_key": "PARTIAL_CANARY is not a supported private key type",
                "diagnostic_key_type": "Key type PARTIAL_CANARY is not supported",
                "diagnostic_os_error": "OSError: [Errno 95] Operation not supported PARTIAL_CANARY",
                "diagnostic_value_error": "ValueError: invalid key PARTIAL_CANARY",
            }
            if scenario in diagnostic_messages:
                tasks = [{"ansible.builtin.fail": {"msg": diagnostic_messages[scenario]}, "no_log": True}]
            if scenario == "diagnostic_stderr":
                tasks = [
                    {
                        "ansible.builtin.command": {
                            "argv": [
                                "python3",
                                "-c",
                                "import sys; sys.stderr.write('TypeError: PARTIAL_CANARY'); sys.exit(1)",
                            ]
                        },
                        "no_log": True,
                    }
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
                    "tasks": [
                        {
                            "block": tasks,
                            "rescue": [
                                {
                                    "ansible.builtin.fail": {"msg": SAFE_FAILURE_CATEGORY},
                                    "vars": {"fixture_failure_text": SAFE_FAILURE_INPUT},
                                }
                            ],
                        }
                    ],
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

    def test_failure_diagnostic_never_discloses_the_protected_module_message(self):
        code, output = self.execute("diagnostic")
        self.assertNotEqual(code, 0)
        self.assertIn("Keypair fixture failure category: other_censored_failure", output)

    def test_key_diagnostic_distinguishes_known_causes_without_disclosing_messages(self):
        for scenario, category in (
            ("diagnostic_parameters", "unsupported_parameters"),
            ("diagnostic_algorithm", "unsupported_algorithm"),
            ("diagnostic_private_key", "invalid_private_key"),
            ("diagnostic_key_type", "unsupported_key_type"),
            ("diagnostic_os_error", "os_error"),
            ("diagnostic_value_error", "value_error"),
        ):
            with self.subTest(category=category):
                code, output = self.execute(scenario)
                self.assertNotEqual(code, 0)
                self.assertIn("Keypair fixture failure category: " + category, output)

    def test_stderr_diagnostic_reports_only_an_allowlisted_exception_category(self):
        code, output = self.execute("diagnostic_stderr")
        self.assertNotEqual(code, 0)
        self.assertIn("Keypair fixture failure category: type_error", output)

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

    def test_blank_stored_pair_is_refused_consistently_before_generation_or_verification(self):
        for check in (False, True):
            with self.subTest(check=check):
                code, _output = self.execute("blank", check=check)
                self.assertNotEqual(code, 0)

    def test_readonly_missing_pair_fails(self):
        code, _output = self.execute("readonly")
        self.assertNotEqual(code, 0)

    def test_partial_pair_fails_before_generation(self):
        code, output = self.execute("partial")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Create a private volatile keypair directory", output)

    def test_wrong_public_key_fails_and_cleans_up_volatile_private_file(self):
        code, _output = self.execute("mismatch")
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
