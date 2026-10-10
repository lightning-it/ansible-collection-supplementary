"""Execute the opt-in boundary without sockets or live Keycloak access."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


class CleanupOptInTests(unittest.TestCase):
    def exercise(self, enabled=None):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            modules = path / "collections/ansible_collections/lit/supplementary/plugins/modules"
            modules.mkdir(parents=True)
            marker = path / "invoked"
            # Canary module isolates the real Ansible task's opt-in predicate.
            # The shipped module's API boundary is exercised by its separate mocked tests.
            (modules / "keycloak_default_role_composites.py").write_text(
                "from pathlib import Path\n"
                "from ansible.module_utils.basic import AnsibleModule\n"
                "spec = {name: {'type': 'str'} for name in ['api_url', 'auth_realm', 'auth_username', 'auth_password', 'realm']}\n"
                "spec.update(validate_certs={'type': 'bool'}, require_empty_realm={'type': 'bool'}, allowed_removals={'type': 'list', 'elements': 'dict'})\n"
                "module = AnsibleModule(argument_spec=spec)\n"
                f"Path({str(marker)!r}).write_text('invoked')\n"
                "module.fail_json(msg='CANARY_MODULE_FAILURE')\n"
            )
            variables = {
                "keycloak_cac_url": "https://keycloak.example.invalid",
                "keycloak_cac_realm": "master",
                "keycloak_cac_admin_user": "fixture",
                "keycloak_cac_admin_password": "CLEANUP_GUARD_CANARY",
                "keycloak_cac_validate_certs": True,
                "keycloak_cac_default_role_cleanup": [
                    {"realm": "fixture", "allowed_removals": [{"name": "offline_access"}]}
                ],
            }
            if enabled is not None:
                variables["keycloak_cac_default_role_cleanup_enabled"] = enabled
            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": variables,
                    "tasks": [
                        {
                            "ansible.builtin.import_tasks": str(
                                ROOT / "roles/keycloak_cac/tasks/cac_22_default_role_cleanup.yml"
                            )
                        }
                    ],
                }
            ]
            (path / "play.yml").write_text(yaml.safe_dump(play))
            (path / "ansible.cfg").write_text("[defaults]\n")
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", "-c", "local", str(path / "play.yml")],
                text=True,
                capture_output=True,
                timeout=30,
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(path / "ansible.cfg"),
                    "ANSIBLE_COLLECTIONS_PATH": str(path / "collections"),
                    "ANSIBLE_LOCAL_TEMP": str(path / "ansible-temp"),
                },
            )
            self.assertNotIn("CLEANUP_GUARD_CANARY", result.stdout + result.stderr)
            return result.returncode, marker.exists()

    def test_catalog_without_opt_in_does_not_invoke_module(self):
        self.assertEqual(self.exercise(), (0, False))

    def test_explicit_false_does_not_invoke_module(self):
        self.assertEqual(self.exercise(False), (0, False))

    def test_explicit_true_invokes_module_and_propagates_failure(self):
        self.assertEqual(self.exercise(True), (2, True))
