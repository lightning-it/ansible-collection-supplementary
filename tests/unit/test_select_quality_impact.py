from __future__ import annotations

import argparse
import importlib.util
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
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class SelectQualityImpactTests(unittest.TestCase):
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

    def test_unregistered_role_and_documentation_skip_protected_profiles(self) -> None:
        result = SELECTOR.select(
            arguments(
                changed_file=[
                    "roles/nginx_config/tasks/main.yml",
                    "docs/development/nginx.md",
                ]
            )
        )

        self.assertFalse(result["keycloak_required"])
        self.assertEqual(result["affected_files"], [])

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
