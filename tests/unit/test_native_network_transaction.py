"""Run production Ansible block/rescue/always with isolated fault-injected IO.

This proves transaction ordering and recovery decisions, not Podman readiness,
filesystem permissions or the atomic_path primitive (separate acceptance gates).
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml

if __package__:
    from .test_keycloak_native_migration_plan import NATIVE, fixtures
else:
    from test_keycloak_native_migration_plan import NATIVE, fixtures

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "roles/keycloak_deploy/tasks"

# All effects remain inside a TemporaryDirectory in the offline validator.
ACTION = r"""
from ansible.plugins.action import ActionBase
import hashlib
import json

class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        args = self._task.args
        path = task_vars['fixture_state_path']
        with open(path) as stream:
            state = json.load(stream)
        op, payload = args['op'], args['payload']
        event = op
        if op == 'systemd':
            event += ':' + payload.get('name', 'reload') + ':' + payload.get('state', 'reload')
        elif op == 'write':
            event += ':' + payload['path']
        elif op == 'command':
            event += ':' + ('ready' if 'pg_isready' in payload['argv'] else 'inspect')
        state['trace'].append(event)
        result = {'changed': False}
        failure = state['failure']
        if op == 'systemd':
            if payload.get('state') == 'stopped':
                if failure == 'second-stop' and not state['injected'] and payload['name'] == 'postgres.service':
                    state['injected'] = True
                    state['fault_observed'] = True
                    result.update(failed=True, msg='Injected stop failure')
                else:
                    state['services'][payload['name']] = 'stopped'
            elif payload.get('state') == 'started':
                state['services'][payload['name']] = 'started'
            result['changed'] = True
        elif op == 'write':
            target = payload['path']
            current = state['files'][target]
            if hashlib.sha256(current.encode()).hexdigest() != payload['expected_checksum']:
                result.update(failed=True, msg='Fixture compare-and-swap rejected')
            elif failure == 'write:' + target and not state['injected']:
                state['injected'] = True
                state['fault_observed'] = True
                result.update(failed=True, msg='Injected write failure')
            else:
                state['files'][target] = payload['content']
                state['phase'] = ('original' if payload['content'] == state['original'][target] else 'desired')
                result['changed'] = current != payload['content']
        elif op == 'stat':
            result['stat'] = {'isreg': True, 'islnk': False, 'uid': 0, 'gid': 0,
                              'mode': state['modes'][payload['path']],
                              'checksum': hashlib.sha256(state['files'][payload['path']].encode()).hexdigest()}
        elif op == 'command':
            argv = payload['argv']
            if 'pg_isready' in argv:
                failed = failure == 'postgres-ready' and state['phase'] == 'desired'
                state['fault_observed'] = state['fault_observed'] or failed
                result.update(rc=1 if failed else 0,
                              stdout='fixture readiness')
            elif '--format' in argv:
                result.update(rc=0, stdout=json.dumps(['KC_DB_URL_HOST=postgres', 'KC_DB_URL_PORT=5432']))
            else:
                component = 'postgres' if argv[3] == 'postgres-postgres' else 'keycloak'
                result.update(rc=0, stdout=json.dumps([state['records'][state['phase']][component]]))
        elif op == 'uri':
            failed = failure in ('keycloak-ready', 'external-drift') and state['phase'] == 'desired'
            state['fault_observed'] = state['fault_observed'] or failed
            if failed and failure == 'external-drift':
                state['files']['/fixture/keycloak.kube'] = 'foreign configuration\n'
            result.update(status=503 if failed else 200, failed=failed, msg='Fixture health')
        with open(path, 'w') as stream:
            json.dump(state, stream)
        return result
"""


def instrument(tasks):
    """Keep production control flow, conditions, loops, facts and assertions."""
    result = deepcopy(tasks)
    operations = {
        "ansible.builtin.systemd_service": "systemd",
        "lit.supplementary.atomic_path": "write",
        "ansible.builtin.stat": "stat",
        "ansible.builtin.command": "command",
        "ansible.builtin.uri": "uri",
    }
    for task in result:
        for branch in ("block", "rescue", "always"):
            if branch in task:
                task[branch] = instrument(task[branch])
        for module, operation in operations.items():
            if module in task:
                task["fixture_io"] = {"op": operation, "payload": task.pop(module)}
                if "retries" in task:
                    task["retries"], task["delay"] = 1, 0
    return result


class NativeNetworkTransactionTests(unittest.TestCase):
    def run_case(self, failure="", changed=True):
        components = fixtures()
        records = {}
        for name, component in components.items():
            records[name] = {
                "ImageName": component["image"],
                "Mounts": [
                    {
                        "Source": component["host_data_dir"],
                        "Destination": component["container_data_dir"],
                        "Type": "bind",
                        "RW": True,
                    }
                ],
                "NetworkSettings": {
                    "Networks": {"old-network": {"IPAddress": "192.0.2." + ("12" if name == "keycloak" else "13")}}
                },
                "Config": {"Env": ["KC_DB_URL_HOST=fixture-database", "KC_DB_URL_PORT=5432"]},
            }
        components = NATIVE.capture_original_runtime(components, records)
        desired_records = deepcopy(records)
        for name in components:
            desired_records[name]["NetworkSettings"]["Networks"] = {
                "database": {"IPAddress": "192.0.2." + ("2" if name == "keycloak" else "3")}
            }
        desired_records["keycloak"]["Config"]["Env"] = ["KC_DB_URL_HOST=postgres", "KC_DB_URL_PORT=5432"]
        files = []
        for name in components:
            for kind in ("quadlet", "manifest"):
                content = f"original {name} {kind}\n"
                files.append(
                    {
                        "path": "/fixture/" + name + (".kube" if kind == "quadlet" else ".yml"),
                        "kind": kind,
                        "component": name,
                        "original": content,
                        "desired": f"desired {name} {kind}\n",
                        "checksum": hashlib.sha256(content.encode()).hexdigest(),
                        "mode": "0644" if kind == "quadlet" else "0600",
                        "parent_identities": {},
                    }
                )
        source = yaml.safe_load((TASKS / "native_network_migration.yml").read_text())[0]
        cutover = next(task for task in source["block"] if "rescue" in task)
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "Run in pinned Devtools")
        with tempfile.TemporaryDirectory(prefix="native-transaction-") as temporary:
            directory = Path(temporary)
            plugins = directory / "action_plugins"
            plugins.mkdir()
            (plugins / "fixture_io.py").write_text(ACTION)
            for name in ("native_network_start.yml", "native_network_restore.yml"):
                (directory / name).write_text(yaml.safe_dump(instrument(yaml.safe_load((TASKS / name).read_text()))))
            collection = directory / "collections/ansible_collections/lit/supplementary"
            collection.parent.mkdir(parents=True)
            collection.symlink_to(ROOT, target_is_directory=True)
            state_path = directory / "state.json"
            original = {item["path"]: item["original"] for item in files}
            state_path.write_text(
                json.dumps(
                    {
                        "failure": failure,
                        "injected": False,
                        "fault_observed": False,
                        "trace": [],
                        "phase": "original",
                        "files": original,
                        "original": original,
                        "modes": {item["path"]: item["mode"] for item in files},
                        "services": {"keycloak.service": "started", "postgres.service": "started"},
                        "records": {"original": records, "desired": desired_records},
                    }
                )
            )
            variables = {
                "fixture_state_path": str(state_path),
                "keycloak_deploy_migration_needed": changed,
                "keycloak_deploy_migration_specs": {
                    name: {"unit": name, "pod_name": name, "container_name": name} for name in components
                },
                "keycloak_deploy_migration_components": components,
                "keycloak_deploy_migration_files": files,
                "keycloak_deploy_postgres_pod_name": "postgres",
                "keycloak_deploy_postgres_container_name": "postgres",
                "keycloak_deploy_postgres_container_port": 5432,
                "keycloak_deploy_pod_name": "keycloak",
                "keycloak_deploy_container_name": "keycloak",
                "keycloak_deploy_db_host": "postgres",
                "keycloak_deploy_db_port": 5432,
                "keycloak_deploy_validate_certs": True,
                "keycloak_deploy_health_url_effective": "http://127.0.0.1:9000/health/ready",
                "keycloak_deploy_liveness_url_effective": "http://127.0.0.1:9000/health/live",
            }
            cleanup_assert = {
                "ansible.builtin.assert": {
                    "that": ["keycloak_deploy_migration_components == {}", "keycloak_deploy_migration_files == []"],
                    "quiet": True,
                }
            }
            cleanup_proof = directory / "discarded.json"
            record_cleanup = {
                "ansible.builtin.copy": {
                    "dest": str(cleanup_proof),
                    "mode": "0600",
                    "content": "{{ (keycloak_deploy_migration_components == {} "
                    "and keycloak_deploy_migration_files == []) | bool | to_json }}",
                }
            }
            play = directory / "transaction.yml"
            play.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "gather_facts": False,
                            "vars": variables,
                            "tasks": [
                                {
                                    "no_log": True,
                                    "block": instrument([cutover]),
                                    "always": source["always"] + [cleanup_assert, record_cleanup],
                                }
                            ],
                        }
                    ]
                )
            )
            config = directory / "ansible.cfg"
            config.write_text("[defaults]\nretry_files_enabled=False\n")
            environment = dict(
                os.environ,
                ANSIBLE_CONFIG=str(config),
                ANSIBLE_NOCOLOR="1",
                ANSIBLE_COLLECTIONS_PATH=str(directory / "collections"),
            )
            result = subprocess.run(  # noqa: S603 -- pinned executable and generated local fixture, no shell.
                [executable, "-i", "localhost,", "-c", "local", str(play)],
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
            )
            state = json.loads(state_path.read_text())
            # Failures must remain failures even when recovery succeeds.
            self.assertEqual(result.returncode == 0, not failure, result.stdout + result.stderr)
            self.assertTrue(json.loads(cleanup_proof.read_text()), "Actual always tasks must discard snapshots")
            self.assertEqual(state["fault_observed"], bool(failure), "Reach the exact selected fault boundary")
            if failure != "external-drift":
                expected = (
                    original
                    if failure or not changed
                    else {
                        item["path"]: item["desired"]
                        if item["kind"] == "quadlet" or item["component"] == "keycloak"
                        else item["original"]
                        for item in files
                    }
                )
                self.assertEqual(state["files"], expected)
                self.assertEqual(set(state["services"].values()), {"started"})
            else:
                self.assertEqual(state["files"]["/fixture/keycloak.kube"], "foreign configuration\n")
                self.assertEqual(set(state["services"].values()), {"stopped"})
            return state

    def test_success_stops_pair_before_writes_and_starts_database_first(self):
        state = self.run_case()
        self.assertEqual(state["trace"][:2], ["systemd:keycloak.service:stopped", "systemd:postgres.service:stopped"])
        self.assertLess(
            state["trace"].index("systemd:postgres.service:started"),
            state["trace"].index("systemd:keycloak.service:started"),
        )

    def test_second_stop_and_each_write_restore_original_pair(self):
        for failure in (
            "second-stop",
            "write:/fixture/keycloak.kube",
            "write:/fixture/keycloak.yml",
            "write:/fixture/postgres.kube",
        ):
            with self.subTest(failure=failure):
                self.run_case(failure)

    def test_readiness_failures_restore_pair_and_remain_failed(self):
        for failure in ("postgres-ready", "keycloak-ready"):
            with self.subTest(failure=failure):
                self.run_case(failure)

    def test_external_drift_stays_stopped_without_overwrite(self):
        self.run_case("external-drift")

    def test_unchanged_plan_has_zero_io(self):
        self.assertEqual(self.run_case(changed=False)["trace"], [])


if __name__ == "__main__":
    unittest.main()
