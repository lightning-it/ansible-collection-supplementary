"""Real HTTPS previews may read custody but must never issue or write."""

import importlib.util
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[2]
CANARY = "OFFLINE_PKI_CANARY"
SPEC = importlib.util.spec_from_file_location(
    "pki_trust_fixture", Path(__file__).with_name("test_application_java_ca_trust.py")
)
FIXTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIXTURE)
certificate_fixture = FIXTURE.certificate_fixture


class VaultPkiCheckModeTests(unittest.TestCase):
    def exercise(self, role, existing, foreign_issuer=False):
        ca, certificate, key = certificate_fixture()
        pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
        protected = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        requests = []
        payload = {
            "data": {
                "data": {
                    "schema_version": 1,
                    "subject": "localhost",
                    "issue_path": "pki/issuer/existing/issue/server",
                    "certificate": pem,
                    "private_key": protected,
                },
                "metadata": {"version": 1},
            }
        }
        if foreign_issuer:
            payload["data"]["data"]["issue_path"] = "pki/issuer/foreign/issue/server"
        if role == "vault_pki_leaf_role":
            payload = {"data": {"allowed_domains": ["other.example"]}}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append(("GET", self.path))
                self.send_response(200 if existing else 404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload if existing else {"errors": []}).encode())

            def do_POST(self):
                requests.append(("POST", self.path))
                self.send_response(403)
                self.end_headers()

        with tempfile.TemporaryDirectory(dir=os.environ["HOME"]) as temporary:
            directory = Path(temporary)
            ca_path = directory / "ca.pem"
            ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
            cert_path = directory / "server.pem"
            key_path = directory / "server.key"
            cert_path.write_text(pem)
            key_path.write_text(protected)
            key_path.chmod(0o600)
            server = HTTPServer(("127.0.0.1", 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            values = yaml.safe_load((ROOT / "roles" / role / "defaults/main.yml").read_text())
            values.update(
                {role + "_api_url": "https://localhost:" + str(server.server_port), role + "_ca_path": str(ca_path)}
            )
            if role == "vault_pki_certificate":
                values.update(
                    vault_pki_certificate_kv_path="fixture/data/server",
                    vault_pki_certificate_kv_token=CANARY,
                    vault_pki_certificate_common_name="localhost",
                    vault_pki_certificate_issue_path="pki/issuer/existing/issue/server",
                    vault_pki_certificate_cert_path=str(directory / "materialized.pem"),
                    vault_pki_certificate_key_path=str(directory / "materialized.key"),
                )
            else:
                values.update(
                    vault_pki_leaf_role_mount="pki",
                    vault_pki_leaf_role_name="server",
                    vault_pki_leaf_role_admin_token=CANARY,
                    vault_pki_leaf_role_allow_change=True,
                    vault_pki_leaf_role_definition={
                        "allowed_domains": ["localhost"],
                        "allow_any_name": False,
                        "allow_subdomains": False,
                        "allow_glob_domains": False,
                        "allow_ip_sans": False,
                        "allow_localhost": False,
                        "issuer_ref": "existing",
                    },
                )
            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": values,
                    "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "roles" / role / "tasks/main.yml")}],
                }
            ]
            source = directory / "play.yml"
            source.write_text(yaml.safe_dump(play))
            config = directory / "ansible.cfg"
            config.write_text("[defaults]\n")
            try:
                result = subprocess.run(  # noqa: S603 - controlled offline role fixture
                    [shutil.which("ansible-playbook"), "-i", "localhost,", "-c", "local", "--check", str(source)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=45,
                    env={
                        **os.environ,
                        "ANSIBLE_CONFIG": str(config),
                        "ANSIBLE_NOCOLOR": "1",
                        "ANSIBLE_LOCAL_TEMP": str(directory / "ansible"),
                    },
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            self.assertNotIn("OFFLINE_PKI_CANARY", result.stdout + result.stderr)
            if foreign_issuer:
                self.assertNotEqual(result.returncode, 0)
            else:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stdout, r"changed=1(?:\s|$)")
            self.assertEqual([method for method, _path in requests], ["GET"])
            self.assertFalse((directory / "materialized.pem").exists())
            self.assertFalse((directory / "materialized.key").exists())

    def test_missing_and_expiring_certificate_previews_are_read_only(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.exercise("vault_pki_certificate", existing)

    def test_foreign_issuer_custody_is_rejected_before_issuance(self):
        self.exercise("vault_pki_certificate", True, foreign_issuer=True)

    def test_missing_and_changed_leaf_role_previews_are_read_only(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                self.exercise("vault_pki_leaf_role", existing)


if __name__ == "__main__":
    unittest.main()
