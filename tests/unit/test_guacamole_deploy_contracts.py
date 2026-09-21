"""Security contracts for Guacamole deployment."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "main.yml"
ASSERTS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "assert.yml"
DEFAULTS = ROOT / "roles" / "guacamole_deploy" / "defaults" / "main.yml"
POD = ROOT / "roles" / "guacamole_deploy" / "templates" / "guacamole-pod.yml.j2"
OIDC_GROUP_TASKS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "reconcile_oidc_groups.yml"


class GuacamoleDeployContractTests(unittest.TestCase):
    def test_connection_contract_validation_redacts_inventory_credentials(self) -> None:
        asserts = ASSERTS.read_text(encoding="utf-8")
        connection_contract = asserts.split("- name: Validate declared Guacamole connection contracts", 1)[1]

        self.assertIn("no_log: true", connection_contract)

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
        self.assertIn(
            "Apache Guacamole defines API_SESSION_TIMEOUT in minutes",
            pod,
        )
        self.assertIn("guacamole_deploy_api_session_timeout_minutes | string | to_json", pod)
        self.assertNotIn("guacamole_deploy_api_session_timeout_minutes * 60000", pod)

    def test_host_port_rejects_yaml_booleans_and_is_bounded(self) -> None:
        asserts = ASSERTS.read_text(encoding="utf-8")

        self.assertIn("guacamole_deploy_port is integer", asserts)
        self.assertIn("guacamole_deploy_port is not boolean", asserts)
        self.assertIn("guacamole_deploy_port > 0", asserts)
        self.assertIn("guacamole_deploy_port <= 65535", asserts)
        self.assertNotIn("guacamole_deploy_port | int", asserts)

    def test_oidc_group_claim_and_exact_connection_permissions_are_explicit(self) -> None:
        defaults = DEFAULTS.read_text(encoding="utf-8")
        asserts = ASSERTS.read_text(encoding="utf-8")
        pod = POD.read_text(encoding="utf-8")
        tasks = TASKS.read_text(encoding="utf-8")
        group_tasks = OIDC_GROUP_TASKS.read_text(encoding="utf-8")

        self.assertIn('guacamole_deploy_oidc_groups_claim_type: "groups"', defaults)
        self.assertIn("guacamole_deploy_oidc_group_connections: []", defaults)
        self.assertIn("name: OPENID_GROUPS_CLAIM_TYPE", pod)
        self.assertIn("Validate declared Guacamole OIDC group authorization contracts", asserts)
        self.assertIn("difference(guacamole_deploy_connections", asserts)
        self.assertIn("Reject duplicate Guacamole connection names", asserts)
        self.assertIn("Reject duplicate Guacamole OIDC authorization group names", asserts)
        self.assertGreater(
            asserts.index("Validate declared Guacamole OIDC group authorization contracts"),
            asserts.index("Validate declared Guacamole connection contracts"),
        )
        self.assertIn("include_tasks: reconcile_oidc_groups.yml", tasks)
        self.assertGreater(
            tasks.index("include_tasks: reconcile_oidc_groups.yml"),
            tasks.index("include_tasks: reconcile_connection.yml"),
        )
        self.assertIn("guacamole_deploy_oidc_groups_claim_type is string", asserts)
        self.assertIn("lit_guacamole_oidc_managed_group", group_tasks)
        self.assertIn("count(connection.connection_id) <> 1", group_tasks)
        self.assertIn("DELETE FROM guacamole_entity AS entity", group_tasks)
        self.assertIn("permission.permission <> 'READ'", group_tasks)
        self.assertIn("SELECT managed_entity_id, connection.connection_id, 'READ'", group_tasks)
        self.assertIn("user_group.disabled IS DISTINCT FROM false", group_tasks)
        self.assertIn("DELETE FROM guacamole_system_permission", group_tasks)
        self.assertIn("DELETE FROM guacamole_user_group_member", group_tasks)
        self.assertIn("SELECT jsonb_array_elements_text(connection_names)", group_tasks)
        self.assertIn("CREATE TEMPORARY TABLE lit_oidc_group_input", group_tasks)
        self.assertNotIn("set_config(", group_tasks)
        self.assertIn("no_log: true", group_tasks)
        self.assertNotIn("{{ guacamole_deploy_oidc_group.", group_tasks)


if __name__ == "__main__":
    unittest.main()
