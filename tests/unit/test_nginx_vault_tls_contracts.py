"""Security contracts for NGINX Vault-only TLS custody."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[2]
DEFAULTS = ROOT / "roles" / "nginx_config" / "defaults" / "main.yml"
ASSERTS = ROOT / "roles" / "nginx_config" / "tasks" / "assert.yml"
TASKS = ROOT / "roles" / "nginx_config" / "tasks" / "main.yml"


class NginxVaultTlsContractTests(unittest.TestCase):
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
        self.assertEqual(template.count("nginx_config_waf_location_directives"), 3)
        self.assertIn(
            "directive not in (item.extra_directives | default([]))",
            template,
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
                            "PrOxY_SeT_HeAdEr x-FoRwArDeD-fOr $proxy_add_x_forwarded_for",
                            "proxy_set_header\tX-Forwarded-For $http_x_forwarded_for",
                            'proxy_set_header "X-Forwarded-For" $http_x_forwarded_for',
                            "proxy_set_header 'X-Forwarded-Proto' $http_x_forwarded_proto",
                            r"proxy\_set_header X-Forwarded-For $http_x_forwarded_for",
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
                    r"in\clude /etc/nginx/bypass.conf",
                    "InClUdE\t/etc/nginx/bypass.conf",
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

        self.assertEqual(source.count("| lower | replace("), 4)
        self.assertEqual(source.count("| replace(\"'\", '')) in _reserved_proxy_headers"), 4)
        self.assertEqual(source.count("_single_statement and not _reserved_proxy_header"), 4)
        self.assertEqual(source.count("';' not in _directive.rstrip(';')"), 7)

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
        self.assertTrue(any("(?i:include)" in item for item in server_task["ansible.builtin.assert"]["that"]))
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
        self.assertTrue(any("(?i:include)" in item for item in task["ansible.builtin.assert"]["that"]))

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
                self.assertTrue(any("(?i:include)" in item for item in assertions))

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
        quadlet = next(task for task in systemd_block if task["name"] == "Manage the native Nginx Quadlet service")
        self.assertEqual(quadlet["ansible.builtin.include_role"]["name"], "lit.foundational.podman_systemd")
        names = [task["name"] for task in systemd_block]
        validation = names.index("Refuse unknown legacy Nginx lifecycle states")
        stage = names.index("Stage the native Nginx Quadlet before legacy shutdown")
        stop = names.index("Stop and disable the exact legacy Nginx unit before Quadlet takeover")
        self.assertLess(validation, stage)
        self.assertLess(stage, stop)


if __name__ == "__main__":
    unittest.main()
