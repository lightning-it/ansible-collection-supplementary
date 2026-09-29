"""Execute PostgreSQL legacy-to-Quadlet transition predicates in isolation."""

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
    def test_native_quadlet_replaces_only_the_exact_legacy_instance(self) -> None:
        if not (Path("/run/.containerenv").exists() or Path("/.dockerenv").exists()):
            result = subprocess.run(  # noqa: S603
                [
                    "/bin/bash",
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
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return

        ansible = shutil.which("ansible-playbook")
        self.assertIsNotNone(ansible, "Run this regression in the pinned Devtools EE")
        block = yaml.safe_load((ROLE / "tasks/systemd.yml").read_text(encoding="utf-8"))[0]["block"]
        task_map = {task["name"]: task for task in block}
        active = task_map["Inspect the exact legacy PostgreSQL unit activity"]
        enabled = task_map["Inspect the exact legacy PostgreSQL unit enablement"]
        validate = task_map["Refuse unknown legacy PostgreSQL lifecycle states"]
        stage = task_map["Stage the native PostgreSQL Quadlet before legacy shutdown"]
        stop = task_map["Stop and disable the exact legacy PostgreSQL unit before Quadlet takeover"]
        manage = task_map["Manage the native PostgreSQL Quadlet service"]

        self.assertEqual(active["ansible.builtin.command"]["argv"][:2], ["systemctl", "is-active"])
        self.assertEqual(enabled["ansible.builtin.command"]["argv"][:2], ["systemctl", "is-enabled"])
        self.assertLess(block.index(validate), block.index(stage))
        self.assertLess(block.index(stage), block.index(stop))
        self.assertLess(block.index(stop), block.index(manage))
        self.assertEqual(manage["vars"]["podman_systemd_networks"], "{{ postgres_deploy_networks }}")
        self.assertFalse((ROLE / "templates/podman-kube@.service.j2").exists())

        cases = (
            ("active", 0, "enabled", 0, ["stage", "stop"], "restarted"),
            ("inactive", 3, "disabled", 1, [], "present"),
            ("inactive", 3, "enabled-runtime", 0, ["stage", "stop"], "restarted"),
            ("unknown", 4, "not-found", 1, [], "present"),
            ("failed", 3, "masked", 1, [], "present"),
            ("error", 1, "error", 1, [], "rejected"),
        )
        for active_state, active_rc, enabled_state, enabled_rc, events, action in cases:
            with self.subTest(active=active_state, enabled=enabled_state), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                fixture = directory / "systemctl"
                fixture.write_text(
                    "#!/bin/sh\n"
                    f"if [ \"$1\" = is-active ]; then printf '%s\\n' '{active_state}'; exit {active_rc}; fi\n"
                    f"if [ \"$1\" = is-enabled ]; then printf '%s\\n' '{enabled_state}'; exit {enabled_rc}; fi\n"
                    "exit 2\n",
                    encoding="utf-8",
                )
                fixture.chmod(0o700)
                event_log = directory / "events"
                action_file = directory / "action"

                executable = [copy.deepcopy(active), copy.deepcopy(enabled)]
                for task in executable:
                    task["ansible.builtin.command"]["argv"][0] = str(fixture)
                executable.append(copy.deepcopy(validate))
                for source, event in ((stage, "stage"), (stop, "stop")):
                    task = {
                        "name": source["name"],
                        "ansible.builtin.lineinfile": {
                            "path": str(event_log),
                            "line": event,
                            "create": True,
                        },
                        "when": source["when"],
                    }
                    executable.append(task)
                executable.extend(
                    [
                        {
                            "name": manage["name"],
                            "ansible.builtin.set_fact": {"observed_action": manage["vars"]["podman_systemd_action"]},
                            "changed_when": False,
                        },
                        {
                            "name": "Persist observed Quadlet action",
                            "ansible.builtin.copy": {
                                "dest": str(action_file),
                                "content": "{{ observed_action }}\n",
                                "mode": "0600",
                            },
                        },
                    ]
                )
                playbook = directory / "probe.yml"
                playbook.write_text(
                    yaml.safe_dump(
                        [
                            {
                                "hosts": "localhost",
                                "gather_facts": False,
                                "vars": {
                                    "postgres_deploy_kubeplay_run": False,
                                    "postgres_deploy_kubeplay_remove": False,
                                    "postgres_deploy_legacy_systemd_name": {"stdout": "example"},
                                },
                                "tasks": executable,
                            }
                        ],
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
                config = directory / "ansible.cfg"
                config.write_text("[defaults]\nretry_files_enabled = False\n", encoding="utf-8")
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
                first = subprocess.run(  # noqa: S603
                    args,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
                if action == "rejected":
                    self.assertNotEqual(first.returncode, 0, first.stdout + first.stderr)
                    self.assertFalse(event_log.exists())
                    self.assertFalse(action_file.exists())
                    continue

                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                observed_events = event_log.read_text(encoding="utf-8").splitlines() if event_log.exists() else []
                self.assertEqual(observed_events, events)
                self.assertEqual(action_file.read_text(encoding="utf-8").strip(), action)

                second = subprocess.run(  # noqa: S603
                    args,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
                self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
                self.assertIn("changed=0", second.stdout)
                observed_events = event_log.read_text(encoding="utf-8").splitlines() if event_log.exists() else []
                self.assertEqual(observed_events, events)


if __name__ == "__main__":
    unittest.main()
