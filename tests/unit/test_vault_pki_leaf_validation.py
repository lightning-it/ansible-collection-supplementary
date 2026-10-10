"""Exercise the actual Ansible certificate modules and role leaf predicates."""

import datetime
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook")
if ANSIBLE_PLAYBOOK is None:
    raise RuntimeError("The pinned Ansible test runtime is required")


class LeafValidationTest(unittest.TestCase):
    def exercise(self, ca):
        root = Path(__file__).resolve().parents[2]
        tasks = yaml.safe_load((root / "roles/vault_pki_certificate/tasks/main.yml").read_text())
        tasks = tasks[0]["block"]
        predicates = [
            t
            for t in next(
                task["block"]
                for task in tasks
                if task["name"] == "Validate and materialize an available final certificate"
            )
            if t["name"]
            in ("Require the valid exact public DNS server identity", "Require the protected matching server key pair")
        ]
        self.assertEqual(len(predicates), 2)
        with tempfile.TemporaryDirectory(dir=os.environ["HOME"]) as directory:
            directory = Path(directory)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fixture.example")])
            issuer_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            issuer_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Offline declared issuer")])
            now = datetime.datetime.now(datetime.UTC)
            issuer = (
                x509.CertificateBuilder()
                .subject_name(issuer_name)
                .issuer_name(issuer_name)
                .public_key(issuer_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                .sign(issuer_key, hashes.SHA256())
            )
            builder = (
                x509.CertificateBuilder()
                .subject_name(name)
                .issuer_name(issuer_name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("fixture.example")]), False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
            )
            if ca:
                builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            (directory / "certificate.pem").write_bytes(
                builder.sign(issuer_key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
            )
            (directory / "key.pem").write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                )
            )
            (directory / "key.pem").chmod(0o600)
            play = [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "vars": {
                        "vault_pki_certificate_common_name": "fixture.example",
                        "vault_pki_certificate_issuer": {
                            "content": issuer.public_bytes(serialization.Encoding.PEM).decode()
                        },
                        "vault_pki_certificate_readback": {
                            "json": {"data": {"data": {"certificate": (directory / "certificate.pem").read_text()}}}
                        },
                    },
                    "tasks": [
                        {
                            "name": "Inspect real public fixture",
                            "community.crypto.x509_certificate_info": {
                                "path": str(directory / "certificate.pem"),
                                "valid_at": {"now": "+0s"},
                            },
                            "register": "vault_pki_certificate_info",
                        },
                        {
                            "name": "Inspect real protected fixture key",
                            "community.crypto.openssl_privatekey_info": {"path": str(directory / "key.pem")},
                            "register": "vault_pki_certificate_key_info",
                            "no_log": True,
                        },
                        *predicates,
                    ],
                }
            ]
            path = directory / "play.yml"
            path.write_text(yaml.safe_dump(play))
            config = directory / "ansible.cfg"
            config.write_text("[defaults]\n")
            environment = {k: v for k, v in os.environ.items() if k != "ANSIBLE_VAULT_PASSWORD_FILE"}
            namespace = directory / "collections/ansible_collections/lit"
            namespace.mkdir(parents=True)
            (namespace / "supplementary").symlink_to(root, target_is_directory=True)
            environment["ANSIBLE_COLLECTIONS_PATH"] = (
                str(directory / "collections")
                + ":"
                + environment.get("ANSIBLE_COLLECTIONS_PATH", "/opt/ansible/collections:/usr/share/ansible/collections")
            )
            result = subprocess.run(  # noqa: S603 - execute only the controlled local Ansible fixture
                [ANSIBLE_PLAYBOOK, "-i", "localhost,", str(path)],
                capture_output=True,
                check=False,
                text=True,
                timeout=60,
                env={**environment, "ANSIBLE_CONFIG": str(config), "ANSIBLE_REMOTE_TMP": str(directory / "tmp")},
            )
            return result.returncode, result.stdout + result.stderr

    def test_vault_leaf_without_basic_constraints_is_accepted(self):
        code, output = self.exercise(False)
        self.assertEqual(code, 0, output[-2000:])

    def test_certificate_authority_is_rejected(self):
        code, output = self.exercise(True)
        self.assertNotEqual(code, 0)
        self.assertIn("Require the valid exact public DNS server identity", output)


if __name__ == "__main__":
    unittest.main()
