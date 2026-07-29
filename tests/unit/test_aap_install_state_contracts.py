"""Regression tests for the strict AAP clean-install state guard."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]


def task_named(tasks: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """Return one task by its exact name."""
    return next(task for task in tasks if task.get("name") == name)


class AapInstallStateContractsTests(unittest.TestCase):
    """Require clean, installed, and inconsistent states to stay distinct."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tasks = yaml.safe_load(
            (ROOT / "roles/aap_deploy/tasks/05_detect_existing_install.yml").read_text(encoding="utf-8")
        )
        classifier = task_named(cls.tasks, "Classify existing AAP install state")
        cls.classifier = classifier["ansible.builtin.set_fact"]
        cls.jinja = Environment(autoescape=True)
        cls.jinja.filters["bool"] = bool

    def render_state(self, marker_exists: bool, runtime_exists: bool) -> tuple[bool, bool]:
        """Render the role's exact state expressions for one probe result."""
        context = {
            "aap_deploy_install_marker_precheck": {
                "stat": {"exists": marker_exists},
            },
            "aap_deploy_runtime_containers": (["automation-controller"] if runtime_exists else []),
        }

        installed = yaml.safe_load(
            self.jinja.from_string(self.classifier["aap_deploy_existing_install_detected"]).render(context)
        )
        inconsistent = yaml.safe_load(
            self.jinja.from_string(self.classifier["aap_deploy_install_state_inconsistent"]).render(context)
        )
        return installed, inconsistent

    def test_clean_state_proceeds(self) -> None:
        self.assertEqual(self.render_state(False, False), (False, False))

    def test_complete_install_is_detected(self) -> None:
        self.assertEqual(self.render_state(True, True), (True, False))

    def test_both_inconsistent_states_fail_closed(self) -> None:
        for marker_exists, runtime_exists in ((True, False), (False, True)):
            with self.subTest(
                marker_exists=marker_exists,
                runtime_exists=runtime_exists,
            ):
                self.assertEqual(
                    self.render_state(marker_exists, runtime_exists),
                    (False, True),
                )

        rejection = task_named(self.tasks, "Reject inconsistent AAP install state")
        self.assertEqual(
            rejection["ansible.builtin.assert"]["that"],
            ["not (aap_deploy_install_state_inconsistent | bool)"],
        )
        self.assertIn(
            "ansible.containerized_installer.uninstall",
            rejection["ansible.builtin.assert"]["fail_msg"],
        )

    def test_obsolete_detection_modes_are_absent(self) -> None:
        files = (
            ROOT / "roles/aap_deploy/defaults/main.yml",
            ROOT / "roles/aap_deploy/tasks/assert.yml",
            ROOT / "roles/aap_deploy/tasks/05_detect_existing_install.yml",
            ROOT / "roles/aap_deploy/README.md",
        )
        obsolete = (
            "aap_deploy_skip_if_installed",
            "aap_deploy_skip_if_runtime_active",
            "aap_deploy_runtime_probe_all_containers",
            "aap_deploy_runtime_min_matching_containers",
            "aap_deploy_runtime_name_regex",
            "aap_deploy_installer_wait",
            "aap_deploy_installer_async_retries",
            "aap_deploy_installer_async_jid_path",
        )

        for path in files:
            content = path.read_text(encoding="utf-8")
            for variable in obsolete:
                with self.subTest(path=path, variable=variable):
                    self.assertNotIn(variable, content)

    def test_runtime_probe_fails_closed_and_runs_in_check_mode(self) -> None:
        probe = task_named(self.tasks, "List Podman containers for install user")

        self.assertIs(probe["check_mode"], False)
        self.assertNotIn("failed_when", probe)
        self.assertNotIn("ignore_errors", probe)

    def test_installer_always_waits_before_writing_marker(self) -> None:
        tasks = yaml.safe_load((ROOT / "roles/aap_deploy/tasks/40_install.yml").read_text(encoding="utf-8"))
        install_block = task_named(tasks, "Run AAP containerized installer with diagnostics")
        installer = task_named(install_block["block"], "Run native AAP containerized installer")
        marker = task_named(tasks, "Write installation marker")

        self.assertNotEqual(installer["poll"], 0)
        self.assertIs(installer["no_log"], True)
        self.assertNotIn("when", marker)

        assertions = yaml.safe_load((ROOT / "roles/aap_deploy/tasks/assert.yml").read_text(encoding="utf-8"))
        switch_validation = task_named(assertions, "Validate aap_deploy role switches and mode")
        contracts = switch_validation["ansible.builtin.assert"]["that"]
        self.assertIn("aap_deploy_installer_async_timeout | int > 0", contracts)
        self.assertIn("aap_deploy_installer_async_delay | int > 0", contracts)

    def test_secret_inventory_fact_is_not_logged(self) -> None:
        tasks = yaml.safe_load(
            (ROOT / "roles/aap_deploy/tasks/22_build_setup_inventory_vars.yml").read_text(encoding="utf-8")
        )
        secret_fact = task_named(tasks, "Build setup inventory variables")

        self.assertIs(secret_fact["no_log"], True)


if __name__ == "__main__":
    unittest.main()
