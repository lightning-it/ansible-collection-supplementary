"""Real prechecks and rendered manifest for a root-context Access migration."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.plugins.filter.core import FilterModule
from jinja2 import Environment, StrictUndefined

from tests.unit.test_guacamole_oidc_username import ROLE, GuacamoleUsernameClaimTests


class GuacamoleContextTests(unittest.TestCase):
    def test_actual_prechecks_reject_path_injection(self):
        harness = GuacamoleUsernameClaimTests()
        for context in ("guacamole", "ROOT", "access-service"):
            harness.precheck({"guacamole_deploy_webapp_context": context}, True)
        for context in ("", "/", "../ROOT", "ROOT/", "ROOT\n", None, False, []):
            harness.precheck({"guacamole_deploy_webapp_context": context}, False)

    def test_actual_ansible_health_and_api_urls(self):
        executable = shutil.which("ansible-playbook")
        self.assertIsNotNone(executable)
        for context, suffix in (("guacamole", "/guacamole"), ("ROOT", "")):
            variables = GuacamoleUsernameClaimTests().variables()
            variables["guacamole_deploy_webapp_context"] = context
            base = "http://127.0.0.1:8082" + suffix
            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": variables,
                    "tasks": [
                        {
                            "ansible.builtin.assert": {
                                "that": [
                                    "guacamole_deploy_health_url == " + repr(base + "/"),
                                    "guacamole_deploy_api_url == " + repr(base + "/api"),
                                ],
                                "quiet": True,
                            }
                        }
                    ],
                }
            ]
            with tempfile.TemporaryDirectory(prefix="guacamole-context-") as temporary:
                path = Path(temporary) / "verify.yml"
                path.write_text(yaml.safe_dump(play))
                config = Path(temporary) / "ansible.cfg"
                config.write_text("[defaults]\n")
                result = subprocess.run(  # noqa: S603 - pinned Ansible, synthetic fixture
                    [executable, "-i", "localhost,", "-c", "local", str(path)],
                    env={**os.environ, "ANSIBLE_CONFIG": str(config)},
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_manifest_selects_actual_context(self):
        environment = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - YAML
        environment.filters.update(FilterModule().filters())
        template = environment.from_string((ROLE / "templates/guacamole-pod.yml.j2").read_text())
        variables = GuacamoleUsernameClaimTests().variables()
        self.assertEqual(variables["guacamole_deploy_webapp_context"], "guacamole")
        for context in ("guacamole", "ROOT"):
            pod = yaml.safe_load(template.render(dict(variables, guacamole_deploy_webapp_context=context)))
            app = next(c for c in pod["spec"]["containers"] if c["name"] == "guacamole")
            entries = {e["name"]: e["value"] for e in app["env"]}
            self.assertEqual(entries["WEBAPP_CONTEXT"], context)
            self.assertEqual(entries["OPENID_REDIRECT_URI"], variables["guacamole_deploy_oidc_redirect_uri"])


if __name__ == "__main__":
    unittest.main()
