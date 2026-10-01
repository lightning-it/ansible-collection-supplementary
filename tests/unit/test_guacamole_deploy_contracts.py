"""Security contracts for Guacamole deployment."""

from __future__ import annotations

import http.server
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles" / "guacamole_deploy"
TASKS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "main.yml"
ASSERTS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "assert.yml"
DEFAULTS = ROOT / "roles" / "guacamole_deploy" / "defaults" / "main.yml"
POD = ROOT / "roles" / "guacamole_deploy" / "templates" / "guacamole-pod.yml.j2"
SYSTEMD_TASKS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "systemd.yml"
HANDLERS = ROOT / "roles" / "guacamole_deploy" / "handlers" / "main.yml"
LEGACY_SERVICE = ROOT / "roles" / "guacamole_deploy" / "templates" / "guacamole.service.j2"
OIDC_GROUP_TASKS = ROOT / "roles" / "guacamole_deploy" / "tasks" / "reconcile_oidc_groups.yml"


class _HealthyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class GuacamoleDeployContractTests(unittest.TestCase):
    def test_connection_contract_validation_redacts_inventory_credentials(self) -> None:
        asserts = ASSERTS.read_text(encoding="utf-8")
        connection_contract = asserts.split("- name: Validate declared Guacamole connection contracts", 1)[1]

        self.assertIn("no_log: true", connection_contract)

    def test_breakglass_sql_uses_psql_quoted_variables(self) -> None:
        source = TASKS.read_text(encoding="utf-8")

        self.assertIn("breakglass_salt={{ guacamole_deploy_secrets.breakglass_salt }}", source)
        self.assertIn("convert_to(:'breakglass_salt','UTF8')", source)
        self.assertIn("decode(:'breakglass_hash','hex')", source)
        self.assertIn("name = :'breakglass_user'", source)
        self.assertNotIn("convert_to('{{ guacamole_deploy_secrets.breakglass_salt }}'", source)

    def test_prechecks_are_imported_before_mutation(self) -> None:
        source = TASKS.read_text(encoding="utf-8")

        self.assertIn("ansible.builtin.import_tasks: assert.yml", source)
        self.assertLess(
            source.index("import_tasks: assert.yml"),
            source.index("ansible.builtin.package:"),
        )

    def test_api_session_timeout_is_bounded_and_rendered(self) -> None:
        defaults = DEFAULTS.read_text(encoding="utf-8")
        asserts = ASSERTS.read_text(encoding="utf-8")
        pod = POD.read_text(encoding="utf-8")

        self.assertIn("guacamole_deploy_api_session_timeout_minutes: 60", defaults)
        self.assertIn("guacamole_deploy_api_session_timeout_minutes is integer", asserts)
        self.assertIn("guacamole_deploy_api_session_timeout_minutes is not boolean", asserts)
        self.assertIn("guacamole_deploy_api_session_timeout_minutes >= 1", asserts)
        self.assertIn("guacamole_deploy_api_session_timeout_minutes <= 1440", asserts)
        self.assertNotIn("guacamole_deploy_api_session_timeout_minutes | int", asserts)
        self.assertIn("name: API_SESSION_TIMEOUT", pod)
        self.assertIn(
            "Apache Guacamole defines API_SESSION_TIMEOUT in minutes",
            pod,
        )
        self.assertIn("guacamole_deploy_api_session_timeout_minutes | string | to_json", pod)
        self.assertNotIn("guacamole_deploy_api_session_timeout_minutes * 60000", pod)

    def test_host_port_rejects_yaml_booleans_and_is_bounded(self) -> None:
        asserts = ASSERTS.read_text(encoding="utf-8")

        self.assertIn("guacamole_deploy_port is integer", asserts)
        self.assertIn("guacamole_deploy_port is not boolean", asserts)
        self.assertIn("guacamole_deploy_port > 0", asserts)
        self.assertIn("guacamole_deploy_port <= 65535", asserts)
        self.assertNotIn("guacamole_deploy_port | int", asserts)

    def test_quadlet_interface_rejects_type_path_and_directive_injection(self) -> None:
        tasks = yaml.safe_load(ASSERTS.read_text(encoding="utf-8"))
        contract = "\n".join(tasks[0]["ansible.builtin.assert"]["that"])

        for value in (
            "guacamole_deploy_systemd_unit_name",
            "guacamole_deploy_systemd_description",
            "guacamole_deploy_quadlet_dir",
            "guacamole_deploy_legacy_systemd_unit_path",
        ):
            self.assertIn(f"{value} is string", contract)
        self.assertIn("^[A-Za-z0-9][A-Za-z0-9_.-]*$", contract)
        self.assertIn("'\\n' not in guacamole_deploy_systemd_description", contract)
        self.assertIn("'\\r' not in guacamole_deploy_systemd_description", contract)

    def test_static_network_and_proxy_bypass_are_exact_and_default_off(self) -> None:
        defaults = DEFAULTS.read_text(encoding="utf-8")
        asserts = ASSERTS.read_text(encoding="utf-8")
        pod = POD.read_text(encoding="utf-8")
        systemd_tasks = SYSTEMD_TASKS.read_text(encoding="utf-8")

        self.assertIn('guacamole_deploy_network_name: ""', defaults)
        self.assertIn('guacamole_deploy_network_ipv4: ""', defaults)
        self.assertIn("guacamole_deploy_no_proxy: []", defaults)
        self.assertIn('guacamole_deploy_proxy_url: ""', defaults)
        self.assertIn("(guacamole_deploy_network_name | length == 0)", asserts)
        self.assertIn("== (guacamole_deploy_network_ipv4 | length == 0)", asserts)
        self.assertIn("guacamole_deploy_no_proxy | unique", asserts)
        self.assertIn("guacamole_deploy_quadlet_networks", defaults)
        self.assertIn(
            'podman_systemd_networks: "{{ guacamole_deploy_quadlet_networks }}"',
            systemd_tasks,
        )
        self.assertIn("name: no_proxy", pod)
        self.assertIn("name: NO_PROXY", pod)
        self.assertIn("name: HTTPS_PROXY", pod)
        self.assertIn("name: JAVA_TOOL_OPTIONS", pod)
        self.assertIn("-Dhttp.proxyHost=", pod)
        self.assertIn("-Dhttp.proxyPort=", pod)
        self.assertIn("-Dhttps.proxyHost=", pod)
        self.assertIn("-Dhttps.proxyPort=", pod)
        self.assertIn("-Dhttp.nonProxyHosts=", pod)
        self.assertIn("guacamole_deploy_proxy_url | to_json", pod)
        self.assertIn("':[1-9][0-9]{0,4}\\\\Z'", asserts)
        self.assertIn("regex_replace('^.*:([0-9]+)$', '\\\\1')", asserts)
        self.assertIn(") <= 65535", asserts)
        self.assertIn("guacamole_deploy_no_proxy | join(',') | to_json", pod)
        non_application_containers = pod.split("    - name: guacamole", 1)[0]
        for proxy_name in (
            "http_proxy",
            "HTTP_PROXY",
            "https_proxy",
            "HTTPS_PROXY",
            "all_proxy",
            "ALL_PROXY",
            "ftp_proxy",
            "FTP_PROXY",
            "no_proxy",
            "NO_PROXY",
        ):
            self.assertIn(f'name: {proxy_name}, value: ""', non_application_containers)
        self.assertNotIn("JAVA_TOOL_OPTIONS", non_application_containers)

    def test_persistent_lifecycle_uses_only_native_quadlet(self) -> None:
        tasks = TASKS.read_text(encoding="utf-8")
        systemd_tasks = SYSTEMD_TASKS.read_text(encoding="utf-8")
        handlers = HANDLERS.read_text(encoding="utf-8")
        defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))

        self.assertFalse(LEGACY_SERVICE.exists())
        self.assertEqual(defaults["guacamole_deploy_systemd_unit_name"], "{{ guacamole_deploy_pod_name }}-pod")
        self.assertIn("include_tasks: systemd.yml", tasks)
        self.assertIn("name: lit.foundational.podman_systemd", systemd_tasks)
        self.assertIn(
            "guacamole_deploy_manage_systemd | bool or guacamole_deploy_skip_runtime | bool",
            ASSERTS.read_text(encoding="utf-8"),
        )
        self.assertLess(
            systemd_tasks.index("Refuse an unsafe legacy Guacamole unit path before reading"),
            systemd_tasks.index("Read the exact legacy Guacamole unit before takeover"),
        )
        self.assertIn("guacamole_deploy_legacy_unit_stat.stat.isreg", systemd_tasks)
        self.assertIn("no_log: true", systemd_tasks)
        self.assertIn("Refuse to replace an unknown Guacamole systemd unit", systemd_tasks)
        self.assertIn("Resolve the loaded legacy Guacamole unit fragment", systemd_tasks)
        self.assertIn("Resolve loaded legacy Guacamole unit drop-ins", systemd_tasks)
        self.assertIn("Refuse a legacy Guacamole unit loaded from an unexpected fragment", systemd_tasks)
        self.assertIn("--property=FragmentPath", systemd_tasks)
        self.assertIn("--property=DropInPaths", systemd_tasks)
        self.assertIn("Refuse unproven drift in an existing native Guacamole Quadlet", systemd_tasks)
        self.assertIn("guacamole_deploy_native_quadlet_file.stat.isreg", systemd_tasks)
        self.assertIn("not (guacamole_deploy_native_quadlet_file.stat.islnk", systemd_tasks)
        self.assertIn("guacamole_deploy_native_quadlet_file.stat.mode | default('') == '0644'", systemd_tasks)
        self.assertIn("guacamole_deploy_native_quadlet_file.stat.pw_name | default('') == 'root'", systemd_tasks)
        self.assertIn("Resolve the loaded native Guacamole unit fragment", systemd_tasks)
        self.assertIn("Resolve loaded native Guacamole unit drop-ins", systemd_tasks)
        self.assertIn("^/run/systemd/generator", systemd_tasks)
        self.assertIn("guacamole_deploy_native_systemd_active.stdout | trim in ['active', 'failed']", systemd_tasks)
        self.assertNotIn("guacamole_deploy_native_systemd_active.stdout | trim != 'unknown'", systemd_tasks)
        self.assertIn("Refuse unmanaged Guacamole pod; remove it first", systemd_tasks)
        self.assertIn("not (guacamole_deploy_legacy_unit_stat.stat.islnk", systemd_tasks)
        self.assertIn(
            "Stage native Guacamole Quadlet before lifecycle mutation",
            systemd_tasks,
        )
        self.assertIn("Require the staged native Guacamole Quadlet provenance boundary", systemd_tasks)
        self.assertIn("Resolve staged native Guacamole unit drop-ins", systemd_tasks)
        self.assertIn(
            'name: "{{ guacamole_deploy_legacy_systemd_unit_path | basename }}"',
            systemd_tasks,
        )
        self.assertLess(
            systemd_tasks.index("Stop and disable the exact legacy Guacamole unit before removal"),
            systemd_tasks.index("Remove the verified legacy Guacamole systemd unit"),
        )
        self.assertLess(
            systemd_tasks.index("Wait for Guacamole readiness before committing legacy removal"),
            systemd_tasks.index("Remove the verified legacy Guacamole systemd unit"),
        )
        self.assertIn("Attempt exact legacy Guacamole restoration after failed takeover", systemd_tasks)
        self.assertIn("Require native Guacamole inactivity before legacy restoration", systemd_tasks)
        self.assertIn("guacamole_deploy_legacy_unit_raw.content | b64decode", systemd_tasks)
        self.assertIn("Restore the exact pre-transaction Guacamole Pod manifest", systemd_tasks)
        self.assertIn("Remove a transaction-created Guacamole Pod manifest", systemd_tasks)
        self.assertIn("Restore generated native Guacamole service state after failure", systemd_tasks)
        self.assertLess(
            systemd_tasks.index("Restore the exact pre-transaction Guacamole Pod manifest"),
            systemd_tasks.index("Restore generated native Guacamole service state after failure"),
        )
        self.assertIn("Capture the exact pre-transaction Guacamole Pod manifest", systemd_tasks)
        self.assertIn("Render the transactional Guacamole Pod manifest", systemd_tasks)
        self.assertIn("guacamole_deploy_legacy_unit_stat.stat.exists | bool", systemd_tasks)
        self.assertIn("Reload systemd after verified legacy Guacamole unit removal", handlers)
        self.assertIn("scope: system", handlers)
        self.assertNotIn('scope: "{{ guacamole_deploy_systemd_scope }}"', handlers)
        self.assertIn("notify: Reload systemd after verified legacy Guacamole unit removal", systemd_tasks)
        self.assertIn("'started'", systemd_tasks)
        self.assertIn("guacamole_deploy_manifest_render.changed", systemd_tasks)
        self.assertLess(
            systemd_tasks.index("Remove the verified legacy Guacamole systemd unit"),
            systemd_tasks.index("Flush systemd reload after verified legacy Guacamole unit removal"),
        )
        self.assertNotIn("- name: Wait for Guacamole readiness\n", tasks)
        self.assertNotIn("podman kube play", tasks)
        self.assertNotIn("podman kube down", tasks)
        self.assertIn(
            "guacamole_deploy_legacy_systemd_unit_path: >-\n  /etc/systemd/system/guacamole.service",
            DEFAULTS.read_text(encoding="utf-8"),
        )

    def test_drop_ins_are_rejected_and_staging_skips_verified_native_units(self) -> None:
        tasks = yaml.safe_load(SYSTEMD_TASKS.read_text(encoding="utf-8"))
        task_map = {task["name"]: task for task in tasks}
        native_contract = "\n".join(
            task_map["Refuse unproven drift in an existing native Guacamole Quadlet"]["ansible.builtin.assert"]["that"]
        )
        legacy_contract = "\n".join(
            task_map["Refuse a legacy Guacamole unit loaded from an unexpected fragment"]["ansible.builtin.assert"][
                "that"
            ]
        )
        transaction = task_map["Cut over to native Guacamole Quadlet with rollback"]
        transaction_map = {task["name"]: task for task in transaction["block"]}
        staged_contract = "\n".join(
            transaction_map["Require the staged native Guacamole Quadlet provenance boundary"][
                "ansible.builtin.assert"
            ]["that"]
        )
        staging_condition = "not (guacamole_deploy_native_quadlet_file.stat.exists | default(false))"

        self.assertIn("guacamole_deploy_native_drop_in_paths.stdout | trim == ''", native_contract)
        self.assertIn("guacamole_deploy_legacy_drop_in_paths.stdout | trim == ''", legacy_contract)
        self.assertIn("guacamole_deploy_staged_drop_in_paths.stdout | trim == ''", staged_contract)
        for name in (
            "Stage native Guacamole Quadlet before lifecycle mutation",
            "Reinspect the staged native Guacamole Quadlet",
            "Resolve the staged native Guacamole unit fragment",
            "Resolve staged native Guacamole unit drop-ins",
            "Require the staged native Guacamole Quadlet provenance boundary",
        ):
            self.assertEqual(transaction_map[name]["when"], staging_condition)
        manage_action = transaction_map["Manage native Guacamole Quadlet service"]["vars"]["podman_systemd_action"]
        self.assertIn("guacamole_deploy_native_systemd_active.stdout | trim != 'active'", manage_action)
        self.assertNotIn("guacamole_deploy_legacy_unit_stat.stat.exists", manage_action)
        native_restoration = next(
            task
            for task in transaction["rescue"]
            if task["name"] == "Attempt pre-existing native Guacamole service-state restoration"
        )
        for task in native_restoration["block"]:
            state = task["ansible.builtin.systemd"]["state"]
            self.assertIn("'started'", state)
            self.assertIn("guacamole_deploy_manifest_render.changed", state)

    def test_post_removal_reload_failure_executes_exact_manifest_and_service_rollback(self) -> None:
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "Pinned Devtools Ansible is required")

        with tempfile.TemporaryDirectory(prefix="guacamole-rollback-") as temporary:
            root = Path(temporary)
            collection = root / "collections/ansible_collections/lit/supplementary"
            fixture_role = collection / "roles/guacamole_deploy"
            fixture_role.parent.mkdir(parents=True)
            shutil.copytree(ROLE, fixture_role)
            fixture_foundational_tasks = (
                root / "collections/ansible_collections/lit/foundational/roles/podman_systemd/tasks"
            )
            fixture_foundational_tasks.mkdir(parents=True)
            (fixture_foundational_tasks / "main.yml").write_text(
                """---
- name: Ensure fixture Quadlet directory exists
  ansible.builtin.file:
    path: "{{ podman_systemd_quadlet_dir }}"
    state: directory
    mode: '0755'

- name: Materialize fixture Quadlet
  ansible.builtin.copy:
    dest: "{{ podman_systemd_quadlet_dir }}/{{ podman_systemd_unit_name }}.kube"
    content: |
      [Unit]
      Description={{ podman_systemd_description }}
      After=network-online.target
      Wants=network-online.target
      [Kube]
      Yaml={{ podman_systemd_manifest_path }}
      [Install]
      WantedBy=multi-user.target
    mode: '0644'
  when: podman_systemd_action != 'absent'

- name: Apply fixture service action
  ansible.builtin.command:
    argv:
      - systemctl
      - >-
        {{
          'restart'
          if podman_systemd_action == 'restarted'
          else ('stop' if podman_systemd_action == 'stopped' else 'start')
        }}
      - "{{ podman_systemd_unit_name }}.service"
  changed_when: true
  when: podman_systemd_action != 'absent'

- name: Apply fixture enabled state
  ansible.builtin.command:
    argv:
      - systemctl
      - "{{ 'enable' if podman_systemd_enabled | bool else 'disable' }}"
      - "{{ podman_systemd_unit_name }}.service"
  changed_when: true
  when: podman_systemd_action != 'absent'

- name: Stop fixture service before removal
  ansible.builtin.command:
    argv: [systemctl, stop, "{{ podman_systemd_unit_name }}.service"]
  changed_when: true
  when: podman_systemd_action == 'absent'

- name: Remove fixture Quadlet
  ansible.builtin.file:
    path: "{{ podman_systemd_quadlet_dir }}/{{ podman_systemd_unit_name }}.kube"
    state: absent
  when: podman_systemd_action == 'absent'
""",
                encoding="utf-8",
            )
            fixture_systemd = fixture_role / "tasks/systemd.yml"
            production_systemd = fixture_systemd.read_text(encoding="utf-8")
            privileged_render = """        owner: root
        group: root
        mode: "0600"
"""
            self.assertEqual(production_systemd.count(privileged_render), 1)
            fixture_systemd.write_text(
                production_systemd.replace(
                    privileged_render,
                    f"""        owner: {os.geteuid()}
        group: {os.getegid()}
        mode: "0600"
""",
                    1,
                )
                .replace(
                    "guacamole_deploy_staged_quadlet_file.stat.pw_name | default('') == 'root'",
                    f"guacamole_deploy_staged_quadlet_file.stat.uid | int == {os.geteuid()}",
                )
                .replace(
                    "guacamole_deploy_staged_quadlet_file.stat.gr_name | default('') == 'root'",
                    f"guacamole_deploy_staged_quadlet_file.stat.gid | int == {os.getegid()}",
                )
                .replace("      retries: 40\n      delay: 5\n", "      retries: 1\n      delay: 0\n", 1),
                encoding="utf-8",
            )

            fake_bin = root / "bin"
            fake_bin.mkdir()
            state = root / "systemd-state"
            state.mkdir()
            log = root / "systemctl.log"
            manifest = root / "guacamole.yml"
            original = b"original-guacamole-manifest\nwith-exact-bytes\n"
            manifest.write_bytes(original)
            manifest.chmod(0o640)
            quadlet_dir = root / "quadlets"
            quadlet_dir.mkdir()
            legacy_unit = root / "guacamole.service"
            legacy_unit.write_text(
                "\n".join(
                    (
                        "[Unit]",
                        "Description=Apache Guacamole Podman application pod",
                        "Wants=network-online.target",
                        "After=network-online.target",
                        "[Service]",
                        "Type=oneshot",
                        "RemainAfterExit=yes",
                        f"ExecStartPre=-/usr/bin/podman kube down {manifest}",
                        f"ExecStart=/usr/bin/podman kube play {manifest}",
                        f"ExecStop=/usr/bin/podman kube down {manifest}",
                        "TimeoutStartSec=300",
                        "TimeoutStopSec=120",
                        "[Install]",
                        "WantedBy=multi-user.target",
                        "",
                    )
                ),
                encoding="utf-8",
            )
            legacy_unit.chmod(0o644)
            legacy_original = legacy_unit.read_bytes()
            native_quadlet = quadlet_dir / "guacamole-pod.kube"

            systemctl = fake_bin / "systemctl"
            systemctl.write_text(
                """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_SYSTEMCTL_LOG"
all="$*"
case "$all" in
  *--property=DropInPaths*) printf '\\n'; exit 0 ;;
  *--property=FragmentPath*)
    case "$all" in
      *guacamole-pod.service*)
        if [ -f "$FAKE_NATIVE_QUADLET" ]; then
          printf '%s\\n' /run/systemd/generator/guacamole-pod.service
        else
          printf '\\n'
        fi
        ;;
      *guacamole.service*) printf '%s\\n' "$FAKE_LEGACY_UNIT" ;;
    esac
    exit 0
    ;;
esac
command_name="${1:-}"
shift || true
unit="${1:-}"
safe_unit=$(printf '%s' "$unit" | tr '/@.' '___')
active_file="$FAKE_SYSTEMD_STATE/$safe_unit.active"
enabled_file="$FAKE_SYSTEMD_STATE/$safe_unit.enabled"
case "$unit" in
  guacamole.service) default_active=active; default_enabled=enabled ;;
  *) default_active=unknown; default_enabled=not-found ;;
esac
active=$(cat "$active_file" 2>/dev/null || printf '%s' "$default_active")
enabled=$(cat "$enabled_file" 2>/dev/null || printf '%s' "$default_enabled")
case "$command_name" in
  show)
    printf 'LoadState=loaded\\nActiveState=%s\\nSubState=%s\\nUnitFileState=%s\\n' \
      "$active" "$active" "$enabled"
    ;;
  is-active)
    printf '%s\\n' "$active"
    test "$active" = active && exit 0
    test "$active" = unknown && exit 4
    exit 3
    ;;
  is-enabled)
    printf '%s\\n' "$enabled"
    test "$enabled" = enabled && exit 0
    test "$enabled" = not-found && exit 1
    exit 1
    ;;
  enable) printf enabled > "$enabled_file" ;;
  disable) printf disabled > "$enabled_file" ;;
  start|restart) printf active > "$active_file" ;;
  stop) printf inactive > "$active_file" ;;
  daemon-reload)
    if [ ! -e "$FAKE_LEGACY_UNIT" ]; then
      exit 42
    fi
    ;;
  list-unit-files) printf '%s %s\\n' "$unit" "$enabled" ;;
esac
""",
                encoding="utf-8",
            )
            systemctl.chmod(0o755)
            podman = fake_bin / "podman"
            podman.write_text(
                '#!/bin/sh\n[ "${1:-} ${2:-}" = "pod exists" ] && exit 1\nexit 0\n',
                encoding="utf-8",
            )
            podman.chmod(0o755)

            health_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HealthyHandler)
            health_thread = threading.Thread(target=health_server.serve_forever, daemon=True)
            health_thread.start()
            playbook = root / "rollback.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "gather_facts": False,
                            "vars": {
                                "ansible_service_mgr": "systemd",
                                "guacamole_deploy_manifest_path": str(manifest),
                                "guacamole_deploy_quadlet_dir": str(quadlet_dir),
                                "guacamole_deploy_legacy_systemd_unit_path": str(legacy_unit),
                                "guacamole_deploy_health_url": (
                                    f"http://127.0.0.1:{health_server.server_port}/guacamole/"
                                ),
                                "guacamole_deploy_secrets": {"db_password": "OFFLINE_TEST_ONLY"},
                            },
                            "tasks": [
                                {
                                    "name": "Execute the real Guacamole systemd transaction",
                                    "ansible.builtin.include_role": {
                                        "name": "lit.supplementary.guacamole_deploy",
                                        "tasks_from": "systemd",
                                    },
                                }
                            ],
                        }
                    ],
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            config = root / "ansible.cfg"
            config.write_text("[defaults]\nstdout_callback=default\n", encoding="utf-8")
            environment = {
                **os.environ,
                "ANSIBLE_CONFIG": str(config),
                "ANSIBLE_COLLECTIONS_PATH": f"{root / 'collections'}:/usr/share/ansible/collections",
                "ANSIBLE_LOCAL_TEMP": str(root / "ansible-tmp"),
                "ANSIBLE_NOCOLOR": "1",
                "FAKE_SYSTEMCTL_LOG": str(log),
                "FAKE_SYSTEMD_STATE": str(state),
                "FAKE_LEGACY_UNIT": str(legacy_unit),
                "FAKE_NATIVE_QUADLET": str(native_quadlet),
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
            }
            try:
                result = subprocess.run(  # noqa: S603
                    [executable, "-i", "localhost,", "-c", "local", str(playbook)],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
            finally:
                health_server.shutdown()
                health_server.server_close()
                health_thread.join(timeout=5)

            output = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("Native Guacamole Quadlet takeover failed", output)
            self.assertEqual(manifest.read_bytes(), original)
            self.assertEqual(manifest.stat().st_mode & 0o777, 0o640)
            self.assertTrue(legacy_unit.exists())
            self.assertEqual(legacy_unit.read_bytes(), legacy_original)
            self.assertEqual(legacy_unit.stat().st_mode & 0o777, 0o644)
            self.assertFalse(native_quadlet.exists())
            service_log = log.read_text(encoding="utf-8")
            evidence = f"{output}\nSYSTEMCTL LOG:\n{service_log}"
            self.assertIn("stop guacamole.service", service_log, evidence)
            self.assertIn("disable guacamole.service", service_log, evidence)
            self.assertIn("restart guacamole-pod.service", service_log, evidence)
            self.assertIn("stop guacamole-pod.service", service_log, evidence)
            self.assertIn("enable guacamole.service", service_log, evidence)
            self.assertIn("start guacamole.service", service_log, evidence)
            self.assertGreaterEqual(service_log.count("daemon-reload"), 2, evidence)
            legacy_state = "guacamole_service"
            native_state = "guacamole-pod_service"
            self.assertEqual((state / f"{legacy_state}.active").read_text(encoding="utf-8"), "active")
            self.assertEqual((state / f"{legacy_state}.enabled").read_text(encoding="utf-8"), "enabled")
            self.assertEqual((state / f"{native_state}.active").read_text(encoding="utf-8"), "inactive")

    def test_existing_manifest_and_quadlet_use_executable_slurp_contract(self) -> None:
        tasks = yaml.safe_load(SYSTEMD_TASKS.read_text(encoding="utf-8"))
        task_map = {task["name"]: task for task in tasks}
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "Pinned Devtools Ansible is required")

        with tempfile.TemporaryDirectory(prefix="guacamole-slurp-") as temporary:
            temporary_path = Path(temporary)
            manifest = temporary_path / "guacamole-pod.yml"
            quadlet = temporary_path / "guacamole-pod.kube"
            manifest.write_text("kind: Pod\n", encoding="utf-8")
            quadlet.write_text("[Kube]\nYaml=/tmp/guacamole-pod.yml\n", encoding="utf-8")
            selected_tasks = []
            for name in (
                "Capture the exact pre-transaction Guacamole Pod manifest",
                "Read the desired native Guacamole Quadlet file",
            ):
                action = task_map[name]["ansible.builtin.slurp"]
                self.assertEqual(set(action), {"src"})
                selected_tasks.append({"name": name, "ansible.builtin.slurp": action})

            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "guacamole_deploy_manifest_path": str(manifest),
                        "guacamole_deploy_quadlet_dir": str(temporary_path),
                        "guacamole_deploy_systemd_unit_name": "guacamole-pod",
                    },
                    "tasks": selected_tasks,
                }
            ]
            playbook = temporary_path / "slurp.yml"
            playbook.write_text(yaml.safe_dump(play), encoding="utf-8")
            config = temporary_path / "ansible.cfg"
            config.write_text(
                f"[defaults]\nremote_tmp={temporary_path / 'remote'}\n",
                encoding="utf-8",
            )
            result = subprocess.run(  # noqa: S603
                [executable, "-i", "localhost,", "-c", "local", str(playbook)],
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(config),
                    "ANSIBLE_NOCOLOR": "1",
                    "ANSIBLE_STDOUT_CALLBACK": "default",
                    "ANSIBLE_LOCAL_TEMP": str(temporary_path / "ansible"),
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_takeover_rejects_unrestorable_failed_and_unknown_states(self) -> None:
        tasks = yaml.safe_load(SYSTEMD_TASKS.read_text(encoding="utf-8"))
        task_map = {task["name"]: task for task in tasks}
        lifecycle_assertions = task_map["Refuse unknown Guacamole lifecycle states"]["ansible.builtin.assert"]["that"]
        contract = "\n".join(lifecycle_assertions)

        self.assertIn("guacamole_deploy_legacy_unit_stat.stat.exists", contract)
        self.assertIn("in ['active', 'inactive']", contract)
        self.assertIn("in ['enabled', 'disabled']", contract)
        self.assertIn("guacamole_deploy_native_systemd_active.stdout | trim != 'failed'", contract)
        self.assertIn("guacamole_deploy_systemd_scope == 'system'", ASSERTS.read_text(encoding="utf-8"))
        self.assertIn("guacamole_deploy_quadlet_dir == '/etc/containers/systemd'", ASSERTS.read_text(encoding="utf-8"))

    def test_no_legacy_rollback_proves_transaction_created_native_is_inactive(self) -> None:
        tasks = yaml.safe_load(SYSTEMD_TASKS.read_text(encoding="utf-8"))
        transaction = next(
            task for task in tasks if task["name"] == "Cut over to native Guacamole Quadlet with rollback"
        )
        proof = next(
            task
            for task in transaction["rescue"]
            if task["name"] == "Prove the failed native Guacamole controller is inactive"
        )
        condition = str(proof["when"])
        self.assertIn("guacamole_deploy_legacy_systemd_active", condition)
        self.assertIn("guacamole_deploy_native_quadlet_file", condition)

        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable, "Pinned Devtools Ansible is required")
        with tempfile.TemporaryDirectory(prefix="guacamole-no-legacy-rollback-") as temporary:
            temporary_path = Path(temporary)
            fake_bin = temporary_path / "bin"
            fake_bin.mkdir()
            systemctl = fake_bin / "systemctl"
            systemctl.write_text(
                "#!/bin/sh\nprintf '%s\\n' active\nexit 0\n",
                encoding="utf-8",
            )
            systemctl.chmod(0o755)
            playbook = temporary_path / "proof.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "gather_facts": False,
                            "vars": {
                                "guacamole_deploy_legacy_unit_stat": {"stat": {"exists": False}},
                                "guacamole_deploy_legacy_systemd_active": {"stdout": "unknown"},
                                "guacamole_deploy_native_quadlet_file": {"stat": {"exists": False}},
                                "guacamole_deploy_systemd_scope": "system",
                                "guacamole_deploy_systemd_unit_name": "guacamole-pod",
                            },
                            "tasks": [
                                proof,
                                {
                                    "name": "Require fail-closed inactivity evidence",
                                    "ansible.builtin.assert": {
                                        "that": [
                                            "guacamole_deploy_native_quiescence_failure_message | length > 0",
                                            "not guacamole_deploy_native_quiescence_proven | default(false) | bool",
                                        ]
                                    },
                                },
                            ],
                        }
                    ],
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            config = temporary_path / "ansible.cfg"
            config.write_text("[defaults]\nstdout_callback=default\n", encoding="utf-8")
            result = subprocess.run(  # noqa: S603
                [executable, "-i", "localhost,", "-c", "local", str(playbook)],
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(config),
                    "ANSIBLE_NOCOLOR": "1",
                    "ANSIBLE_LOCAL_TEMP": str(temporary_path / "ansible"),
                    "PATH": f"{fake_bin}:{os.environ['PATH']}",
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_file_restoration_does_not_require_native_quiescence(self) -> None:
        tasks = yaml.safe_load(SYSTEMD_TASKS.read_text(encoding="utf-8"))
        transaction = next(
            task for task in tasks if task["name"] == "Cut over to native Guacamole Quadlet with rollback"
        )
        restoration = next(
            task
            for task in transaction["rescue"]
            if task["name"] == "Attempt exact legacy Guacamole restoration after failed takeover"
        )
        restore_file, restore_state = restoration["block"]
        self.assertEqual(
            restore_file["when"],
            "guacamole_deploy_legacy_unit_stat.stat.exists | bool",
        )
        self.assertIn("guacamole_deploy_native_quiescence_proven", "\n".join(restore_state["when"]))
        self.assertIn("!= 'active'", "\n".join(restore_state["when"]))

    def test_legacy_takeover_requires_the_exact_ordered_unit_contract(self) -> None:
        tasks = yaml.safe_load(SYSTEMD_TASKS.read_text(encoding="utf-8"))
        task_map = {task["name"]: task for task in tasks}
        normalize = task_map["Normalize the role-owned legacy Guacamole unit contract"]
        validate = task_map["Refuse to replace an unknown Guacamole systemd unit"]
        expected = normalize["ansible.builtin.set_fact"]["guacamole_deploy_legacy_unit_expected_lines"]
        actual_expression = normalize["ansible.builtin.set_fact"]["guacamole_deploy_legacy_unit_actual_lines"]

        self.assertIn("splitlines()", actual_expression)
        self.assertIn("reject('match', '^#')", actual_expression)
        self.assertEqual(expected[0], "[Unit]")
        self.assertEqual(expected[-1], "WantedBy=multi-user.target")
        self.assertEqual(sum(line.startswith("ExecStart=") for line in expected), 1)
        self.assertEqual(sum(line.startswith("ExecStop=") for line in expected), 1)
        self.assertIn("--network {{ guacamole_deploy_network_name }}:ip=", "\n".join(expected))
        self.assertEqual(
            validate["ansible.builtin.assert"]["that"],
            ["guacamole_deploy_legacy_unit_actual_lines == guacamole_deploy_legacy_unit_expected_lines"],
        )
        transaction = task_map["Cut over to native Guacamole Quadlet with rollback"]
        transaction_names = [task["name"] for task in transaction["block"]]
        self.assertLess(tasks.index(normalize), tasks.index(validate))
        self.assertLess(tasks.index(validate), tasks.index(transaction))
        self.assertIn(
            "Stop and disable the exact legacy Guacamole unit before removal",
            transaction_names,
        )

    def test_oidc_group_claim_and_exact_connection_permissions_are_explicit(
        self,
    ) -> None:
        defaults = DEFAULTS.read_text(encoding="utf-8")
        asserts = ASSERTS.read_text(encoding="utf-8")
        pod = POD.read_text(encoding="utf-8")
        tasks = TASKS.read_text(encoding="utf-8")
        group_tasks = OIDC_GROUP_TASKS.read_text(encoding="utf-8")

        self.assertIn('guacamole_deploy_oidc_groups_claim_type: "groups"', defaults)
        self.assertIn("guacamole_deploy_oidc_group_connections: []", defaults)
        self.assertIn("name: OPENID_GROUPS_CLAIM_TYPE", pod)
        self.assertIn("Validate declared Guacamole OIDC group authorization contracts", asserts)
        self.assertIn("difference(guacamole_deploy_connections", asserts)
        self.assertIn("Reject duplicate Guacamole connection names", asserts)
        self.assertIn("Reject duplicate Guacamole OIDC authorization group names", asserts)
        self.assertGreater(
            asserts.index("Validate declared Guacamole OIDC group authorization contracts"),
            asserts.index("Validate declared Guacamole connection contracts"),
        )
        self.assertIn("include_tasks: reconcile_oidc_groups.yml", tasks)
        self.assertGreater(
            tasks.index("include_tasks: reconcile_oidc_groups.yml"),
            tasks.index("include_tasks: reconcile_connection.yml"),
        )
        self.assertIn("guacamole_deploy_oidc_groups_claim_type is string", asserts)
        self.assertIn("lit_guacamole_oidc_managed_group", group_tasks)
        self.assertIn("count(connection.connection_id) <> 1", group_tasks)
        self.assertIn("DELETE FROM guacamole_entity AS entity", group_tasks)
        self.assertIn("permission.permission <> 'READ'", group_tasks)
        self.assertIn("SELECT managed_entity_id, connection.connection_id, 'READ'", group_tasks)
        self.assertIn("user_group.disabled IS DISTINCT FROM false", group_tasks)
        self.assertIn("DELETE FROM guacamole_system_permission", group_tasks)
        self.assertIn("DELETE FROM guacamole_user_group_member", group_tasks)
        self.assertIn("SELECT jsonb_array_elements_text(connection_names)", group_tasks)
        self.assertIn("CREATE TEMPORARY TABLE lit_oidc_group_input", group_tasks)
        self.assertNotIn("set_config(", group_tasks)
        self.assertIn("no_log: true", group_tasks)
        self.assertNotIn("{{ guacamole_deploy_oidc_group.", group_tasks)


if __name__ == "__main__":
    unittest.main()
