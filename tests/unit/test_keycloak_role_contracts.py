"""Contract tests for Keycloak role interfaces and portable service identities."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).parents[2]


class KeycloakRoleContractTests(unittest.TestCase):
    def _role_defaults(self, role: str) -> dict[str, object]:
        path = ROOT / "roles" / role / "defaults" / "main.yml"
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertIsInstance(loaded, dict)
        return loaded

    def _role_options(self, role: str) -> dict[str, dict[str, object]]:
        path = ROOT / "roles" / role / "meta" / "argument_specs.yml"
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        options = loaded["argument_specs"]["main"]["options"]
        self.assertIsInstance(options, dict)
        return options

    def _assert_documented_options(self, options: dict[str, dict[str, object]]) -> None:
        for name, option in options.items():
            with self.subTest(option=name):
                self.assertIn("type", option)
                self.assertIsInstance(option.get("description"), str)
                self.assertTrue(str(option["description"]).strip())
                nested = option.get("options")
                if nested is not None:
                    self.assertIsInstance(nested, dict)
                    self._assert_documented_options(nested)

    def test_every_keycloak_default_has_a_typed_described_argument(self) -> None:
        for role in ("keycloak_deploy", "keycloak_cac"):
            with self.subTest(role=role):
                defaults = self._role_defaults(role)
                options = self._role_options(role)
                self.assertEqual(set(defaults), set(options))
                self._assert_documented_options(options)

    def test_secret_bearing_arguments_are_suppressed_from_logs(self) -> None:
        deploy = self._role_options("keycloak_deploy")
        deploy_secrets = {
            "keycloak_deploy_db_password",
            "keycloak_deploy_admin_password",
            "keycloak_deploy_env_extra",
            "keycloak_deploy_vault_token",
            "keycloak_deploy_vault_role_id",
            "keycloak_deploy_vault_secret_id",
            "keycloak_deploy_vault_auth_token",
            "keycloak_deploy_vault_auth_role_id",
            "keycloak_deploy_vault_auth_secret_id",
        }
        for name in deploy_secrets:
            with self.subTest(option=name):
                self.assertIs(deploy[name].get("no_log"), True)

        cac = self._role_options("keycloak_cac")
        cac_secrets = {
            "keycloak_cac_admin_password",
            "keycloak_cac_realms",
            "keycloak_cac_clients",
            "keycloak_cac_users",
            "keycloak_cac_groups",
            "keycloak_cac_roles",
            "keycloak_cac_user_role_mappings",
            "keycloak_cac_samba_ldap_provider",
            "keycloak_cac_ldap_providers",
        }
        for name in cac_secrets:
            with self.subTest(option=name):
                self.assertIs(cac[name].get("no_log"), True)

        ldap_options = cac["keycloak_cac_samba_ldap_provider"]["options"]
        self.assertIs(ldap_options["bind_credential"].get("no_log"), True)

    def _assert_portable_group_expression(self, expression: object) -> None:
        self.assertIsInstance(expression, str)
        template = Environment(autoescape=False).from_string(expression)  # noqa: S701

        self.assertEqual(template.render(ansible_facts={"os_family": "Debian"}).strip(), "nogroup")
        self.assertEqual(template.render(ansible_facts={"os_family": "RedHat"}).strip(), "nobody")
        self.assertEqual(template.render(ansible_facts={"os_family": "Suse"}).strip(), "")
        self.assertEqual(template.render().strip(), "")

    def test_service_group_defaults_are_portable_and_fail_closed(self) -> None:
        samba_expression = self._role_defaults("samba_deploy")["samba_deploy_share_group"]
        self._assert_portable_group_expression(samba_expression)

        acceptance_path = ROOT / "molecule" / "keycloak-application-acceptance" / "converge.yml"
        acceptance_source = acceptance_path.read_text(encoding="utf-8")
        acceptance_plays = yaml.safe_load(acceptance_source)
        acceptance_expression = acceptance_plays[1]["vars"]["keycloak_acceptance_service_group"]
        self._assert_portable_group_expression(acceptance_expression)
        self.assertIn("User={{ keycloak_acceptance_service_user }}", acceptance_source)
        self.assertIn("Group={{ keycloak_acceptance_service_group }}", acceptance_source)

    def test_samba_bind_identity_matches_keycloak_ldap_provider(self) -> None:
        samba_defaults = self._role_defaults("samba_deploy")
        expected_cn = " ".join(
            (
                str(samba_defaults["samba_deploy_ad_dc_keycloak_bind_given_name"]),
                str(samba_defaults["samba_deploy_ad_dc_keycloak_bind_surname"]),
            )
        )

        cac_defaults = self._role_defaults("keycloak_cac")
        default_bind_dn = cac_defaults["keycloak_cac_samba_ldap_provider"]["bind_dn"]
        self.assertEqual(default_bind_dn, f"CN={expected_cn},CN=Users,DC=corp,DC=example,DC=com")

        heavy_path = ROOT / "molecule" / "keycloak-heavy" / "converge.yml"
        heavy_plays = yaml.safe_load(heavy_path.read_text(encoding="utf-8"))
        heavy_provider = heavy_plays[1]["vars"]["keycloak_cac_samba_ldap_provider"]
        self.assertEqual(
            heavy_provider["bind_dn"],
            f"CN={expected_cn},CN=Users,DC=keycloak,DC=test",
        )

    def test_postgres_manifest_with_password_is_owner_only(self) -> None:
        tasks_path = ROOT / "roles" / "postgres_deploy" / "tasks" / "deploy_pod.yml"
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))
        render_task = next(task for task in tasks if task.get("name", "").startswith("Render PostgreSQL Pod manifest"))

        self.assertEqual(render_task["ansible.builtin.template"]["mode"], "0600")
        self.assertIs(render_task["no_log"], True)

        systemd_block = yaml.safe_load(
            (ROOT / "roles" / "postgres_deploy" / "tasks" / "systemd.yml").read_text(encoding="utf-8")
        )[0]["block"]
        transaction = next(
            task for task in systemd_block if task["name"] == "Cut over to native PostgreSQL Quadlet with rollback"
        )
        transactional_render = transaction["block"][0]
        self.assertEqual(transactional_render["ansible.builtin.template"]["mode"], "0600")
        self.assertIs(transactional_render["no_log"], True)

        template_path = ROOT / "roles" / "postgres_deploy" / "templates" / "postgres-pod.yml.j2"
        self.assertIn("POSTGRES_PASSWORD", template_path.read_text(encoding="utf-8"))

    def test_keycloak_lifecycle_has_one_controller_and_verifies_runtime(self) -> None:
        pod_tasks_path = ROOT / "roles" / "keycloak_deploy" / "tasks" / "deploy_pod.yml"
        pod_tasks = yaml.safe_load(pod_tasks_path.read_text(encoding="utf-8"))
        pod_task_map = {task["name"]: task for task in pod_tasks}
        recreate = pod_task_map["Recreate Keycloak pod from the desired manifest"]
        self.assertEqual(recreate["vars"]["kubeplay_action"], "recreate")
        self.assertIn("not keycloak_deploy_manage_systemd | bool", recreate["when"])
        systemd_block = yaml.safe_load((ROOT / "roles/keycloak_deploy/tasks/systemd.yml").read_text(encoding="utf-8"))[
            0
        ]["block"]
        systemd_map = {task["name"]: task for task in systemd_block}
        transaction = systemd_map["Cut over to native Keycloak Quadlet with rollback"]
        transaction_map = {task["name"]: task for task in transaction["block"]}
        quadlet = transaction_map["Manage the native Keycloak Quadlet service"]
        self.assertEqual(quadlet["ansible.builtin.include_role"]["name"], "lit.foundational.podman_systemd")
        for contract in (
            "keycloak_deploy_pod_manifest_path",
            "keycloak_deploy_quadlet_dir",
            "keycloak_deploy_networks",
        ):
            self.assertIn(contract, str(quadlet["vars"]))
        stage = transaction_map["Stage the native Keycloak Quadlet before legacy shutdown"]
        names = [task["name"] for task in systemd_block]
        validation_index = names.index("Refuse unknown Keycloak lifecycle states")
        collision_index = next(index for index, name in enumerate(names) if "Refuse unmanaged Keycloak" in name)
        collision = systemd_block[collision_index]
        self.assertEqual(collision["ansible.builtin.command"]["argv"][:3], ["podman", "pod", "exists"])
        self.assertIn("keycloak_deploy_native_systemd_active", collision["failed_when"])
        ownership = systemd_map["Refuse unproven drift in an existing native Keycloak Quadlet"]
        ownership_contract = "\n".join(str(item) for item in ownership["ansible.builtin.assert"]["that"])
        for contract in ("isreg", "islnk", "Description=", "Yaml=", "native_systemd_enabled"):
            self.assertIn(contract, ownership_contract)
        lifecycle_contract = str(systemd_block[validation_index]["ansible.builtin.assert"]["that"])
        for unsupported in ("activating", "reloading", "deactivating", "static", "indirect", "transient", "linked"):
            self.assertNotIn(unsupported, lifecycle_contract)
        legacy_stop = transaction_map["Stop and disable the exact legacy Keycloak unit before Quadlet takeover"]
        transaction_index = systemd_block.index(transaction)
        self.assertTrue(validation_index < collision_index < transaction_index)
        self.assertLess(systemd_block.index(ownership), collision_index)
        self.assertEqual(transaction["block"][0]["name"], "Render the transactional Keycloak Pod manifest")
        self.assertLess(transaction["block"].index(stage), transaction["block"].index(legacy_stop))
        self.assertEqual(
            (legacy_stop["ansible.builtin.systemd"]["state"], legacy_stop["ansible.builtin.systemd"]["enabled"]),
            ("stopped", False),
        )
        rescue_source = "\n".join(str(task) for task in transaction["rescue"])
        for contract in (
            "exact pre-transaction Keycloak Pod manifest",
            "transaction-created Keycloak Pod manifest",
            "generated native Keycloak service",
            "native Keycloak inactivity",
            "exact legacy Keycloak service",
        ):
            self.assertIn(contract, rescue_source)
        self.assertIn("Inspect the transactional Keycloak database endpoint", str(transaction["block"]))
        self.assertIn(
            "Require the desired database endpoint before committing Keycloak takeover",
            str(transaction["block"]),
        )
        manifest_render = next(task for task in pod_tasks if task["name"].startswith("Render Keycloak Pod manifest"))
        self.assertIn("not keycloak_deploy_manage_systemd", manifest_render["when"])
        runtime_block = yaml.safe_load((ROOT / "roles/keycloak_deploy/tasks/deploy.yml").read_text(encoding="utf-8"))[
            2
        ]["block"]
        runtime_map = {task["name"]: task for task in runtime_block}
        inspect = runtime_map["Inspect the effective Keycloak environment"]
        self.assertEqual(
            (inspect["no_log"], inspect["ansible.builtin.command"]["argv"][:3]),
            (True, ["podman", "container", "inspect"]),
        )
        self.assertIn("not keycloak_deploy_manage_systemd", inspect["when"])
        verify = runtime_map["Require the desired database endpoint in the active Keycloak pod"]
        self.assertIs(verify["no_log"], True)
        self.assertIn("KC_DB_URL_HOST=", str(verify))
        self.assertIn("KC_DB_URL_PORT=", str(verify))
        source = pod_tasks_path.read_text(encoding="utf-8")
        self.assertNotIn("Ignore kubeplay remove failure", source)
        self.assertNotIn("Ignore kubeplay run failure", source)

    def test_edge_proxy_contract_restricts_forwarded_identity(self) -> None:
        defaults = self._role_defaults("keycloak_deploy")
        self.assertEqual(defaults["keycloak_deploy_proxy_trusted_addresses"], [])
        self.assertEqual(defaults["keycloak_deploy_host_ip"], "127.0.0.1")
        self.assertEqual(defaults["keycloak_deploy_networks"], [])
        self.assertIn("keycloak_deploy_networks", defaults["keycloak_deploy_postgres_networks"])

        template = (ROOT / "roles" / "keycloak_deploy" / "templates" / "keycloak-pod.yml.j2").read_text(
            encoding="utf-8"
        )
        self.assertIn("KC_PROXY_TRUSTED_ADDRESSES", template)
        self.assertIn("keycloak_deploy_proxy_trusted_addresses | join(',')", template)
        tasks = yaml.safe_load(
            (ROOT / "roles" / "keycloak_deploy" / "tasks" / "assert.yml").read_text(encoding="utf-8")
        )
        validation = next(task for task in tasks if task["name"] == "Validate trusted Keycloak proxy address syntax")
        command = validation["ansible.builtin.command"]["argv"]
        self.assertIn("ipaddress.ip_network(sys.argv[1], strict=False)", command[2])
        self.assertEqual(
            (command[3], validation["loop"]), ("{{ item }}", "{{ keycloak_deploy_proxy_trusted_addresses }}")
        )
        self.assertEqual((validation["check_mode"], validation["changed_when"]), (False, False))

    def test_systemd_management_fails_closed_without_systemd_facts(self) -> None:
        for role in ("keycloak_deploy", "postgres_deploy"):
            assertions = (ROOT / "roles" / role / "tasks" / "assert.yml").read_text(encoding="utf-8")
            for contract in (
                f"not {role}_manage_systemd | bool",
                f"{role}_skip_runtime | bool",
                f"{role}_skip_deploy | bool",
            ):
                self.assertIn(contract, assertions)
            with self.subTest(role=role):
                self.assertIn("ansible_facts.get('service_mgr', '')", assertions)

    def test_managed_bridge_database_requires_a_shared_normalized_network(self) -> None:
        assertions = (ROOT / "roles" / "keycloak_deploy" / "tasks" / "assert.yml").read_text(encoding="utf-8")
        defaults = self._role_defaults("keycloak_deploy")
        self.assertEqual(
            (defaults["keycloak_deploy_postgres_port"], defaults["keycloak_deploy_postgres_container_port"]),
            (5432, 5432),
        )
        self.assertGreaterEqual(assertions.count("map('regex_replace', ':.*$', '')"), 2)
        for contract in (
            "not (keycloak_deploy_host_network | bool)",
            "| intersect(",
            "or keycloak_deploy_manage_systemd | bool",
        ):
            self.assertIn(contract, assertions)
        tasks = yaml.safe_load(assertions)
        validation = next(task for task in tasks if task["name"] == "Validate the managed private PostgreSQL endpoint")
        command = validation["ansible.builtin.command"]["argv"]
        self.assertIn("host.is_private and any", command[2])

    def test_quadlet_destroy_fails_closed_until_li220(self) -> None:
        for role, deploy_role in (("keycloak_destroy", "keycloak_deploy"), ("postgres_destroy", "postgres_deploy")):
            defaults = self._role_defaults(role)
            assertions = (ROOT / "roles" / role / "tasks" / "assert.yml").read_text(encoding="utf-8")
            self.assertEqual(
                defaults[f"{role}_manage_systemd"], f"{{{{ {deploy_role}_manage_systemd | default(true) }}}}"
            )
            self.assertIn(f"not ({role}_manage_systemd | bool)", assertions)
            self.assertIn("currently unsupported Quadlet teardown", assertions)


if __name__ == "__main__":
    unittest.main()
