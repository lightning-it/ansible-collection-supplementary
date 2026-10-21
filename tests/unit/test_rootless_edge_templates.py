"""Rootless edge listener and TLS trust boundary regression tests."""

import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

ROOT = Path(__file__).resolve().parents[2]


class RootlessEdgeTemplates(unittest.TestCase):
    def render(self, role, name, **values):
        source = (ROOT / "roles" / role / "templates" / name).read_text()
        return (
            Environment(
                undefined=StrictUndefined,
                autoescape=select_autoescape(default=False, default_for_string=False),
            )
            .from_string(source)
            .render(**values)
        )

    def test_keycloak_management_can_be_disabled_without_exposing_application(self):
        values = dict(
            keycloak_deploy_image="example/keycloak@sha256:abc",
            keycloak_deploy_rootless_keycloak_ip="10.89.50.10",
            keycloak_deploy_config_dir="/srv/config",
            keycloak_deploy_host_data_dir="/srv/data",
        )
        enabled = self.render(
            "keycloak_deploy",
            "rootless-keycloak.container.j2",
            keycloak_deploy_rootless_publish_management=True,
            **values,
        )
        disabled = self.render(
            "keycloak_deploy",
            "rootless-keycloak.container.j2",
            keycloak_deploy_rootless_publish_management=False,
            **values,
        )
        self.assertIn("PublishPort=127.0.0.1:9000:9000", enabled)
        self.assertNotIn("PublishPort=", disabled)
        self.assertNotIn(":8080", enabled)

    def test_postgres_has_no_host_listener(self):
        rendered = self.render(
            "keycloak_deploy",
            "rootless-postgres.container.j2",
            keycloak_deploy_postgres_image="example/postgres@sha256:abc",
            keycloak_deploy_rootless_postgres_ip="10.89.50.20",
            keycloak_deploy_config_dir="/srv/config",
            keycloak_deploy_postgres_data_dir="/srv/pgdata",
        )
        self.assertNotIn("PublishPort=", rendered)
        self.assertIn("/srv/pgdata:/var/lib/postgresql/data:Z,U", rendered)

    def test_proxy_replaces_untrusted_headers_and_blocks_management(self):
        rendered = self.render(
            "nginx_deploy",
            "rootless-nginx.conf.j2",
            nginx_deploy_server_name="sso.example.invalid",
            nginx_deploy_rootless_upstream="http://10.89.50.10:8080",
            nginx_deploy_tls_host_port=443,
        )
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", rendered)
        self.assertNotIn("$proxy_add_x_forwarded_for", rendered)
        self.assertIn('proxy_set_header Forwarded "";', rendered)
        self.assertIn("location /health { return 404; }", rendered)
        self.assertIn("location /metrics { return 404; }", rendered)
        self.assertIn("ssl_protocols TLSv1.2 TLSv1.3;", rendered)


if __name__ == "__main__":
    unittest.main()
