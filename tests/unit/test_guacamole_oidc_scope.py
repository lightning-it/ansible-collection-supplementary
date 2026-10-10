"""Real offline prechecks and manifest rendering for explicit OIDC scopes."""
import unittest
import yaml
from jinja2 import Environment, StrictUndefined
import test_guacamole_oidc_username as username_tests


class GuacamoleScopeTests(unittest.TestCase):
    def test_real_scope_prechecks(self):
        harness = username_tests.GuacamoleUsernameClaimTests()
        for scope in ("openid", "openid profile", "openid email profile"):
            with self.subTest(scope=scope):
                harness.precheck({"guacamole_deploy_oidc_scope": scope}, True)
        for scope in (None, False, [], "", "profile", "openid\nemail", "openid  email"):
            with self.subTest(scope=scope):
                harness.precheck({"guacamole_deploy_oidc_scope": scope}, False)

    def test_rendered_scope_is_exact_and_absent_when_disabled(self):
        from ansible.plugins.filter.core import FilterModule
        environment = Environment(undefined=StrictUndefined, autoescape=False)
        environment.filters.update(FilterModule().filters())
        template = environment.from_string((username_tests.ROLE / "templates/guacamole-pod.yml.j2").read_text())
        variables = username_tests.GuacamoleUsernameClaimTests().variables()
        self.assertEqual(variables["guacamole_deploy_oidc_scope"], "openid email profile")
        for enabled, scope in ((True, "openid"), (True, "openid email profile"), (False, "openid")):
            pod = yaml.safe_load(template.render(dict(variables, guacamole_deploy_oidc_enabled=enabled,
                                                     guacamole_deploy_oidc_scope=scope)))
            app = next(item for item in pod["spec"]["containers"] if item["name"] == "guacamole")
            entries = {item["name"]: item["value"] for item in app["env"]}
            if enabled:
                self.assertEqual(entries["OPENID_SCOPE"], scope)
            else:
                self.assertNotIn("OPENID_SCOPE", entries)


if __name__ == "__main__":
    unittest.main()
