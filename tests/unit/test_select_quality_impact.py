from __future__ import annotations

import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[2] / "scripts" / "select-quality-impact.py"
REGISTRY_PATH = Path(__file__).parents[2] / "meta" / "quality-impact.yml"
SPEC = importlib.util.spec_from_file_location("select_quality_impact", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
SELECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTOR)


def arguments(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "event_name": "pull_request",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "base_ref": "develop",
        "head_ref": "feature/example",
        "execution_mode": "",
        "registry": str(REGISTRY_PATH),
        "changed_file": [],
        "base_dependency_inventory": "",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class SelectQualityImpactTests(unittest.TestCase):
    def _base_inventory(self, replacement: tuple[str, str]) -> str:
        before, after = replacement
        inventory = (Path(__file__).parents[2] / "meta" / "source-dependencies.yml").read_text(encoding="utf-8")
        self.assertIn(before, inventory)
        temporary = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        self.addCleanup(lambda: Path(temporary.name).unlink(missing_ok=True))
        temporary.write(inventory.replace(before, after, 1))
        temporary.close()
        return temporary.name

    def _registry_fixture(self) -> str:
        temporary = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        self.addCleanup(lambda: Path(temporary.name).unlink(missing_ok=True))
        temporary.write(
            """---
schema_version: 2
safe_fast_lane_path_prefixes: []
families:
  fast:
    profiles: [tiny]
    path_prefixes: [roles/fast/]
  central-heavy:
    profiles: [heavy]
    path_prefixes: [roles/heavy/]
  central-acceptance:
    profiles: [heavy, application_acceptance]
    path_prefixes: [roles/acceptance/]
"""
        )
        temporary.close()
        return temporary.name

    def test_keycloak_role_requires_every_keycloak_profile(self) -> None:
        result = SELECTOR.select(arguments(changed_file=["roles/keycloak_deploy/tasks/main.yml"]))

        self.assertTrue(result["keycloak_required"])
        self.assertEqual(
            result["profiles"],
            {"tiny": True, "heavy": True, "application_acceptance": True},
        )

    def test_samba_and_postgres_dependencies_require_keycloak_profiles(self) -> None:
        for path in (
            "roles/samba_deploy/tasks/main.yml",
            "roles/postgres_deploy/tasks/main.yml",
            "roles/postgres_backup_restore/tasks/main.yml",
        ):
            with self.subTest(path=path):
                result = SELECTOR.select(arguments(changed_file=[path]))
                self.assertTrue(result["keycloak_required"])

    def test_unregistered_role_fails_closed_only_to_tiny(self) -> None:
        result = SELECTOR.select(
            arguments(
                changed_file=[
                    "roles/nginx_config/tasks/main.yml",
                    "docs/development/nginx.md",
                ]
            )
        )

        self.assertFalse(result["keycloak_required"])
        self.assertTrue(result["unknown_impact"])
        self.assertEqual(
            {"tiny": True, "heavy": False, "application_acceptance": False},
            result["profiles"],
        )
        self.assertEqual(result["affected_files"], [])

    def test_pr_545_rsyslog_dependency_update_cannot_select_keycloak_profiles(self) -> None:
        base_inventory = self._base_inventory(
            (
                "docker.io/rsyslog/syslog_appliance_alpine:latest@sha256:"
                "c0dd7cad9ff3234967ff59879590175b7590e8a5f5621ec49a85aff546b44a3b",
                "docker.io/rsyslog/syslog_appliance_alpine:latest@sha256:"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        )
        result = SELECTOR.select(
            arguments(
                changed_file=[
                    "meta/source-dependencies.yml",
                    "roles/rsyslog_deploy/defaults/main.yml",
                    "roles/rsyslog_upgrade/defaults/main.yml",
                ],
                base_dependency_inventory=base_inventory,
            )
        )

        self.assertEqual(
            {"tiny": True, "heavy": False, "application_acceptance": False},
            result["profiles"],
        )
        self.assertFalse(result["keycloak_required"])
        self.assertIn("container_images:docker.io/rsyslog/syslog_appliance_alpine:latest", result["dependency_keys"])
        self.assertEqual(
            [
                "roles/rsyslog_deploy/defaults/main.yml",
                "roles/rsyslog_upgrade/defaults/main.yml",
            ],
            result["affected_files"],
        )

    def test_rsyslog_dependency_digest_alone_selects_only_tiny(self) -> None:
        base_inventory = self._base_inventory(
            (
                "docker.io/rsyslog/syslog_appliance_alpine:latest@sha256:"
                "c0dd7cad9ff3234967ff59879590175b7590e8a5f5621ec49a85aff546b44a3b",
                "docker.io/rsyslog/syslog_appliance_alpine:latest@sha256:"
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        )
        result = SELECTOR.select(
            arguments(
                changed_file=["meta/source-dependencies.yml"],
                base_dependency_inventory=base_inventory,
            )
        )

        self.assertEqual(
            {"tiny": True, "heavy": False, "application_acceptance": False},
            result["profiles"],
        )
        self.assertFalse(result["runtime_evidence_required"])

    def test_dependency_location_move_keeps_the_old_protected_impact(self) -> None:
        base_inventory = self._base_inventory(
            (
                '      - "roles/rsyslog_deploy/defaults/main.yml"\n'
                '      - "roles/rsyslog_upgrade/defaults/main.yml"',
                '      - "roles/keycloak_deploy/defaults/main.yml"\n'
                '      - "roles/rsyslog_upgrade/defaults/main.yml"',
            )
        )
        result = SELECTOR.select(
            arguments(
                changed_file=["meta/source-dependencies.yml"],
                base_dependency_inventory=base_inventory,
            )
        )

        self.assertEqual(
            {"tiny": True, "heavy": True, "application_acceptance": True},
            result["profiles"],
        )
        self.assertIn("roles/keycloak_deploy/defaults/main.yml", result["affected_files"])

    def test_keycloak_dependency_digest_selects_all_declared_profiles(self) -> None:
        base_inventory = self._base_inventory(
            (
                "quay.io/keycloak/keycloak:26.7.0@sha256:"
                "0f198be292568439d700cdbfb893e69a6009bb43a94a06a945b1d3d506c76b13",
                "quay.io/keycloak/keycloak:26.7.0@sha256:"
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            )
        )
        result = SELECTOR.select(
            arguments(
                changed_file=["meta/source-dependencies.yml"],
                base_dependency_inventory=base_inventory,
            )
        )

        self.assertEqual(
            {"tiny": True, "heavy": True, "application_acceptance": True},
            result["profiles"],
        )
        self.assertTrue(result["keycloak_required"])

    def test_registry_can_select_each_profile_independently(self) -> None:
        registry = self._registry_fixture()
        expected = {
            "roles/fast/defaults/main.yml": {"tiny": True, "heavy": False, "application_acceptance": False},
            "roles/heavy/defaults/main.yml": {"tiny": False, "heavy": True, "application_acceptance": False},
            "roles/acceptance/defaults/main.yml": {"tiny": False, "heavy": True, "application_acceptance": True},
        }

        for path, profiles in expected.items():
            with self.subTest(path=path):
                result = SELECTOR.select(arguments(registry=registry, changed_file=[path]))
                self.assertEqual(profiles, result["profiles"])

    def test_central_profiles_require_runtime_evidence_without_tiny(self) -> None:
        registry = self._registry_fixture()
        for path in ("roles/heavy/defaults/main.yml", "roles/acceptance/defaults/main.yml"):
            with self.subTest(path=path):
                result = SELECTOR.select(arguments(registry=registry, changed_file=[path]))
                self.assertFalse(result["profiles"]["tiny"])
                self.assertTrue(result["runtime_evidence_required"])

    def test_registry_rejects_acceptance_without_heavy(self) -> None:
        temporary = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        self.addCleanup(lambda: Path(temporary.name).unlink(missing_ok=True))
        temporary.write(
            """---
schema_version: 2
safe_fast_lane_path_prefixes: []
families:
  invalid:
    profiles: [application_acceptance]
    path_prefixes: [roles/invalid/]
"""
        )
        temporary.close()

        with self.assertRaisesRegex(ValueError, "requires heavy when it declares application_acceptance"):
            SELECTOR.select(arguments(registry=temporary.name, changed_file=["roles/invalid/tasks/main.yml"]))

    def test_unreadable_dependency_inventory_only_selects_tiny(self) -> None:
        result = SELECTOR.select(
            arguments(
                changed_file=["meta/source-dependencies.yml"],
                base_dependency_inventory="/definitely/not/a/source-dependencies.yml",
            )
        )

        self.assertTrue(result["unknown_impact"])
        self.assertEqual(
            {"tiny": True, "heavy": False, "application_acceptance": False},
            result["profiles"],
        )

    def test_develop_to_main_promotion_runs_complete_registered_matrix(self) -> None:
        result = SELECTOR.select(arguments(base_ref="main", head_ref="develop", changed_file=["README.md"]))

        self.assertTrue(result["full_matrix"])
        self.assertTrue(result["keycloak_required"])

    def test_manual_and_main_validation_run_complete_registered_matrix(self) -> None:
        for event_name, head_ref in (
            ("workflow_dispatch", "refs/heads/develop"),
            ("push", "refs/heads/main"),
        ):
            with self.subTest(event_name=event_name, head_ref=head_ref):
                result = SELECTOR.select(
                    arguments(
                        event_name=event_name,
                        head_ref=head_ref,
                        changed_file=["README.md"],
                    )
                )
                self.assertTrue(result["full_matrix"])

    def test_unknown_push_base_fails_closed(self) -> None:
        result = SELECTOR.select(
            arguments(
                event_name="push",
                base_sha="0" * 40,
                head_ref="refs/heads/develop",
                changed_file=[],
            )
        )

        self.assertTrue(result["full_matrix"])
        self.assertTrue(result["keycloak_required"])

    def test_rejects_unsafe_changed_path(self) -> None:
        with self.assertRaises(ValueError):
            SELECTOR.select(arguments(changed_file=["../outside.yml"]))
