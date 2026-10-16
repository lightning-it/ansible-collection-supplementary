"""Canonical role templates versus migration serialization, without credentials."""

import base64
import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import jinja2
import yaml
from ansible.errors import AnsibleFilterError
from ansible.plugins.filter.core import to_nice_yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("native_manifest", ROOT / "plugins/filter/native_manifest.py")
FILTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILTER)


def canonical_context(component):
    prefix = component + "_deploy_"
    values = {
        "pod_name": component,
        "container_name": component,
        "image": "example.invalid/" + component + "@sha256:" + "1" * 64,
        "host_network": False,
        "port": 8080 if component == "keycloak" else 5432,
        "container_port": 5432,
        "management_port": 9000,
        "host_ip": "127.0.0.1",
        "start_command": "start",
        "extra_start_args": [],
        "db_vendor": "postgres",
        "db_host": "postgres",
        "db_port": 5432,
        "db_name": "fixture",
        "db_user": "fixture",
        "db_password_effective": "SYNTHETIC-NOT-A-CREDENTIAL",
        "admin_user": "fixture",
        "admin_password_effective": "SYNTHETIC-NOT-A-CREDENTIAL",
        "hostname": "",
        "proxy_headers": "",
        "http_relative_path": "",
        "env_extra": {},
        "container_data_dir": "/data",
        "host_data_dir": "/srv/fixture",
    }
    return {prefix + key: value for key, value in values.items()}


def canonical_manifest(component):
    environment = jinja2.Environment(trim_blocks=True, autoescape=False)  # noqa: S701 -- match Ansible YAML, not HTML.
    environment.filters["bool"] = bool
    template = ROOT / "roles" / (component + "_deploy") / "templates" / (component + "-pod.yml.j2")
    return environment.from_string(template.read_text()).render(canonical_context(component))


class NativeManifestReconciliationTests(unittest.TestCase):
    def test_actual_snapshot_rejects_ambiguous_bytes_before_conversion(self):
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "Run inside pinned Devtools")
        source = yaml.safe_load((ROOT / "roles/keycloak_deploy/tasks/native_network_snapshot.yml").read_text())
        selected = deepcopy(source[-2:])
        self.assertIn("native_manifest_equal", str(selected[0]))
        selected[1]["no_log"] = True
        valid = canonical_manifest("keycloak")
        cases = (
            valid,
            "kind: Pod\nspec: {}\nspec: {secret-canary: bad}\n",
            "kind: Pod\nspec:\n  containers: []\n  containers: []\n",
            "secret-canary: [",
        )
        for index, content in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary)
                collection = target / "collections/ansible_collections/lit/supplementary"
                (collection / "plugins/filter").mkdir(parents=True)
                shutil.copy2(ROOT / "plugins/filter/native_manifest.py", collection / "plugins/filter")
                values = {
                    "keycloak_deploy_migration_component": "keycloak",
                    "keycloak_deploy_migration_components": {},
                    "keycloak_deploy_migration_specs": {"keycloak": {}},
                    "keycloak_deploy_migration_quadlet_read": {"content": base64.b64encode(b"fixture").decode()},
                    "keycloak_deploy_migration_manifest_read": {"content": base64.b64encode(content.encode()).decode()},
                }
                play = target / "play.yml"
                play.write_text(
                    yaml.safe_dump([{"hosts": "localhost", "gather_facts": False, "vars": values, "tasks": selected}])
                )
                result = subprocess.run(  # noqa: S603 -- resolved Ansible executable and generated local fixture, no shell.
                    [executable, "-i", "localhost,", "-c", "local", str(play)],
                    env=dict(os.environ, ANSIBLE_COLLECTIONS_PATH=str(target / "collections")),
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                output = result.stdout + result.stderr
                self.assertNotIn("secret-canary", output)
                self.assertEqual(result.returncode == 0, index == 0, output)

    def test_actual_ansible_preview_render_permissions_and_lifecycle_selection(self):
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "Run inside pinned Devtools")
        for component in ("keycloak", "postgres"):
            prefix = component + "_deploy_"
            source = yaml.safe_load((ROOT / "roles" / (component + "_deploy") / "tasks/systemd.yml").read_text())
            transaction = next(task for task in source[0]["block"] if task.get("rescue"))["block"]
            by_name = {task["name"]: task for task in transaction}
            label = "Keycloak" if component == "keycloak" else "PostgreSQL"
            selected = [
                deepcopy(by_name["Privately render the desired " + label + " manifest for comparison"]),
                deepcopy(by_name["Preview transactional " + label + " Pod manifest drift"]),
                deepcopy(by_name["Stop the exact active native " + label + " unit before manifest replacement"]),
                deepcopy(by_name["Render the transactional " + label + " Pod manifest"]),
                deepcopy(by_name["Preserve equal " + label + " manifest bytes and reconcile private permissions"]),
            ]
            # Only lifecycle I/O is instrumented; actual when expressions and
            # lookup, comparison, template/file modules and registers execute.
            selected[2].pop("ansible.builtin.systemd")
            selected[2]["ansible.builtin.set_fact"] = {"fixture_stopped": True}
            manage = by_name["Manage the native " + label + " Quadlet service"]
            selected.append(
                {
                    "name": "Observe actual service action",
                    "ansible.builtin.set_fact": {"fixture_action": manage["vars"]["podman_systemd_action"]},
                }
            )
            for task in selected[3:5]:
                module = task.get("ansible.builtin.template", task.get("ansible.builtin.file"))
                module["owner"], module["group"] = os.geteuid(), os.getegid()
            for drift in ("equal", "changed", "invalid"):
                with self.subTest(component=component, drift=drift), tempfile.TemporaryDirectory() as temporary:
                    target = Path(temporary)
                    collection = target / "collections/ansible_collections/lit/supplementary"
                    role = collection / "roles" / (component + "_deploy")
                    (role / "tasks").mkdir(parents=True)
                    (role / "templates").mkdir()
                    shutil.copytree(ROOT / "roles" / (component + "_deploy") / "defaults", role / "defaults")
                    (collection / "plugins/filter").mkdir(parents=True)
                    shutil.copy2(ROOT / "plugins/filter/native_manifest.py", collection / "plugins/filter")
                    shutil.copy2(
                        ROOT / "roles" / (component + "_deploy") / "templates" / (component + "-pod.yml.j2"),
                        role / "templates",
                    )
                    (role / "tasks/main.yml").write_text(yaml.safe_dump(selected))
                    document = yaml.safe_load(canonical_manifest(component))
                    if drift == "changed":
                        document["spec"]["containers"][0]["env"][0]["value"] = "different"
                    original = to_nice_yaml(document) if drift != "invalid" else "secret-canary: ["
                    manifest = target / "pod.yml"
                    manifest.write_text(original)
                    manifest.chmod(0o640)
                    values = canonical_context(component) | {
                        prefix + "pod_manifest_path": str(manifest),
                        prefix + "original_manifest_file": {"stat": {"exists": True}},
                        prefix + "original_manifest_read": {"content": base64.b64encode(original.encode()).decode()},
                        prefix + "native_systemd_active": {"stdout": "active"},
                        prefix + "legacy_systemd_active": {"stdout": "inactive"},
                        prefix + "legacy_systemd_enabled": {"stdout": "disabled"},
                        prefix + "systemd_unit_name": "fixture",
                        prefix + "systemd_scope": "system",
                        "fixture_stopped": False,
                    }
                    tasks = [{"ansible.builtin.include_role": {"name": "lit.supplementary." + component + "_deploy"}}]
                    if drift != "invalid":
                        tasks.append(
                            {
                                "ansible.builtin.assert": {
                                    "that": [
                                        "fixture_stopped == " + ("true" if drift == "changed" else "false"),
                                        "fixture_action == '"
                                        + ("restarted" if drift == "changed" else "present")
                                        + "'",
                                    ],
                                    "quiet": True,
                                }
                            }
                        )
                    play = target / "play.yml"
                    play.write_text(
                        yaml.safe_dump([{"hosts": "localhost", "gather_facts": False, "vars": values, "tasks": tasks}])
                    )
                    environment = dict(
                        os.environ, ANSIBLE_COLLECTIONS_PATH=str(target / "collections"), ANSIBLE_NOCOLOR="1"
                    )
                    result = subprocess.run(  # noqa: S603 -- resolved Ansible executable and generated local fixture, no shell.
                        [executable, "-i", "localhost,", "-c", "local", str(play)],
                        env=environment,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=30,
                    )
                    output = result.stdout + result.stderr
                    self.assertNotIn("secret-canary", output)
                    if drift == "invalid":
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(manifest.read_text(), original)
                    else:
                        self.assertEqual(result.returncode, 0, output)
                        self.assertEqual(manifest.stat().st_mode & 0o777, 0o600)
                        if drift == "equal":
                            self.assertEqual(manifest.read_text(), original)
                        else:
                            self.assertTrue(
                                FILTER.native_manifest_equal(manifest.read_text(), canonical_manifest(component))
                            )

    def test_actual_migration_serialization_matches_complete_production_templates(self):
        for component in ("keycloak", "postgres"):
            desired = canonical_manifest(component)
            migrated = to_nice_yaml(yaml.safe_load(desired))
            with self.subTest(component=component):
                self.assertNotEqual(migrated, desired, "Reproduce the prior byte-only drift")
                self.assertTrue(FILTER.native_manifest_equal(migrated, desired))
                for field in ("image", "env", "ports"):
                    changed = yaml.safe_load(migrated)
                    container = changed["spec"]["containers"][0]
                    if field == "image":
                        container[field] = "example.invalid/different@sha256:" + "2" * 64
                    elif field == "env":
                        container[field][0]["value"] = "different"
                    else:
                        container[field][0]["hostIP"] = "127.0.0.2"
                    with self.subTest(field=field):
                        self.assertFalse(FILTER.native_manifest_equal(to_nice_yaml(changed), desired))

    def test_types_and_sequence_order_are_not_formatting(self):
        original = yaml.safe_load(canonical_manifest("keycloak"))
        for first, second in ((True, 1), ("5432", 5432), (1, 1.0)):
            left, right = deepcopy(original), deepcopy(original)
            left["spec"]["fixture"] = first
            right["spec"]["fixture"] = second
            self.assertFalse(FILTER.native_manifest_equal(to_nice_yaml(left), to_nice_yaml(right)))
        changed = deepcopy(original)
        changed["spec"]["containers"][0]["env"].reverse()
        self.assertFalse(FILTER.native_manifest_equal(to_nice_yaml(original), to_nice_yaml(changed)))

    def test_invalid_or_ambiguous_documents_fail_closed_without_echoing_content(self):
        desired = canonical_manifest("keycloak")
        for original in ("", "secret-canary: [", "kind: Pod\nkind: Pod\n", "[]", "kind: Service\n", None):
            with self.subTest(original=original), self.assertRaises(AnsibleFilterError) as error:
                FILTER.native_manifest_equal(original, desired)
            self.assertNotIn("secret-canary", str(error.exception))

    def test_both_native_paths_use_preview_to_skip_equal_byte_rendering(self):
        for component in ("keycloak", "postgres"):
            source = yaml.safe_load((ROOT / "roles" / (component + "_deploy") / "tasks/systemd.yml").read_text())

            def flatten(tasks):
                for task in tasks:
                    yield task
                    for branch in ("block", "rescue", "always"):
                        yield from flatten(task.get(branch, []))

            tasks = list(flatten(source))
            preview = next(task for task in tasks if task["name"].startswith("Preview transactional"))
            render = next(task for task in tasks if task["name"].startswith("Render the transactional"))
            preserve = next(task for task in tasks if task["name"].startswith("Preserve equal"))
            self.assertIn("native_manifest_equal", str(preview["ansible.builtin.set_fact"]))
            self.assertEqual(render["when"], component + "_deploy_manifest_preview.changed | bool")
            self.assertEqual(preserve["when"], "not " + component + "_deploy_manifest_preview.changed | bool")
            self.assertEqual(preserve["ansible.builtin.file"]["mode"], "0600")
            self.assertTrue(preview["no_log"])
            self.assertTrue(preserve["no_log"])
