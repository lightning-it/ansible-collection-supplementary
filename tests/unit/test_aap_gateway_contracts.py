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

    def test_service_backed_sso_uses_supported_eda_extra_settings(self) -> None:
        inventory_vars = (ROOT / "roles/aap_deploy/tasks/22_build_setup_inventory_vars.yml").read_text(encoding="utf-8")

        self.assertIn("eda_extra_settings:", inventory_vars)
        self.assertIn("aap_deploy_eda_extra_settings", inventory_vars)
        self.assertNotIn("settings.yaml.j2", inventory_vars)

        defaults = (ROOT / "roles/aap_deploy/defaults/main.yml").read_text(encoding="utf-8")
        self.assertIn("'setting': 'ENABLE_SERVICE_BACKED_SSO'", defaults)
        self.assertIn(
            "aap_deploy_eda_service_backed_sso_enabled | bool",
            defaults,
        )

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


if __name__ == "__main__":
    unittest.main()
