"""Execute the real discovery/fallback tasks with an isolated systemctl fixture."""

from __future__ import annotations

import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles" / "postgres_deploy"


class PostgresSystemdPreservationTests(unittest.TestCase):
    def test_systemd_discovery_and_fallback(self) -> None:
        if not (Path("/run/.containerenv").exists() or Path("/.dockerenv").exists()):
            # The ordinary pre-commit unit hook is host-side. Keep actual
            # Ansible execution in the same pinned offline EE as role gates.
            result = subprocess.run(  # noqa: S603
                [
                    "bash",
                    str(ROOT / "scripts/wunder-devtools-ee.sh"),
                    "env",
                    "LC_ALL=C.UTF-8",
                    "LANG=C.UTF-8",
                    "python3",
                    "/workspace/tests/unit/test_postgres_systemd_preservation.py",
                    "-v",
                ],
                cwd=ROOT,
                env=dict(os.environ, WUNDER_DEVTOOLS_RUN_AS_HOST_UID="1"),
                capture_output=True,
                text=True,
                timeout=300,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return
        ansible = shutil.which("ansible-playbook")
        self.assertIsNotNone(ansible, "Run this regression in the pinned Devtools EE")
        block = yaml.safe_load((ROLE / "tasks/systemd.yml").read_text())[0]["block"]
        probe = next(task for task in block if task.get("register") == "postgres_deploy_systemd_load_state")
        install = next(task for task in block if "ansible.builtin.template" in task)
        self.assertEqual(
            probe["ansible.builtin.command"]["argv"][:4], ["systemctl", "show", "--property=LoadState", "--value"]
        )
        self.assertIs(probe["changed_when"], False)
        self.assertIs(install["ansible.builtin.template"]["force"], False)
        cases = (
            ("loaded", 0, False, True, False),
            ("loaded", 0, True, True, False),
            ("not-found", 0, False, True, True),
            ("not-found", 0, True, True, False),
            ("masked", 0, False, False, False),
            ("error", 0, False, False, False),
            ("", 0, False, False, False),
            ("loaded\nnot-found", 0, False, False, False),
            ("not-found", 1, False, False, False),
        )
        for state, rc, existing, success, creates in cases:
            with self.subTest(state=state, rc=rc, existing=existing), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                fixture = directory / "systemctl"
                fixture.write_text(f"#!/bin/sh\nprintf '%s\\n' '{state}'\nexit {rc}\n")
                fixture.chmod(0o700)
                destination = directory / "podman-kube@.service"
                original = "administrator-owned unit\n"
                if existing:
                    destination.write_text(original)
                tasks = copy.deepcopy([probe, install])
                tasks[0]["ansible.builtin.command"]["argv"][0] = str(fixture)
                tasks[1]["ansible.builtin.template"]["src"] = str(ROLE / "templates/podman-kube@.service.j2")
                tasks[1]["ansible.builtin.template"]["dest"] = str(destination)
                playbook = directory / "probe.yml"
                playbook.write_text(
                    yaml.safe_dump(
                        [
                            {
                                "hosts": "localhost",
                                "gather_facts": False,
                                "vars": {"postgres_deploy_systemd_name": {"stdout": "example"}},
                                "tasks": tasks,
                            }
                        ]
                    )
                )
                config = directory / "ansible.cfg"
                config.write_text("[defaults]\nretry_files_enabled = False\n")
                env = dict(
                    os.environ,
                    ANSIBLE_CONFIG=str(config),
                    ANSIBLE_LOCAL_TEMP=str(directory / "tmp"),
                    ANSIBLE_NOCOLOR="1",
                    ANSIBLE_STDOUT_CALLBACK="default",
                    LC_ALL="C.UTF-8",
                    LANG="C.UTF-8",
                )
                args = [str(ansible), "-i", "localhost,", "-c", "local", str(playbook)]
                result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=45)  # noqa: S603
                self.assertIn("TASK [" + probe["name"] + "]", result.stdout, result.stdout + result.stderr)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                self.assertEqual(destination.exists(), existing or creates)
                if existing:
                    self.assertEqual(destination.read_text(), original)
                elif creates:
                    self.assertEqual(destination.read_text(), (ROLE / "templates/podman-kube@.service.j2").read_text())
                    repeated = subprocess.run(args, env=env, capture_output=True, text=True, timeout=45)  # noqa: S603
                    self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                    self.assertIn("changed=0", repeated.stdout)


if __name__ == "__main__":
    unittest.main()
