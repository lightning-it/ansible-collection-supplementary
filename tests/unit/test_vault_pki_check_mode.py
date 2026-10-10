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
    def exercise(
        self,
        role,
        existing,
        foreign_issuer=False,
        apply=False,
        bare_domains=True,
        expansion=None,
        forged=False,
        omitted=None,
        failing_path=None,
        bad_issuance=None,
    ):
        ca, certificate, key = certificate_fixture()
        pem = certificate.public_bytes(serialization.Encoding.PEM).decode()
        protected = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        issued_pem, issued_key = pem, protected
        if bad_issuance:
            _foreign_ca, foreign_leaf, foreign_key = certificate_fixture()
            issued_key = foreign_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ).decode()
            if bad_issuance == "foreign_issuer":
                issued_pem = foreign_leaf.public_bytes(serialization.Encoding.PEM).decode()
        requests = []
        original_existing = existing
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
        if forged:
            _wrong_ca, wrong_leaf, wrong_key = certificate_fixture()
            payload["data"]["data"]["certificate"] = wrong_leaf.public_bytes(serialization.Encoding.PEM).decode()
            payload["data"]["data"]["private_key"] = wrong_key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            ).decode()
        if foreign_issuer:
            payload["data"]["data"]["issue_path"] = "pki/issuer/foreign/issue/server"
        if role == "vault_pki_leaf_role":
            payload = {"data": {"allowed_domains": ["other.example"], "max_ttl": 3600, "key_type": "ec"}}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                requests.append(("GET", self.path))
                if self.path == "/v1/pki/issuer/existing/pem":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(ca.public_bytes(serialization.Encoding.PEM))
                    return
                self.send_response(200 if existing else 404)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload if existing else {"errors": []}).encode())

            def do_POST(self):
                nonlocal existing, payload
                requests.append(("POST", self.path))
                incoming = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if apply and role == "vault_pki_certificate":
                    if self.path == failing_path:
                        self.send_response(403)
                        self.end_headers()
                        return
                    if self.path == "/v1/auth/approle/login":
                        response = {"auth": {"client_token": CANARY}}
                    elif self.path == "/v1/fixture/data/server":
                        payload = {"data": {"data": incoming["data"], "metadata": {"version": 2}}}
                        existing = True
                        response = {"data": {"version": 2}}
                    else:
                        response = {
                            "data": {
                                "certificate": issued_pem,
                                "private_key": issued_key,
                                "ca_chain": [ca.public_bytes(serialization.Encoding.PEM).decode()],
                                "serial_number": "fixture",
                            }
                        }
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(response).encode())
                    return
                if apply and role == "vault_pki_leaf_role" and not existing:
                    payload = {"data": incoming}
                    existing = True
                    self.send_response(204)
                    self.end_headers()
                    return
                self.send_response(403)
                self.end_headers()

            def do_PATCH(self):
                requests.append(("PATCH", self.path))
                if self.headers.get("Content-Type") != "application/merge-patch+json":
                    self.send_response(415)
                else:
                    payload["data"].update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                    self.send_response(204)
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
            context.minimum_version = ssl.TLSVersion.TLSv1_2
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
                    vault_pki_certificate_issuing_identity={"role_id": CANARY, "secret_id": CANARY},
                )
            else:
                values.update(
                    vault_pki_leaf_role_mount="pki",
                    vault_pki_leaf_role_name="server",
                    vault_pki_leaf_role_admin_token=CANARY,
                    vault_pki_leaf_role_allow_change=True,
                    vault_pki_leaf_role_definition={
                        "allowed_domains": ["localhost"],
                        "allow_bare_domains": bare_domains,
                        "allow_wildcard_certificates": False,
                        "allow_any_name": False,
                        "allow_subdomains": False,
                        "allow_glob_domains": False,
                        "allow_ip_sans": False,
                        "allow_localhost": False,
                        "issuer_ref": "existing",
                    },
                )
            if omitted:
                del values["vault_pki_leaf_role_definition"][omitted]
            if expansion:
                values["vault_pki_leaf_role_definition"].update(expansion)
            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {**values, "role_fixture": role},
                    "tasks": [
                        {
                            "block": [{"ansible.builtin.import_tasks": str(ROOT / "roles" / role / "tasks/main.yml")}],
                            "always": [
                                {
                                    "ansible.builtin.assert": {
                                        "that": [
                                            "vault_pki_certificate_existing == {}",
                                            "vault_pki_certificate_existing_info == {}",
                                            "vault_pki_certificate_login == {}",
                                            "vault_pki_certificate_issued == {}",
                                            "vault_pki_certificate_issued_document == {}",
                                            "vault_pki_certificate_readback == {}",
                                            "vault_pki_certificate_info == {}",
                                            "vault_pki_certificate_key_info == {}",
                                            "vault_pki_certificate_cert_copy == {}",
                                            "vault_pki_certificate_key_copy == {}",
                                        ]
                                    },
                                    "no_log": True,
                                    "when": "role_fixture == 'vault_pki_certificate'",
                                }
                            ],
                        }
                    ],
                }
            ]
            source = directory / "play.yml"
            source.write_text(yaml.safe_dump(play))
            config = directory / "ansible.cfg"
            config.write_text("[defaults]\n")
            namespace = directory / "collections/ansible_collections/lit"
            namespace.mkdir(parents=True)
            (namespace / "supplementary").symlink_to(ROOT, target_is_directory=True)
            try:
                result = subprocess.run(  # noqa: S603 - controlled offline role fixture
                    [shutil.which("ansible-playbook"), "-i", "localhost,", "-c", "local"]
                    + ([] if apply else ["--check"])
                    + [str(source)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=45,
                    env={
                        **os.environ,
                        "ANSIBLE_CONFIG": str(config),
                        "ANSIBLE_NOCOLOR": "1",
                        "ANSIBLE_COLLECTIONS_PATH": str(directory / "collections")
                        + ":"
                        + os.environ.get(
                            "ANSIBLE_COLLECTIONS_PATH", "/opt/ansible/collections:/usr/share/ansible/collections"
                        ),
                        "ANSIBLE_LOCAL_TEMP": str(directory / "ansible"),
                    },
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
            self.assertNotIn("OFFLINE_PKI_CANARY", result.stdout + result.stderr)
            if foreign_issuer or not bare_domains or expansion or forged or omitted or failing_path or bad_issuance:
                self.assertNotEqual(result.returncode, 0)
            else:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertRegex(result.stdout, r"changed=1(?:\s|$)")
            if not bare_domains or expansion or omitted:
                self.assertEqual(requests, [])
            elif bad_issuance:
                self.assertIn(("POST", "/v1/pki/issuer/existing/issue/server"), requests)
                self.assertNotIn(("POST", "/v1/fixture/data/server"), requests)
            elif failing_path:
                self.assertIn(("POST", failing_path), requests)
                self.assertNotIn("Readback cleanup failed", result.stdout)
            elif apply and role == "vault_pki_certificate":
                self.assertEqual([method for method, _path in requests], ["GET", "GET", "POST", "POST", "POST", "GET"])
                self.assertEqual(payload["data"]["metadata"]["version"], 2)
                self.assertEqual((directory / "materialized.key").read_text(), protected)
            elif apply:
                self.assertEqual(
                    [method for method, _path in requests], ["GET", "PATCH" if original_existing else "POST", "GET"]
                )
                if original_existing:
                    self.assertEqual(payload["data"]["max_ttl"], 3600)
                    self.assertEqual(payload["data"]["key_type"], "ec")
            else:
                self.assertEqual(
                    [method for method, _path in requests],
                    ["GET", "GET"] if role == "vault_pki_certificate" else ["GET"],
                )
            if not (apply and role == "vault_pki_certificate" and not failing_path and not bad_issuance):
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

    def test_existing_role_patch_preserves_undeclared_restrictions_and_new_role_uses_post(self):
        for existing in (True, False):
            self.exercise("vault_pki_leaf_role", existing, apply=True)

    def test_exact_domains_require_bare_domain_issuance_before_api_access(self):
        self.exercise("vault_pki_leaf_role", True, bare_domains=False)

    def test_forged_custody_with_copied_metadata_cannot_pass_issuer_verification(self):
        self.exercise("vault_pki_certificate", True, forged=True)

    def test_issuance_and_custody_failure_clear_tokens_and_private_responses(self):
        for path in ("/v1/pki/issuer/existing/issue/server", "/v1/fixture/data/server"):
            with self.subTest(path=path):
                self.exercise("vault_pki_certificate", False, apply=True, failing_path=path)

    def test_invalid_issuance_never_advances_kv_custody(self):
        for fault in ("foreign_issuer", "key_mismatch"):
            with self.subTest(fault=fault):
                self.exercise("vault_pki_certificate", False, apply=True, bad_issuance=fault)

    def test_every_expansion_flag_must_be_explicit_boolean_false(self):
        for field in (
            "allow_any_name",
            "allow_subdomains",
            "allow_glob_domains",
            "allow_ip_sans",
            "allow_localhost",
            "allow_wildcard_certificates",
        ):
            with self.subTest(field=field):
                self.exercise("vault_pki_leaf_role", False, omitted=field)
                self.exercise("vault_pki_leaf_role", False, expansion={field: "false"})

    def test_name_expansion_options_fail_before_api_access(self):
        for expansion in (
            {"allow_wildcard_certificates": True},
            {"allowed_uri_sans": ["*"]},
            {"allowed_other_sans": ["*"]},
            {"allowed_domains_template": True},
        ):
            self.exercise("vault_pki_leaf_role", True, expansion=expansion)


if __name__ == "__main__":
    unittest.main()
