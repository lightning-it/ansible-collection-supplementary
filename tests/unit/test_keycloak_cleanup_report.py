"""Execute the shipped JUnit writer with an intentionally unusable remote interpreter."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from scripts import quality_evidence as evidence

ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_PLAYBOOK = shutil.which("ansible-playbook")
if ANSIBLE_PLAYBOOK is None:
    raise RuntimeError("The pinned Ansible test runtime is required")


class CleanupReportTests(unittest.TestCase):
    def exercise(self, failed_case=None, *, source_sha="a" * 40, github_sha="b" * 40):
        source = yaml.safe_load((ROOT / "molecule/shared/keycloak/default-role-cleanup.yml").read_text())
        checks = dict.fromkeys(source[0]["ansible.builtin.set_fact"]["keycloak_cleanup_probe_checks"], True)
        if failed_case is not None:
            checks[failed_case] = False
        report_tasks = [
            task
            for task in source[1]["always"]
            if task["name"]
            in (
                "Create the independent cleanup report directory",
                "Write observed cleanup JUnit results on success or failure",
            )
        ]
        self.assertEqual(len(report_tasks), 2)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            inventory = {
                "all": {
                    "hosts": {
                        "remote_probe": {
                            "ansible_connection": "local",
                            "ansible_python_interpreter": "/unavailable-remote-python",
                        },
                        "localhost": {
                            "ansible_connection": "local",
                            "ansible_python_interpreter": sys.executable,
                        },
                    }
                }
            }
            play = [
                {
                    "hosts": "remote_probe",
                    "gather_facts": False,
                    "vars": {
                        "keycloak_cleanup_probe_scenario": "remote-report-regression",
                        "keycloak_cleanup_probe_junit_dir": str(directory / "junit"),
                        "keycloak_cleanup_probe_checks": checks,
                    },
                    "tasks": report_tasks,
                }
            ]
            (directory / "inventory.yml").write_text(yaml.safe_dump(inventory))
            (directory / "play.yml").write_text(yaml.safe_dump(play))
            (directory / "ansible.cfg").write_text("[defaults]\n")
            environment = {**os.environ, "ANSIBLE_CONFIG": str(directory / "ansible.cfg")}
            environment.pop("QUALITY_SOURCE_SHA", None)
            environment.pop("GITHUB_SHA", None)
            if source_sha is not None:
                environment["QUALITY_SOURCE_SHA"] = source_sha
            if github_sha is not None:
                environment["GITHUB_SHA"] = github_sha
            result = subprocess.run(  # noqa: S603 - execute the shipped writer in a local controlled fixture
                [ANSIBLE_PLAYBOOK, "-i", str(directory / "inventory.yml"), str(directory / "play.yml")],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            # Only the shipped writer and the fixed local fixture produce these bytes.
            report = ET.parse(directory / "junit/remote-report-regression-default-cleanup.xml").getroot()  # noqa: S314
            self.assertEqual(report.get("tests"), str(len(checks)))
            self.assertEqual({case.get("name") for case in report.findall("testcase")}, set(checks))
            parsed = evidence.parse_junit(directory / "junit/remote-report-regression-default-cleanup.xml")
            self.assertEqual(evidence._report_commit(parsed), source_sha or github_sha or "unknown")
            return report

    def test_success_report_is_written_by_the_controller_for_a_remote_target(self):
        report = self.exercise()
        self.assertEqual(report.get("failures"), "0")
        self.assertEqual(report.findall("testcase/failure"), [])

    def test_failed_observation_remains_a_failure_in_the_controller_report(self):
        report = self.exercise("check_mode")
        self.assertEqual(report.get("failures"), "1")
        self.assertIsNotNone(report.find("testcase[@name='check_mode']/failure"))

    def test_report_uses_github_sha_when_no_selected_source_is_available(self):
        self.exercise(source_sha=None)

    def test_missing_source_remains_unknown_instead_of_inventing_commit_evidence(self):
        self.exercise(source_sha=None, github_sha=None)
