"""Offline username-claim contracts, not live identity or authorization acceptance."""

from __future__ import annotations

import builtins
import os
import runpy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[2]
ROLE = ROOT / "roles/guacamole_deploy"


class GuacamoleUsernameClaimTests(unittest.TestCase):
    def test_host_discovery_without_ansible_delegates_to_devtools(self) -> None:
        original_import = builtins.__import__

        def host_import(name, *args, **kwargs):
            if name == "ansible" or name.startswith("ansible."):
                raise ModuleNotFoundError("Ansible intentionally unavailable on host")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=host_import):
            namespace = runpy.run_path(__file__, run_name="host_discovery_probe")
            with patch.object(Path, "exists", return_value=False), patch("subprocess.run") as execute:
                execute.return_value = subprocess.CompletedProcess([], 0, "", "")
                suite = namespace["load_tests"](None, unittest.TestSuite(), None)
                result = unittest.TestResult()
                suite.run(result)
                self.assertEqual(result.testsRun, 1)
                self.assertEqual(result.errors, [])
                self.assertEqual(result.failures, [])
                command = execute.call_args.args[0]
                self.assertEqual(command[1], str(ROOT / "scripts/wunder-devtools-ee.sh"))
                self.assertEqual(command[3], "/workspace/tests/unit/test_guacamole_oidc_username.py")

    def variables(self) -> dict:
        return {
            **yaml.safe_load((ROLE / "defaults/main.yml").read_text()),
            "guacamole_deploy_oidc_enabled": True,
            "guacamole_deploy_oidc_authorization_endpoint": "https://idp.example.test/auth",
            "guacamole_deploy_oidc_jwks_endpoint": "https://idp.example.test/certs",
            "guacamole_deploy_oidc_issuer": "https://idp.example.test",
            "guacamole_deploy_oidc_redirect_uri": "https://access.example.test/guacamole/",
            "guacamole_deploy_secrets": {
                name: "OFFLINE_TEST_FIXTURE_ONLY" for name in ("db_password", "breakglass_password", "breakglass_salt")
            },
        }

    def precheck(self, overrides: dict, success: bool) -> None:
        play = [
            {
                "hosts": "localhost",
                "gather_facts": False,
                "vars": {**self.variables(), **overrides},
                "tasks": [{"ansible.builtin.import_tasks": str(ROLE / "tasks/assert.yml")}],
            }
        ]
        with tempfile.TemporaryDirectory(prefix="guacamole-username-") as temporary:
            path = Path(temporary) / "precheck.yml"
            path.write_text(yaml.safe_dump(play))
            config = Path(temporary) / "ansible.cfg"
            config.write_text("[defaults]\n")
            executable = shutil.which("ansible-playbook")
            self.assertIsNotNone(executable, "Pinned Devtools Ansible is required")
            result = subprocess.run(  # noqa: S603
                [executable, "-i", "localhost,", "-c", "local", str(path)],
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(config),
                    "ANSIBLE_STDOUT_CALLBACK": "default",
                    "ANSIBLE_NOCOLOR": "1",
                    "ANSIBLE_LOCAL_TEMP": str(Path(temporary) / "ansible"),
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        output = result.stdout + result.stderr
        self.assertNotIn("OFFLINE_TEST_FIXTURE_ONLY", output)
        if success:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0, output)
            self.assertIn("failed=1", output)
            self.assertNotIn("couldn't resolve module/action", output)

    def test_real_prechecks_accept_default_and_subject(self) -> None:
        for claim in ("email", "sub"):
            with self.subTest(claim=claim):
                self.precheck({"guacamole_deploy_oidc_username_claim_type": claim}, True)

    def test_real_prechecks_reject_invalid_enabled_claims(self) -> None:
        for claim in ("", "   ", None, False, 123, [], {}):
            with self.subTest(claim=claim):
                self.precheck({"guacamole_deploy_oidc_username_claim_type": claim}, False)

    def test_disabled_oidc_does_not_require_username_claim(self) -> None:
        self.precheck({"guacamole_deploy_oidc_enabled": False, "guacamole_deploy_oidc_username_claim_type": None}, True)

    def test_rendered_pod_preserves_default_and_emits_exact_subject_only_when_enabled(self) -> None:
        from ansible.plugins.filter.core import FilterModule  # noqa: PLC0415

        # This is a Kubernetes YAML template with JSON-quoted values, not HTML.
        environment = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701
        environment.filters.update(FilterModule().filters())
        template = environment.from_string((ROLE / "templates/guacamole-pod.yml.j2").read_text())
        variables = self.variables()
        self.assertEqual(variables["guacamole_deploy_oidc_username_claim_type"], "email")
        for enabled, claim in ((True, "email"), (True, "sub"), (False, "sub")):
            with self.subTest(enabled=enabled, claim=claim):
                pod = yaml.safe_load(
                    template.render(
                        {
                            **variables,
                            "guacamole_deploy_oidc_enabled": enabled,
                            "guacamole_deploy_oidc_username_claim_type": claim,
                        }
                    )
                )
                container = next(item for item in pod["spec"]["containers"] if item["name"] == "guacamole")
                entries = {item["name"]: item["value"] for item in container["env"]}
                if enabled:
                    self.assertEqual(entries["OPENID_USERNAME_CLAIM_TYPE"], claim)
                    self.assertEqual(entries["OPENID_ISSUER"], variables["guacamole_deploy_oidc_issuer"])
                    self.assertEqual(entries["EXTENSION_PRIORITY"], "*, openid")
                else:
                    self.assertNotIn("OPENID_USERNAME_CLAIM_TYPE", entries)


def load_tests(loader, tests, pattern):  # noqa: ARG001
    """Keep Ansible execution in the pinned EE even from host-side discovery."""
    if Path("/run/.containerenv").exists() or Path("/.dockerenv").exists():
        return tests

    def run_in_devtools() -> None:
        result = subprocess.run(  # noqa: S603
            [
                "/bin/bash",
                str(ROOT / "scripts/wunder-devtools-ee.sh"),
                "python3",
                "/workspace/tests/unit/test_guacamole_oidc_username.py",
                "-v",
            ],
            cwd=ROOT,
            env=dict(os.environ, WUNDER_DEVTOOLS_RUN_AS_HOST_UID="1"),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)

    return unittest.TestSuite([unittest.FunctionTestCase(run_in_devtools)])


if __name__ == "__main__":
    unittest.main()
