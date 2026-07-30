"""Regression tests for the AAP Gateway and internal-service boundary."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class AapGatewayContractsTests(unittest.TestCase):
    """Keep vendor Gateway routing intact during installer preparation."""

    def test_prepared_installer_bundle_is_not_customized(self) -> None:
        role_main = (ROOT / "roles/aap_deploy/tasks/main.yml").read_text(encoding="utf-8")
        customizer = ROOT / "roles/aap_deploy/tasks/25_customize_prepared_installer.yml"

        self.assertFalse(customizer.exists())
        self.assertNotIn("25_customize_prepared_installer.yml", role_main)
        self.assertNotIn("Customize prepared installer workspace", role_main)

    def test_removed_internal_service_overrides_are_not_public_role_inputs(self) -> None:
        files = (
            ROOT / "roles/aap_deploy/defaults/main.yml",
            ROOT / "roles/aap_deploy/tasks/assert.yml",
            ROOT / "roles/aap_deploy/tasks/22_build_setup_inventory_vars.yml",
            ROOT / "roles/aap_local_execution/templates/aap-local/inventories/group_vars/aaps/aap.yml.j2",
        )
        forbidden = (
            "aap_deploy_hub_container_registry_url",
            "aap_deploy_hub_upload_readiness_url",
            "aap_deploy_eda_api_url",
            "aap_deploy_manage_hub_registry_trust",
            "aap_deploy_hub_seed_execution_environment_images",
            "hub_container_registry_url",
            "hub_upload_readiness_url",
            "automationeda_api_url",
            "hub_seed_execution_environment_images",
        )

        for path in files:
            content = path.read_text(encoding="utf-8")
            for token in forbidden:
                with self.subTest(path=path, token=token):
                    self.assertNotIn(token, content)

    def test_eda_settings_remain_owned_by_upstream_installer(self) -> None:
        inventory_vars = (ROOT / "roles/aap_deploy/tasks/22_build_setup_inventory_vars.yml").read_text(encoding="utf-8")
        defaults = (ROOT / "roles/aap_deploy/defaults/main.yml").read_text(encoding="utf-8")

        self.assertIn("automationeda: {}", inventory_vars)
        self.assertNotIn("eda_extra_settings", inventory_vars)
        self.assertNotIn("aap_deploy_eda_extra_settings", defaults)
        self.assertNotIn("aap_deploy_eda_service_backed_sso_enabled", defaults)
        self.assertNotIn("settings.yaml.j2", inventory_vars)

    def test_local_execution_uses_public_envoy_url(self) -> None:
        template = (
            ROOT / "roles/aap_local_execution/templates/aap-local/inventories/group_vars/aaps/aap.yml.j2"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'aap_deploy_gateway_main_url: "https://{{ aap_fqdn }}"',
            template,
        )
        self.assertNotIn(
            'aap_deploy_gateway_main_url: "https://{{ aap_fqdn }}:8446"',
            template,
        )

    def test_partial_install_autoreset_is_not_supported(self) -> None:
        files = (
            ROOT / "roles/aap_deploy/defaults/main.yml",
            ROOT / "roles/aap_deploy/tasks/assert.yml",
            ROOT / "roles/aap_deploy/tasks/05_detect_existing_install.yml",
            ROOT / "roles/aap_host_prepare/tasks/main.yml",
            ROOT / "roles/aap_local_execution/templates/aap-local/inventories/group_vars/aaps/aap.yml.j2",
            ROOT / "roles/aap_deploy/README.md",
        )

        for path in files:
            with self.subTest(path=path):
                self.assertNotIn(
                    "aap_deploy_reset_partial_install",
                    path.read_text(encoding="utf-8"),
                )

    def test_registry_trust_remains_owned_by_upstream_installer(self) -> None:
        role_main = (ROOT / "roles/aap_deploy/tasks/main.yml").read_text(encoding="utf-8")
        defaults = (ROOT / "roles/aap_deploy/defaults/main.yml").read_text(encoding="utf-8")

        self.assertFalse((ROOT / "roles/aap_deploy/tasks/16_hub_registry_trust.yml").exists())
        self.assertNotIn("16_hub_registry_trust.yml", role_main)
        self.assertNotIn("aap_deploy_manage_hub_registry_trust", defaults)

    def test_supported_installer_version_remains_explicit(self) -> None:
        assertions = (ROOT / "roles/aap_deploy/tasks/assert.yml").read_text(encoding="utf-8")

        self.assertIn(
            "aap_deploy_setup_download_version == '2.7'",
            assertions,
        )

    def test_cac_authentication_uses_shared_gateway_password_contract(self) -> None:
        defaults = (ROOT / "roles/aap_cac/defaults/main.yml").read_text(encoding="utf-8")
        main = (ROOT / "roles/aap_cac/tasks/main.yml").read_text(encoding="utf-8")
        assertions = (ROOT / "roles/aap_cac/tasks/assert.yml").read_text(encoding="utf-8")

        self.assertIn("aap_username | default('admin', true)", defaults)
        self.assertIn("aap_gateway_admin_password_effective", defaults)
        self.assertIn(
            "aap_password\n"
            "    | default(\n"
            "        aap_gateway_admin_password_effective | default('', true),",
            defaults,
        )
        self.assertNotIn('aap_cac_gateway_password: "{{ aap_password }}"', defaults)
        self.assertIn("ansible.builtin.import_tasks: assert.yml", main)
        self.assertIn("tasks_from: resolve_admin_passwords.yml", assertions)
        self.assertLess(
            assertions.index("Resolve shared AAP admin passwords for CaC authentication"),
            assertions.index("Validate AAP CaC authentication inputs"),
        )


if __name__ == "__main__":
    unittest.main()
