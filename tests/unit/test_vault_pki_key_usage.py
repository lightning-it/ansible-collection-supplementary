"""Exercise production TLS leaf validation with real signed usage extensions."""

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "pki_usage_fixture", Path(__file__).with_name("test_application_java_ca_trust.py")
)
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)


class VaultPkiKeyUsageTests(unittest.TestCase):
    def exercise_usage(self, usage, accepted):
        ca, leaf, key = FIXTURE.certificate_fixture(leaf_usage=usage)
        ca_pem = ca.public_bytes(serialization.Encoding.PEM).decode()
        candidate = {
            "certificate": leaf.public_bytes(serialization.Encoding.PEM).decode(),
            "private_key": key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ).decode(),
            "ca_chain": [ca_pem],
        }
        with tempfile.TemporaryDirectory(dir=os.environ["HOME"]) as temporary:
            directory = Path(temporary)
            namespace = directory / "collections/ansible_collections/lit"
            namespace.mkdir(parents=True)
            (namespace / "supplementary").symlink_to(ROOT, target_is_directory=True)
            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "vault_pki_certificate_candidate": candidate,
                        "vault_pki_certificate_common_name": "localhost",
                        "vault_pki_certificate_renewal_window_seconds": 3600,
                        "vault_pki_certificate_issuer": {
                            "json": {
                                "data": {
                                    "certificate": ca_pem,
                                    "ca_chain": [ca_pem],
                                }
                            }
                        },
                    },
                    "tasks": [
                        {
                            "ansible.builtin.import_tasks": str(
                                ROOT / "roles/vault_pki_certificate/tasks/validate_document.yml"
                            ),
                            "no_log": True,
                        },
                        {
                            "name": "Mark successful validation before any custody or materialization",
                            "ansible.builtin.copy": {
                                "content": "accepted",
                                "dest": str(directory / "accepted"),
                                "mode": "0600",
                            },
                        },
                    ],
                }
            ]
            play_path = directory / "play.yml"
            play_path.write_text(yaml.safe_dump(play))
            play_path.chmod(0o600)
            config = directory / "ansible.cfg"
            config.write_text("[defaults]\n")
            environment = {
                **os.environ,
                "ANSIBLE_CONFIG": str(config),
                "ANSIBLE_NOCOLOR": "1",
                "ANSIBLE_COLLECTIONS_PATH": str(directory / "collections")
                + ":"
                + os.environ.get("ANSIBLE_COLLECTIONS_PATH", "/opt/ansible/collections:/usr/share/ansible/collections"),
                "ANSIBLE_LOCAL_TEMP": str(directory / "ansible"),
            }
            result = subprocess.run(  # noqa: S603 - generated offline play invoking the production validator
                [shutil.which("ansible-playbook"), "-i", "localhost,", "-c", "local", str(play_path)],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=45,
            )
            self.assertNotIn(candidate["private_key"], result.stdout + result.stderr)
            self.assertEqual(result.returncode == 0, accepted, result.stdout + result.stderr)
            self.assertEqual((directory / "accepted").exists(), accepted)

    def test_tls_signing_and_absent_usage_are_valid(self):
        for usage in (None, ["Digital Signature"], ["Digital Signature", "Key Encipherment", "Key Agreement"]):
            with self.subTest(usage=usage):
                self.exercise_usage(usage, accepted=True)

    def test_nonsigning_and_ca_or_unrelated_usage_cannot_advance(self):
        for usage in (
            ["Key Agreement"],
            ["Key Encipherment"],
            ["Certificate Sign"],
            ["CRL Sign"],
            ["Digital Signature", "Certificate Sign"],
            ["Digital Signature", "CRL Sign"],
            ["Digital Signature", "Data Encipherment"],
            ["Digital Signature", "Non Repudiation"],
        ):
            with self.subTest(usage=usage):
                self.exercise_usage(usage, accepted=False)


if __name__ == "__main__":
    unittest.main()
