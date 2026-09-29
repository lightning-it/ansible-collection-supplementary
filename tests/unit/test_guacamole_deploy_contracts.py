"""Security contracts for Guacamole deployment."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "main.yml"
ASSERTS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "assert.yml"
DEFAULTS = ROOT / "roles" / "guacamole_deploy" / "defaults" / "main.yml"
POD = ROOT / "roles" / "guacamole_deploy" / "templates" / "guacamole-pod.yml.j2"
SYSTEMD_TASKS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "systemd.yml"
LEGACY_SERVICE = ROOT / "roles" / "guacamole_deploy" / "templates" / "guacamole.service.j2"
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

    def test_static_network_and_proxy_bypass_are_exact_and_default_off(self) -> None:
        defaults = DEFAULTS.read_text(encoding="utf-8")
        asserts = ASSERTS.read_text(encoding="utf-8")
        pod = POD.read_text(encoding="utf-8")
        systemd_tasks = SYSTEMD_TASKS.read_text(encoding="utf-8")

        self.assertIn('guacamole_deploy_network_name: ""', defaults)
        self.assertIn('guacamole_deploy_network_ipv4: ""', defaults)
        self.assertIn("guacamole_deploy_no_proxy: []", defaults)
        self.assertIn('guacamole_deploy_proxy_url: ""', defaults)
        self.assertIn("(guacamole_deploy_network_name | length == 0)", asserts)
        self.assertIn("== (guacamole_deploy_network_ipv4 | length == 0)", asserts)
        self.assertIn("guacamole_deploy_no_proxy | unique", asserts)
        self.assertIn("guacamole_deploy_quadlet_networks", defaults)
        self.assertIn(
            'podman_systemd_networks: "{{ guacamole_deploy_quadlet_networks }}"',
            systemd_tasks,
        )
        self.assertIn("name: no_proxy", pod)
        self.assertIn("name: NO_PROXY", pod)
        self.assertIn("name: HTTPS_PROXY", pod)
        self.assertIn("name: JAVA_TOOL_OPTIONS", pod)
        self.assertIn("-Dhttp.proxyHost=", pod)
        self.assertIn("-Dhttp.proxyPort=", pod)
        self.assertIn("-Dhttps.proxyHost=", pod)
        self.assertIn("-Dhttps.proxyPort=", pod)
        self.assertIn("-Dhttp.nonProxyHosts=", pod)
        self.assertIn("guacamole_deploy_proxy_url | to_json", pod)
        self.assertIn("':[1-9][0-9]{0,4}\\\\Z'", asserts)
        self.assertIn("regex_replace('^.*:([0-9]+)$', '\\\\1')", asserts)
        self.assertIn(") <= 65535", asserts)
        self.assertIn("guacamole_deploy_no_proxy | join(',') | to_json", pod)
        non_application_containers = pod.split("    - name: guacamole", 1)[0]
        self.assertNotIn("http_proxy", non_application_containers)
        self.assertNotIn("HTTP_PROXY", non_application_containers)
        self.assertNotIn("HTTPS_PROXY", non_application_containers)
        self.assertNotIn("JAVA_TOOL_OPTIONS", non_application_containers)

    def test_persistent_lifecycle_uses_only_native_quadlet(self) -> None:
        tasks = TASKS.read_text(encoding="utf-8")
        systemd_tasks = SYSTEMD_TASKS.read_text(encoding="utf-8")

        self.assertFalse(LEGACY_SERVICE.exists())
        self.assertIn("include_tasks: systemd.yml", tasks)
        self.assertIn("name: lit.foundational.podman_systemd", systemd_tasks)
        self.assertLess(
            systemd_tasks.index("Refuse an unsafe legacy Guacamole unit path before reading"),
            systemd_tasks.index("Read the exact legacy Guacamole unit before takeover"),
        )
        self.assertIn("guacamole_deploy_legacy_unit_stat.stat.isreg", systemd_tasks)
        self.assertIn("no_log: true", systemd_tasks)
        self.assertIn("Refuse to replace an unknown Guacamole systemd unit", systemd_tasks)
        self.assertIn("not (guacamole_deploy_legacy_unit_stat.stat.islnk", systemd_tasks)
        self.assertIn(
            "Stop and disable the exact legacy Guacamole unit before removal",
            systemd_tasks,
        )
        self.assertIn(
            'name: "{{ guacamole_deploy_legacy_systemd_unit_path | basename }}"',
            systemd_tasks,
        )
        self.assertLess(
            systemd_tasks.index("Stop and disable the exact legacy Guacamole unit before removal"),
            systemd_tasks.index("Remove the verified legacy Guacamole systemd unit"),
        )
        self.assertNotIn("podman kube play", tasks)
        self.assertNotIn("podman kube down", tasks)
        self.assertIn(
            "guacamole_deploy_legacy_systemd_unit_path: >-\n  /etc/systemd/system/guacamole.service",
            DEFAULTS.read_text(encoding="utf-8"),
        )

    def test_oidc_group_claim_and_exact_connection_permissions_are_explicit(
        self,
    ) -> None:
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
