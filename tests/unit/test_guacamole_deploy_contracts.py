"""Security contracts for Guacamole deployment."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "main.yml"
ASSERTS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "assert.yml"
DEFAULTS = ROOT / "roles" / "guacamole_deploy" / "defaults" / "main.yml"
POD = ROOT / "roles" / "guacamole_deploy" / "templates" / "guacamole-pod.yml.j2"


class GuacamoleDeployContractTests(unittest.TestCase):
    def test_breakglass_sql_uses_psql_quoted_variables(self) -> None:
        source = TASKS.read_text(encoding="utf-8")

        self.assertIn("breakglass_salt={{ guacamole_deploy_secrets.breakglass_salt }}", source)
        self.assertIn("convert_to(:'breakglass_salt','UTF8')", source)
        self.assertIn("decode(:'breakglass_hash','hex')", source)
        self.assertIn("name = :'breakglass_user'", source)
        self.assertNotIn("convert_to('{{ guacamole_deploy_secrets.breakglass_salt }}'", source)

    def test_prechecks_are_imported_before_mutation(self) -> None:
        source = TASKS.read_text(encoding="utf-8")

        self.assertIn("ansible.builtin.import_tasks: assert.yml", source)
        self.assertLess(
            source.index("import_tasks: assert.yml"),
            source.index("ansible.builtin.package:"),
        )

    def test_api_session_timeout_is_bounded_and_rendered(self) -> None:
        defaults = DEFAULTS.read_text(encoding="utf-8")
        asserts = ASSERTS.read_text(encoding="utf-8")
        pod = POD.read_text(encoding="utf-8")

        self.assertIn("guacamole_deploy_api_session_timeout_minutes: 60", defaults)
        self.assertIn("guacamole_deploy_api_session_timeout_minutes is integer", asserts)
        self.assertIn("guacamole_deploy_api_session_timeout_minutes is not boolean", asserts)
        self.assertIn("guacamole_deploy_api_session_timeout_minutes >= 1", asserts)
        self.assertIn("guacamole_deploy_api_session_timeout_minutes <= 1440", asserts)
        self.assertNotIn("guacamole_deploy_api_session_timeout_minutes | int", asserts)
        self.assertIn("name: API_SESSION_TIMEOUT", pod)
        self.assertIn("guacamole_deploy_api_session_timeout_minutes | string | to_json", pod)

    def test_host_port_rejects_yaml_booleans_and_is_bounded(self) -> None:
        asserts = ASSERTS.read_text(encoding="utf-8")

        self.assertIn("guacamole_deploy_port is integer", asserts)
        self.assertIn("guacamole_deploy_port is not boolean", asserts)
        self.assertIn("guacamole_deploy_port > 0", asserts)
        self.assertIn("guacamole_deploy_port <= 65535", asserts)
        self.assertNotIn("guacamole_deploy_port | int", asserts)


if __name__ == "__main__":
    unittest.main()
