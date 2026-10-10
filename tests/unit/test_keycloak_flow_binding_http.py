"""Exercise narrow flow writes against an offline HTTP fixture."""

import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class FlowBindingHTTPTests(unittest.TestCase):
    def exercise(self, current, target_exists=True, check=False):
        state = {"browserFlow": current, "enabled": False, "unrelated": "keep-me"}
        writes = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, status, payload=None):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if payload is not None:
                    self.wfile.write(json.dumps(payload).encode())

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.respond(200, {"access_token": "BROKER_CONTRACT_CANARY_SECRET"})

            def do_GET(self):
                if self.path.endswith("/authentication/flows"):
                    self.respond(200, [{"alias": "target", "topLevel": True}] if target_exists else [])
                else:
                    self.respond(200, state)

            def do_PUT(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                writes.append(payload)
                if set(payload) != {"browserFlow"}:
                    self.respond(400, {"error": "broad mutation forbidden"})
                    return
                state.update(payload)
                self.respond(204)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(prefix="flow-binding-http-") as temporary:
                path = Path(temporary)
                play = [
                    {
                        "hosts": "localhost",
                        "gather_facts": False,
                        "vars": {
                            "keycloak_cac_url": "http://127.0.0.1:" + str(server.server_port),
                            "keycloak_cac_realm": "master",
                            "keycloak_cac_admin_user": "admin",
                            "keycloak_cac_admin_password": "BROKER_CONTRACT_CANARY_SECRET",
                            "keycloak_cac_validate_certs": True,
                            "keycloak_cac_request_timeout": 5,
                            "keycloak_cac_realm_flow_bindings": [{"realm": "fixture", "browser_flow": "target"}],
                        },
                        "tasks": [
                            {
                                "ansible.builtin.import_tasks": str(
                                    ROOT / "roles/keycloak_cac/tasks/cac_21_realm_flow_bindings.yml"
                                )
                            }
                        ],
                    }
                ]
                (path / "play.yml").write_text(yaml.safe_dump(play))
                (path / "ansible.cfg").write_text("[defaults]\n")
                command = ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path / "play.yml")]
                if check:
                    command.append("--check")
                result = subprocess.run(  # noqa: S603 - execute only the controlled local Ansible fixture
                    command,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=45,
                    env={
                        **os.environ,
                        "ANSIBLE_CONFIG": str(path / "ansible.cfg"),
                        "ANSIBLE_LOCAL_TEMP": str(path / "ansible"),
                        "ANSIBLE_NOCOLOR": "1",
                    },
                )
            self.assertNotIn("BROKER_CONTRACT_CANARY_SECRET", result.stdout + result.stderr)
            self.assertEqual(state["enabled"], False)
            self.assertEqual(state["unrelated"], "keep-me")
            return result, writes, state
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_matching_flow_performs_no_write(self):
        result, writes, state = self.exercise("target")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(writes, [])

    def test_changed_flow_writes_only_browser_field(self):
        result, writes, state = self.exercise("old")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(writes, [{"browserFlow": "target"}])
        self.assertEqual(state["browserFlow"], "target")

    def test_missing_flow_fails_before_write(self):
        result, writes, state = self.exercise("old", target_exists=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(writes, [])

    def test_check_mode_never_writes(self):
        result, writes, state = self.exercise("old", check=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(writes, [])


if __name__ == "__main__":
    unittest.main()
