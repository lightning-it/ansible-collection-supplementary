"""Regression tests for the AAP Gateway and internal-service boundary."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

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
        defaults = (ROOT / "roles/aap_deploy/defaults/main.yml").read_text(encoding="utf-8")
        cac_defaults = (ROOT / "roles/aap_cac/defaults/main.yml").read_text(encoding="utf-8")
        template = (
            ROOT / "roles/aap_local_execution/templates/aap-local/inventories/group_vars/aaps/aap.yml.j2"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "('https://' ~ aap_fqdn)",
            defaults,
        )
        self.assertIn(
            'aap_deploy_gateway_main_url: "https://{{ aap_fqdn }}"',
            template,
        )
        self.assertNotIn(
            'aap_deploy_gateway_main_url: "https://{{ aap_fqdn }}:8446"',
            template,
        )
        self.assertIn(
            "('https://' ~ aap_fqdn)",
            cac_defaults,
        )
        self.assertIn(
            "aap_fqdn | default('', true) | string | trim | length > 0",
            defaults,
        )
        self.assertIn(
            "aap_fqdn | default('', true) | string | trim | length > 0",
            cac_defaults,
        )
        self.assertNotIn(
            'aap_cac_gateway_hostname: "https://{{ inventory_hostname }}"',
            cac_defaults,
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
            "aap_password\n    | default(\n        aap_gateway_admin_password_effective | default('', true),",
            defaults,
        )
        self.assertNotIn('aap_cac_gateway_password: "{{ aap_password }}"', defaults)
        self.assertIn("ansible.builtin.import_tasks: assert.yml", main)
        self.assertIn("tasks_from: resolve_admin_passwords.yml", assertions)
        self.assertLess(
            assertions.index("Resolve shared AAP admin passwords for CaC authentication"),
            assertions.index("Validate AAP CaC authentication inputs"),
        )

    def test_cac_organization_default_is_loop_safe(self) -> None:
        defaults = (ROOT / "roles/aap_cac/defaults/main.yml").read_text(encoding="utf-8")
        assertions = (ROOT / "roles/aap_cac/tasks/assert.yml").read_text(encoding="utf-8")

        self.assertIn("aap_cac_controller_organizations: []", defaults)
        self.assertIn(
            "Validate AAP CaC organization collection input",
            assertions,
        )
        self.assertIn(
            "(aap_cac_controller_organizations | type_debug) == 'list'",
            assertions,
        )

    def test_cac_certificate_validation_default_is_not_recursive(self) -> None:
        defaults = (ROOT / "roles/aap_cac/defaults/main.yml").read_text(encoding="utf-8")

        self.assertIn("aap_cac_gateway_validate_certs: true", defaults)
        self.assertNotIn(
            'aap_cac_gateway_validate_certs: "{{ aap_validate_certs | default(true) }}"',
            defaults,
        )

    def test_cac_gateway_and_hub_tasksets_receive_canonical_auth(self) -> None:
        gateway_tasksets = (
            "cac_10_gateway_settings.yml",
            "cac_12_aap_users.yml",
            "cac_13_aap_teams.yml",
            "cac_14_gateway_role_user_assignments.yml",
        )
        hub_tasksets = (
            "cac_30_hub_collection_remotes.yml",
            "cac_31_hub_collection_repositories.yml",
            "cac_32_hub_collection_repository_sync.yml",
            "cac_33_hub_group_roles.yml",
        )
        common_contract = (
            'aap_hostname: "{{ aap_cac_gateway_hostname }}"',
            'aap_username: "{{ aap_cac_gateway_username }}"',
            'aap_validate_certs: "{{ aap_cac_gateway_validate_certs | bool }}"',
        )

        for filename in gateway_tasksets:
            content = (ROOT / "roles/aap_cac/tasks" / filename).read_text(encoding="utf-8")
            with self.subTest(taskset=filename):
                for contract in common_contract:
                    self.assertIn(contract, content)
                self.assertIn(
                    'aap_password: "{{ aap_cac_gateway_password_effective }}"',
                    content,
                )
                self.assertIn('aap_token: "{{ aap_cac_auth_token }}"', content)

        for filename in hub_tasksets:
            content = (ROOT / "roles/aap_cac/tasks" / filename).read_text(encoding="utf-8")
            with self.subTest(taskset=filename):
                for contract in common_contract:
                    self.assertIn(contract, content)
                self.assertIn(
                    'aap_password: "{{ aap_cac_hub_password_effective }}"',
                    content,
                )

    def test_complete_cac_example_populates_every_dispatched_resource(self) -> None:
        example = yaml.safe_load((ROOT / "examples/aap-cac.yml").read_text(encoding="utf-8"))
        expected_inputs = {
            "aap_cac_controller_organizations",
            "aap_user_accounts",
            "aap_teams",
            "gateway_role_user_assignments",
            "gateway_settings",
            "controller_settings",
            "controller_credential_types",
            "controller_labels",
            "controller_credentials",
            "controller_projects",
            "controller_instance_groups",
            "controller_inventories",
            "controller_inventory_sources",
            "controller_templates",
            "aap_cac_hub_collection_remotes",
            "aap_cac_hub_collection_repositories",
            "aap_cac_hub_group_roles",
            "controller_bulk_hosts",
            "controller_hosts",
            "controller_groups",
            "controller_instances",
            "controller_ad_hoc_commands",
            "controller_ad_hoc_commands_cancel",
            "controller_bulk_launch_jobs",
            "controller_launch_jobs",
            "controller_cancel_jobs",
            "controller_workflows",
            "controller_workflow_launch_jobs",
            "controller_applications",
            "controller_credential_input_sources",
            "controller_configuration_dispatcher_roles",
            "controller_execution_environments",
            "operation_translate",
            "controller_notifications",
            "controller_configuration_object_diff_tasks",
            "controller_roles",
            "controller_schedules",
            "ee_list",
            "output_path",
            "input_tag",
            "dir_orgs_vars",
            "orgs",
            "aap_cac_controller_license_manifest_remote_src",
        }

        self.assertTrue(expected_inputs.issubset(example))
        for name in expected_inputs:
            with self.subTest(variable=name):
                self.assertNotIn(example[name], (None, "", [], {}))


if __name__ == "__main__":
    unittest.main()
