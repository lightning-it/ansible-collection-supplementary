"""Security contracts for NGINX Vault-only TLS custody."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.conditional import Conditional
from ansible.template import Templar
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "roles" / "nginx_config" / "defaults" / "main.yml"
ASSERTS = ROOT / "roles" / "nginx_config" / "tasks" / "assert.yml"
TASKS = ROOT / "roles" / "nginx_config" / "tasks" / "main.yml"


class NginxVaultTlsContractTests(unittest.TestCase):
    @staticmethod
    def _evaluate(condition: str, variables: dict) -> bool:
        loader = DataLoader()
        conditional = Conditional(loader=loader)
        conditional.when = [condition]
        return conditional.evaluate_conditional(Templar(loader=loader, variables=variables), variables)

    def _run_assert_tasks(self, names: set[str], variables: dict) -> subprocess.CompletedProcess[str]:
        tasks = [task for task in yaml.safe_load(ASSERTS.read_text(encoding="utf-8")) if task.get("name") in names]
        play = [{"hosts": "localhost", "gather_facts": False, "vars": variables, "tasks": tasks}]
        with tempfile.TemporaryDirectory(prefix="nginx-contract-") as temporary:
            root = Path(temporary)
            playbook = root / "assert.yml"
            playbook.write_text(yaml.safe_dump(play), encoding="utf-8")
            executable = shutil.which("ansible-playbook")
            self.assertIsNotNone(executable, "Pinned Devtools Ansible is required")
            return subprocess.run(  # noqa: S603 - fixed executable and generated offline fixture
                [executable, "-i", "localhost,", "-c", "local", str(playbook)],
                env={**os.environ, "ANSIBLE_NOCOLOR": "1", "ANSIBLE_LOCAL_TEMP": str(root / "ansible")},
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

    def test_local_tls_fallback_has_explicit_compatibility_switch(self) -> None:
        defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))

        self.assertIs(defaults["nginx_config_vault_allow_local_fallback"], False)
        self.assertIs(defaults["nginx_config_vault_issue_missing"], True)

    def test_waf_controls_are_rendered_at_server_and_location_boundaries(self) -> None:
        template = (ROOT / "roles" / "nginx_config" / "templates" / "vhost.conf.j2").read_text(encoding="utf-8")

        self.assertIn("nginx_config_waf_server_directives", template)
        self.assertIn("nginx_config_waf_location_directives", template)
        self.assertLess(
            template.index("nginx_config_waf_server_directives"),
            template.index("item.extra_directives"),
        )
        self.assertLess(
            template.index("nginx_config_waf_location_directives"),
            template.index("item.proxy_directives"),
        )
        self.assertEqual(template.count("nginx_config_waf_location_directives"), 2)
        self.assertIn(
            "directive not in (item.extra_directives | default([]))",
            template,
        )

    def test_waf_controls_are_limited_to_tls_proxy_vhosts(self) -> None:
        defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
        source = (ROOT / "roles" / "nginx_config" / "templates" / "vhost.conf.j2").read_text(encoding="utf-8")
        environment = Environment(autoescape=False)  # noqa: S701
        environment.filters["bool"] = bool
        template = environment.from_string(source)
        common = {
            "nginx_config_http_listen_port": 80,
            "nginx_config_tls_listen_port": 443,
            "nginx_config_tls_certificate": "/tls/tls.crt",
            "nginx_config_tls_certificate_key": "/tls/tls.key",
            "nginx_config_waf_enabled": True,
            "nginx_config_waf_server_directives": ["modsecurity on"],
            "nginx_config_waf_location_directives": ["modsecurity_rules 'SecRuleEngine On'"],
            "nginx_config_proxy_default_directives": defaults["nginx_config_proxy_default_directives"],
            "nginx_config_proxy_required_directives": defaults["nginx_config_proxy_required_directives"],
            "nginx_config_proxy_http_external_port": 80,
            "nginx_config_proxy_tls_external_port": 443,
            "nginx_deploy_listen_port": 80,
            "nginx_deploy_root": "/usr/share/nginx/html",
            "nginx_deploy_index_files": ["index.html"],
        }

        tls = template.render(
            item={"force_https": True, "server_name": "tls.invalid", "upstream_url": "http://backend"},
            **common,
        )
        http = template.render(
            item={"force_https": False, "server_name": "http.invalid", "upstream_url": "http://backend"},
            **common,
        )
        http_locations = template.render(
            item={
                "force_https": False,
                "server_name": "http-locations.invalid",
                "locations": [{"path": "/", "directives": ["proxy_pass http://backend"]}],
            },
            **common,
        )

        self.assertIn("modsecurity on;", tls)
        self.assertIn("modsecurity_rules 'SecRuleEngine On';", tls)
        self.assertNotIn("modsecurity", http)
        self.assertNotIn("modsecurity", http_locations)

    def test_shipped_playbooks_do_not_override_reserved_proxy_headers(self) -> None:
        for relative in ("playbooks/wunderbox.yml", "playbooks/wunderbox_vault.yml"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(playbook=relative):
                self.assertNotRegex(
                    source,
                    r"(?i)proxy_set_header\s+(host|x-real-ip|x-forwarded-for|x-forwarded-proto)\b",
                )

    def test_required_forwarded_headers_follow_consumer_directives(self) -> None:
        defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
        template = (ROOT / "roles" / "nginx_config" / "templates" / "vhost.conf.j2").read_text(encoding="utf-8")
        assertions = (ROOT / "roles" / "nginx_config" / "tasks" / "assert.yml").read_text(encoding="utf-8")

        boundary = defaults["nginx_config_proxy_required_directives"]
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr", boundary)
        self.assertIn("proxy_set_header X-Forwarded-Host $server_name", boundary)
        self.assertFalse(any("X-Forwarded-Port" in directive for directive in boundary))
        self.assertIn("nginx_config_proxy_http_external_port | string is match('^[0-9]+$')", assertions)
        self.assertIn("nginx_config_proxy_tls_external_port | string is match('^[0-9]+$')", assertions)
        self.assertIn('proxy_set_header Forwarded ""', boundary)
        self.assertNotIn("$proxy_add_x_forwarded_for", "\n".join(boundary))
        self.assertEqual(
            template.count("{% for directive in nginx_config_proxy_required_directives %}"),
            4,
        )
        self.assertEqual(template.count("proxy_set_header X-Forwarded-Port {{ _proxy_external_port }};"), 4)
        self.assertIn("nginx_config_proxy_required_directives == [", assertions)
        self.assertGreaterEqual(assertions.count("| map('trim')"), 2)
        custom_proxy = template.index("item.proxy_directives | default(nginx_config_proxy_default_directives)")
        required_after_custom = template.index("nginx_config_proxy_required_directives", custom_proxy)
        self.assertGreater(required_after_custom, custom_proxy)
        self.assertNotIn("{% if item.proxy_directives is defined %}", template)
        self.assertIn("item.proxy_external_port | string is match('^[0-9]+$')", assertions)

    def test_consumer_cannot_reintroduce_reserved_proxy_headers(self) -> None:
        defaults = yaml.safe_load(DEFAULTS.read_text(encoding="utf-8"))
        source = (ROOT / "roles" / "nginx_config" / "templates" / "vhost.conf.j2").read_text(encoding="utf-8")
        environment = Environment(autoescape=False)  # noqa: S701
        environment.filters["bool"] = bool
        template = environment.from_string(source)
        common = {
            "nginx_config_http_listen_port": 80,
            "nginx_config_tls_listen_port": 443,
            "nginx_config_tls_certificate": "/tls/tls.crt",
            "nginx_config_tls_certificate_key": "/tls/tls.key",
            "nginx_config_waf_enabled": False,
            "nginx_config_waf_server_directives": [],
            "nginx_config_waf_location_directives": [],
            "nginx_config_proxy_default_directives": defaults["nginx_config_proxy_default_directives"],
            "nginx_config_proxy_required_directives": defaults["nginx_config_proxy_required_directives"],
            "nginx_config_proxy_http_external_port": 18080,
            "nginx_config_proxy_tls_external_port": 18443,
            "nginx_deploy_listen_port": 8080,
            "nginx_deploy_root": "/usr/share/nginx/html",
            "nginx_deploy_index_files": ["index.html"],
        }
        attempts = (
            {
                "force_https": True,
                "server_name": "keycloak.example.invalid",
                "locations": [
                    {
                        "path": "/",
                        "directives": [
                            "proxy_http_version 1.1;\nproxy_set_header X-Forwarded-For $http_x_forwarded_for",
                            'proxy_set_header "X-Forwarded-For" $http_x_forwarded_for',
                            'proxy"_set_header" X-"Forwarded-For" $http_x_forwarded_for',
                            r"proxy\_set_header X-Forwarded-For $http_x_forwarded_for",
                            '"proxy_set_header" X-Forwarded-For $http_x_forwarded_for',
                            '"include" /etc/nginx/quoted-bypass.conf',
                            'in"clude" /etc/nginx/fragmented-bypass.conf',
                            "include /etc/nginx/bypass.conf",
                            "proxy_pass http://keycloak",
                        ],
                    }
                ],
            },
            {
                "force_https": False,
                "server_name": "guacamole.example.invalid",
                "upstream_url": "http://guacamole",
                "proxy_directives": [
                    "proxy_http_version 1.1; proxy_set_header X-Forwarded-Proto $http_x_forwarded_proto",
                    "proxy_set_header Forwarded $http_forwarded",
                    "'proxy_set_header' Forwarded $http_forwarded",
                    'proxy"_set_header" For"warded" $http_forwarded',
                    "'include' /etc/nginx/quoted-bypass.conf",
                    'in"clude" /etc/nginx/fragmented-bypass.conf',
                    "proxy_http_version 1.1",
                ],
            },
        )
        for item in attempts:
            with self.subTest(server=item["server_name"]):
                rendered = template.render(item=item, **common)
                self.assertNotIn("$proxy_add_x_forwarded_for", rendered)
                self.assertNotIn("$http_x_forwarded_for", rendered)
                self.assertNotIn("$http_x_forwarded_proto", rendered)
                self.assertNotIn("$http_forwarded", rendered)
                self.assertNotIn("bypass.conf", rendered)
                self.assertEqual(rendered.count("proxy_set_header X-Forwarded-For $remote_addr;"), 1)
                self.assertEqual(rendered.count('proxy_set_header Forwarded "";'), 1)
                expected_port = 18443 if item["force_https"] else 18080
                self.assertEqual(rendered.count(f"proxy_set_header X-Forwarded-Port {expected_port};"), 1)

        self.assertEqual(source.count("_name(_directive) != 'include'"), 6)
        self.assertEqual(source.count("== 'proxy_set_header'"), 4)
        self.assertEqual(source.count("_single_statement and not _reserved_proxy_header"), 4)
        self.assertEqual(source.count("';' not in _directive.rstrip(';')"), 6)

    def test_upstream_url_precheck_blocks_proxy_pass_injection(self) -> None:
        name = "Ensure nginx vhost definitions are valid"
        base = {
            "name": "edge",
            "server_name": "edge.example.invalid",
            "force_https": True,
            "extra_directives": [],
        }
        for upstream, success in (
            ("http://keycloak:8080", True),
            ("http://keycloak:65535", True),
            ("https://10.89.40.2:8443/realms/lit-access?x=1", True),
            ("http://keycloak:65536", False),
            ("http://keycloak:99999", False),
            ("http://backend#comment", False),
            ('http://backend"quoted', False),
            ("http://backend\\", False),
            ("http://backend;proxy_pass", False),
        ):
            result = self._run_assert_tasks(
                {name},
                {"nginx_config_vhosts_effective": [{**base, "upstream_url": upstream}], "nginx_deploy_listen_port": 80},
            )
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_waf_location_directives_cannot_override_proxy_identity(self) -> None:
        tasks = yaml.safe_load(ASSERTS.read_text(encoding="utf-8"))
        task = next(
            item
            for item in tasks
            if item.get("name") == "Reject reserved proxy identity headers in WAF location directives"
        )
        assertion = task["ansible.builtin.assert"]["that"][0]

        self.assertIn("item | trim | lower", assertion)
        self.assertIn("[ \\t]+", assertion)
        server_task = next(
            item
            for item in tasks
            if item.get("name") == "Ensure enabled WAF policy contains server and location controls"
        )
        self.assertTrue(any("include(?:" in item for item in server_task["ansible.builtin.assert"]["that"]))
        for header in (
            "host",
            "x-real-ip",
            "x-forwarded-for",
            "x-forwarded-host",
            "x-forwarded-port",
            "x-forwarded-proto",
            "x-forwarded-prefix",
            "x-original-forwarded-for",
            "forwarded",
        ):
            with self.subTest(header=header):
                self.assertIn(header, assertion)
        self.assertEqual(task["loop"], "{{ nginx_config_waf_location_directives }}")
        self.assertIn("nginx_config_waf_enabled | bool", task["when"])
        self.assertTrue(any("include(?:" in item for item in task["ansible.builtin.assert"]["that"]))
        self.assertTrue(any("\\S*[\"'']" in item for item in task["ansible.builtin.assert"]["that"]))
        self.assertIn("#", next(check for check in task["ansible.builtin.assert"]["that"] if "include(?:" in check))
        override_tasks = {item["name"] for item in tasks if "overrides of WAF" in item.get("name", "")}
        self.assertEqual(
            override_tasks,
            {
                "Reject consumer overrides of WAF server controls",
                "Reject consumer overrides of WAF location controls",
                "Reject location overrides of WAF location controls",
            },
        )

    def test_real_waf_prechecks_reject_comments_and_semantic_overrides(self) -> None:
        policy = {
            "nginx_config_waf_enabled": True,
            "nginx_config_waf_server_directives": ["modsecurity on"],
            "nginx_config_waf_location_directives": ["modsecurity_rules 'SecRuleEngine On'"],
            "nginx_config_vhosts_effective": [
                {
                    "name": "edge",
                    "force_https": True,
                    "extra_directives": ["client_max_body_size 1m"],
                    "proxy_directives": ["proxy_http_version 1.1"],
                    "locations": [{"directives": ["proxy_buffering off"]}],
                }
            ],
        }
        names = {
            "Ensure enabled WAF policy contains server and location controls",
            "Reject consumer overrides of WAF server controls",
            "Reject consumer overrides of WAF location controls",
            "Reject location overrides of WAF location controls",
        }
        result = self._run_assert_tasks(names, policy)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        invalid = (
            {"nginx_config_waf_server_directives": ["modsecurity on # policy"]},
            {
                "nginx_config_vhosts_effective": [
                    {**policy["nginx_config_vhosts_effective"][0], "extra_directives": ["modsecurity off"]}
                ]
            },
            {
                "nginx_config_vhosts_effective": [
                    {
                        **policy["nginx_config_vhosts_effective"][0],
                        "proxy_directives": ["modsecurity_rules 'SecRuleEngine Off'"],
                    }
                ]
            },
            {
                "nginx_config_vhosts_effective": [
                    {
                        **policy["nginx_config_vhosts_effective"][0],
                        "locations": [{"directives": ["modsecurity off"]}],
                    }
                ]
            },
        )
        for override in invalid:
            with self.subTest(override=override):
                result = self._run_assert_tasks(names, {**policy, **override})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_location_paths_are_literal_absolute_uri_prefixes(self) -> None:
        name = "Reject unsafe Nginx location paths"
        base = {"name": "edge", "locations": []}
        for path, success in (
            ("/", True),
            ("/realms/lit-access", True),
            ("/oauth2/callback%20safe", True),
            ("", False),
            ("relative", False),
            ("~ ^/admin", False),
            ("/safe\nlocation /bypass", False),
            ("/safe{", False),
            ('/safe"quoted', False),
        ):
            result = self._run_assert_tasks(
                {name},
                {"nginx_config_vhosts_effective": [{**base, "locations": [{"path": path}]}]},
            )
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_proxy_directive_prechecks_reject_multiple_statements(self) -> None:
        tasks = yaml.safe_load(ASSERTS.read_text(encoding="utf-8"))
        names = {
            "Reject multi-statement default proxy directives",
            "Reject multi-statement vhost proxy directives",
            "Reject multi-statement location proxy directives",
        }
        selected = [item for item in tasks if item.get("name") in names]

        self.assertEqual({item["name"] for item in selected}, names)
        for task in selected:
            with self.subTest(task=task["name"]):
                assertions = task["ansible.builtin.assert"]["that"]
                self.assertTrue(any("include(?:" in item for item in assertions))
                if task["name"] != "Reject multi-statement default proxy directives":
                    self.assertTrue(any("is sequence" in item for item in assertions))
                    self.assertTrue(any("is not string" in item for item in assertions))
        vhost = next(item for item in tasks if item.get("name") == "Ensure nginx vhost definitions are valid")
        vhost_assertions = vhost["ansible.builtin.assert"]["that"]
        self.assertTrue(any("extra_directives" in item and "is not string" in item for item in vhost_assertions))
        boundary = next(item for item in tasks if item.get("name") == "Reject block-form proxy-vhost extra directives")
        self.assertNotIn("nginx_config_waf_enabled", boundary["when"])

    def test_real_proxy_prechecks_reject_reserved_identity_headers(self) -> None:
        valid = "proxy_http_version 1.1"
        invalid = (
            "proxy_set_header X-Forwarded-For $http_x_forwarded_for",
            'proxy_set_header "Forwarded" $http_forwarded',
            'proxy_set_header X-Forwarded-Proto" $http_x_forwarded_proto',
            'proxy"_set_header" X-Forwarded-Host $http_host',
        )
        cases = (
            (
                "Reject multi-statement default proxy directives",
                lambda directive: {"nginx_config_proxy_default_directives": [directive]},
            ),
            (
                "Reject multi-statement vhost proxy directives",
                lambda directive: {
                    "nginx_config_vhosts_effective": [{"name": "edge", "proxy_directives": [directive]}]
                },
            ),
            (
                "Reject multi-statement location proxy directives",
                lambda directive: {
                    "nginx_config_vhosts_effective": [
                        {"name": "edge", "locations": [{"path": "/", "directives": [directive]}]}
                    ]
                },
            ),
        )
        for name, variables in cases:
            with self.subTest(task=name, directive=valid):
                result = self._run_assert_tasks({name}, variables(valid))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for directive in invalid:
                with self.subTest(task=name, directive=directive):
                    result = self._run_assert_tasks({name}, variables(directive))
                    self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pki_inputs_are_required_only_when_issuance_is_enabled(self) -> None:
        tasks = yaml.safe_load(ASSERTS.read_text(encoding="utf-8"))
        task = next(
            item for item in tasks if item.get("name") == "Ensure Vault PKI issue inputs are present when enabled"
        )

        self.assertIn("not nginx_deploy_skip_config | bool", task["when"])
        self.assertIn("nginx_config_vault_issue_missing | bool", task["when"])
        assertions = task["ansible.builtin.assert"]["that"]
        self.assertTrue(any("nginx_config_vault_pki_path" in item for item in assertions))
        self.assertTrue(any("nginx_config_vault_pki_role" in item for item in assertions))

    def test_host_files_require_explicit_migration_fallback(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        fallback_tasks = [
            item
            for item in tasks
            if item.get("name")
            in {
                "Read local TLS certificate fallback",
                "Read local TLS private key fallback",
                "Set local TLS fallback content",
            }
        ]

        self.assertEqual(len(fallback_tasks), 3)
        for task in fallback_tasks:
            with self.subTest(task=task["name"]):
                self.assertIn(
                    "nginx_config_vault_allow_local_fallback | bool",
                    task["when"],
                )

    def test_stored_vault_identity_is_complete_when_pki_issue_is_disabled(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        task = next(
            item
            for item in tasks
            if item.get("name") == "Require a complete stored Vault TLS identity when issuance is disabled"
        )
        assertions = task["ansible.builtin.assert"]["that"]

        self.assertIn(
            "nginx_config_vault_cert_present | default(false) | bool",
            assertions,
        )
        self.assertIn(
            "nginx_config_vault_cert_identity_match | default(false) | bool",
            assertions,
        )
        self.assertIn(
            "nginx_config_vault_cert_ca_chain_stored | default([], true) | length > 0",
            assertions,
        )
        self.assertIn("not (nginx_config_vault_issue_missing | bool)", task["when"])

    def test_private_key_is_installed_with_mode_0600(self) -> None:
        tasks = yaml.safe_load(TASKS.read_text(encoding="utf-8"))
        task = next(item for item in tasks if item.get("name") == "Write TLS private key from Vault")

        self.assertEqual(task["ansible.builtin.copy"]["mode"], "0600")
        self.assertEqual(task["no_log"], "{{ nginx_config_tls_no_log }}")

    def test_nginx_lifecycle_has_one_persistent_controller(self) -> None:
        pod_tasks_path = ROOT / "roles" / "nginx_deploy" / "tasks" / "deploy_pod.yml"
        pod_tasks = yaml.safe_load(pod_tasks_path.read_text(encoding="utf-8"))
        recreate = next(task for task in pod_tasks if task["name"] == "Recreate Nginx pod from the desired manifest")
        self.assertEqual(recreate["vars"]["kubeplay_action"], "recreate")
        self.assertIn("not nginx_deploy_manage_systemd | bool", recreate["when"])
        systemd_tasks = yaml.safe_load(
            (ROOT / "roles" / "nginx_deploy" / "tasks" / "systemd.yml").read_text(encoding="utf-8")
        )
        self.assertIn("not ansible_check_mode", systemd_tasks[0]["when"])
        systemd_block = systemd_tasks[0]["block"]
        cutover = next(
            task for task in systemd_block if task["name"] == "Cut over to native Nginx Quadlet with rollback"
        )
        quadlet = next(task for task in cutover["block"] if task["name"] == "Manage the native Nginx Quadlet service")
        self.assertEqual(quadlet["ansible.builtin.include_role"]["name"], "lit.foundational.podman_systemd")
        names = [task["name"] for task in systemd_block]
        validation = names.index("Refuse unknown Nginx lifecycle states")
        collision = names.index("Refuse unmanaged Nginx pod; remove it first")
        drift = names.index("Refuse unproven drift in an existing native Nginx Quadlet")
        self.assertIn("nginx_deploy_native_systemd_active", systemd_block[collision]["failed_when"])
        stage = names.index("Stage the native Nginx Quadlet before legacy shutdown")
        takeover = names.index("Cut over to native Nginx Quadlet with rollback")
        self.assertLess(validation, stage)
        self.assertLess(validation, collision)
        self.assertLess(validation, drift)
        self.assertLess(drift, collision)
        self.assertLess(collision, stage)
        self.assertLess(stage, takeover)
        rescue = {task["name"]: task for task in cutover["rescue"]}
        self.assertIn("Capture the original native Nginx takeover failure", rescue)
        cleanup_guard = rescue["Attempt failed native Nginx cleanup without blocking restoration"]
        cleanup = cleanup_guard["block"][0]
        self.assertEqual(cleanup["vars"]["podman_systemd_action"], "absent")
        self.assertIn("native_quadlet_file.stat.exists", cleanup["when"])
        self.assertEqual(
            cleanup_guard["rescue"][0]["name"],
            "Capture failed native Nginx cleanup",
        )
        native_restore_guard = rescue[
            "Attempt pre-existing native Nginx restoration without blocking legacy restoration"
        ]
        native_restore = {task["name"]: task for task in native_restore_guard["block"]}
        restore_enablement = native_restore[
            "Restore pre-existing enabled or disabled native Nginx service state after failure"
        ]
        self.assertIn("['enabled', 'disabled']", restore_enablement["when"])
        self.assertIn("== 'enabled'", restore_enablement["ansible.builtin.systemd"]["enabled"])
        self.assertEqual(
            restore_enablement["ansible.builtin.systemd"]["scope"],
            "{{ nginx_deploy_systemd_scope }}",
        )
        restore_generated = native_restore["Restore pre-existing generated native Nginx service state after failure"]
        self.assertIn("== 'generated'", restore_generated["when"])
        self.assertNotIn("enabled", restore_generated["ansible.builtin.systemd"])
        self.assertEqual(
            restore_generated["ansible.builtin.systemd"]["scope"],
            "{{ nginx_deploy_systemd_scope }}",
        )
        self.assertEqual(
            native_restore_guard["rescue"][0]["name"],
            "Capture failed pre-existing native Nginx restoration",
        )
        legacy_restore_guard = rescue["Attempt exact legacy Nginx restoration after failed takeover"]
        self.assertEqual(
            legacy_restore_guard["block"][0]["name"],
            "Restore the exact legacy Nginx unit after failed takeover",
        )
        self.assertEqual(
            legacy_restore_guard["rescue"][0]["name"],
            "Capture failed legacy Nginx restoration",
        )
        self.assertIn("Report failed native Nginx takeover after rollback", rescue)

        update_guard = next(
            task
            for task in systemd_block
            if task["name"] == "Refuse non-transactional updates of an existing native Nginx unit"
        )
        self.assertIn("nginx_deploy_kubeplay_run", update_guard["ansible.builtin.assert"]["that"][0])
        update_condition = update_guard["ansible.builtin.assert"]["that"][0]
        for native, remove, run, allowed in (
            ("active", False, False, True),
            ("inactive", False, False, True),
            ("failed", False, False, True),
            ("inactive", True, False, False),
            ("failed", False, True, False),
        ):
            variables = {
                "nginx_deploy_native_systemd_enabled": {"stdout": "generated"},
                "nginx_deploy_native_systemd_active": {"stdout": native},
                "nginx_deploy_kubeplay_remove": remove,
                "nginx_deploy_kubeplay_run": run,
            }
            with self.subTest(native=native, remove=remove, run=run):
                self.assertEqual(self._evaluate(update_condition, variables), allowed)

        self.assertIn("['inactive', 'failed']", quadlet["when"])

        drift_guard = systemd_block[drift]
        self.assertIn("native_quadlet_file.stat.exists", drift_guard["when"])
        self.assertIn("!= 'not-found'", drift_guard["when"])
        drift_assertions = drift_guard["ansible.builtin.assert"]["that"]
        desired_lines = [
            "[Unit]",
            "Description=Nginx container service",
            "After=network-online.target",
            "Wants=network-online.target",
            "",
            "[Kube]",
            "Yaml=/srv/nginx/nginx-pod.yml",
            "Network=lit-private",
            "",
            "[Install]",
            "WantedBy=multi-user.target",
        ]
        variables = {
            "nginx_deploy_native_quadlet_file": {"stat": {"exists": True, "isreg": True, "islnk": False}},
            "nginx_deploy_native_quadlet_read": {
                "content": base64.b64encode(("\n".join(desired_lines) + "\n").encode()).decode()
            },
            "nginx_deploy_systemd_description": "Nginx container service",
            "nginx_deploy_pod_manifest_path": "/srv/nginx/nginx-pod.yml",
            "nginx_deploy_networks": ["lit-private"],
            "nginx_deploy_systemd_enabled": True,
            "nginx_deploy_native_systemd_enabled": {"stdout": "generated"},
        }
        self.assertTrue(all(self._evaluate(check, variables) for check in drift_assertions))
        drifted = {**variables, "nginx_deploy_networks": ["unexpected-network"]}
        self.assertFalse(all(self._evaluate(check, drifted) for check in drift_assertions))

        file_exists_unit_not_found = {
            **variables,
            "nginx_deploy_native_systemd_enabled": {"stdout": "not-found"},
        }
        self.assertTrue(self._evaluate(drift_guard["when"], file_exists_unit_not_found))

        lifecycle_assertions = systemd_block[validation]["ansible.builtin.assert"]["that"]
        collision_condition = systemd_block[collision]["failed_when"]
        cases = (
            ((3, "inactive", 3, "inactive", 1), (True, False)),
            ((0, "active", 3, "inactive", 0), (True, False)),
            ((3, "inactive", 0, "active", 0), (True, False)),
            ((3, "inactive", 3, "inactive", 0), (True, True)),
            ((3, "inactive", 2, "activating", 1), (False, False)),
            ((3, "inactive", 3, "inactive", 1, "linked"), (False, False)),
        )
        for values, expected in cases:
            legacy_rc, legacy, native_rc, native, pod_rc, *enablement = values
            variables = {
                "nginx_deploy_legacy_systemd_active": {"rc": legacy_rc, "stdout": legacy},
                "nginx_deploy_legacy_systemd_enabled": {"rc": 1, "stdout": enablement[0] if enablement else "disabled"},
                "nginx_deploy_native_systemd_active": {"rc": native_rc, "stdout": native},
                "nginx_deploy_native_systemd_enabled": {
                    "rc": 0 if native == "active" else 1,
                    "stdout": "enabled" if native == "active" else "not-found",
                },
                "nginx_deploy_existing_pod": {"rc": pod_rc},
            }
            valid = all(self._evaluate(check, variables) for check in lifecycle_assertions)
            self.assertEqual((valid, self._evaluate(collision_condition, variables)), expected)

        deploy_asserts = yaml.safe_load(
            (ROOT / "roles" / "nginx_deploy" / "tasks" / "assert.yml").read_text(encoding="utf-8")
        )[0]["ansible.builtin.assert"]["that"]
        self.assertEqual(sum("not (nginx_deploy_manage_systemd | bool)" in item for item in deploy_asserts), 5)
        self.assertTrue(any("nginx_deploy_systemd_scope == 'system'" in item for item in deploy_asserts))
        description_assertion = next(
            item for item in deploy_asserts if "nginx_deploy_systemd_description is string" in item
        )
        for description, valid in (
            ("Nginx container service", True),
            ("Nginx\nAfter=network-online.target", False),
            ("Nginx\rWantedBy=multi-user.target", False),
        ):
            with self.subTest(description=description):
                self.assertEqual(
                    self._evaluate(
                        description_assertion,
                        {
                            "nginx_deploy_manage_systemd": True,
                            "nginx_deploy_systemd_description": description,
                        },
                    ),
                    valid,
                )
        unit_assertion = next(item for item in deploy_asserts if "nginx_deploy_systemd_unit_name is string" in item)
        for unit_name, valid in (
            ("nginx", True),
            ("nginx-edge_1", True),
            ("../other", False),
            ("nested/unit", False),
            ("nginx\nother", False),
            (".hidden", False),
        ):
            with self.subTest(unit_name=unit_name):
                self.assertEqual(
                    self._evaluate(
                        unit_assertion,
                        {"nginx_deploy_manage_systemd": True, "nginx_deploy_systemd_unit_name": unit_name},
                    ),
                    valid,
                )

    def test_foundational_dependency_floor_supports_quadlet_networks(self) -> None:
        galaxy = yaml.safe_load((ROOT / "galaxy.yml").read_text(encoding="utf-8"))
        source_dependencies = yaml.safe_load((ROOT / "meta" / "source-dependencies.yml").read_text(encoding="utf-8"))
        source_requirement = next(
            item["requirement"] for item in source_dependencies["collections"] if item["name"] == "lit.foundational"
        )

        self.assertEqual(galaxy["dependencies"]["lit.foundational"], ">=1.35.0")
        self.assertEqual(source_requirement, ">=1.35.0")


if __name__ == "__main__":
    unittest.main()
