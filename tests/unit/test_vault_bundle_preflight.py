"""Malformed key declarations must fail before any Vault request or generation."""

import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class BundlePreflightTests(unittest.TestCase):
    def test_all_keypair_interfaces_are_checked_before_vault_access(self):
        for pairs in (
            ["scalar"],
            [{"private_field": "private", "public_field": "private"}],
            [{"private_field": "private", "public_field": "bad-name"}],
            [{"private_field": "private", "public_field": "public", "extra": True}],
            [{"private_field": "private", "public_field": "public"}] * 2,
            [{"private_field": "password", "public_field": "public"}],
        ):
            with self.subTest(pairs=pairs), tempfile.TemporaryDirectory(dir=os.environ["HOME"]) as temporary:
                requests = []

                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *args):
                        pass

                    def do_GET(self, requests=requests):
                        requests.append(self.path)
                        self.send_response(500)
                        self.end_headers()

                server = HTTPServer(("127.0.0.1", 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                directory = Path(temporary)
                defaults = yaml.safe_load((ROOT / "roles/vault_secret_bundle/defaults/main.yml").read_text())
                defaults.update(
                    vault_secret_bundle_address=f"http://127.0.0.1:{server.server_port}",
                    vault_secret_bundle_kv_path="offline-fixture",  # noqa: S106 - public dummy KV path
                    vault_secret_bundle_token="OFFLINE_BUNDLE_CANARY",  # noqa: S106 - offline canary
                    vault_secret_bundle_items=[{"name": "password"}],
                    vault_secret_bundle_ssh_keypairs=pairs,
                )
                role_tasks = ROOT / "roles/vault_secret_bundle/tasks/main.yml"
                play = [
                    {
                        "hosts": "localhost",
                        "gather_facts": False,
                        "vars": defaults,
                        "tasks": [{"ansible.builtin.import_tasks": str(role_tasks)}],
                    }
                ]
                source = directory / "play.yml"
                source.write_text(yaml.safe_dump(play))
                config = directory / "ansible.cfg"
                config.write_text("[defaults]\n")
                try:
                    result = subprocess.run(  # noqa: S603 - controlled offline Ansible fixture
                        [shutil.which("ansible-playbook"), "-i", "localhost,", "-c", "local", str(source)],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                        env={**os.environ, "ANSIBLE_CONFIG": str(config)},
                    )
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(requests, [])
                self.assertIn("Validate every SSH keypair declaration", result.stdout)
                self.assertNotIn("Read the existing secret bundle", result.stdout)
                self.assertNotIn("Generate only missing", result.stdout)
                self.assertNotIn("OFFLINE_BUNDLE_CANARY", result.stdout + result.stderr)
