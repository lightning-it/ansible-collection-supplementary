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


if __name__ == "__main__":
    unittest.main()
