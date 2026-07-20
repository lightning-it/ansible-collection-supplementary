"""Keep shared Keycloak reports attributable to individual registry roles."""

from __future__ import annotations

import ast
import base64
import importlib.util
import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).parents[2]
EVIDENCE_ROLES = {"keycloak_cac", "keycloak_deploy"}


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        prefix = _decorator_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


class KeycloakEvidenceProducerTests(unittest.TestCase):
    @staticmethod
    def _browser_inventory_module():
        path = ROOT / "molecule" / "shared" / "keycloak" / "acceptance" / "browser_inventory.py"
        spec = importlib.util.spec_from_file_location("keycloak_browser_inventory", path)
        if spec is None or spec.loader is None:  # pragma: no cover - import invariant
            raise RuntimeError(f"unable to import {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_tiny_and_heavy_junit_assign_every_case_to_one_role(self) -> None:
        for scenario in ("keycloak-tiny", "keycloak-heavy"):
            source = (ROOT / "molecule" / scenario / "verify.yml").read_text(encoding="utf-8")
            match = re.search(r"<\?xml.*?</testsuite>", source, re.DOTALL)
            self.assertIsNotNone(match, f"{scenario} has no embedded JUnit document")
            assert match is not None
            # The parsed XML is a literal repository fixture, not external input.
            suite = ET.fromstring(match.group(0))  # noqa: S314
            cases = suite.findall("testcase")
            self.assertGreater(len(cases), 1)
            roles = [case.attrib.get("role", "") for case in cases]
            self.assertTrue(all(role in EVIDENCE_ROLES for role in roles))
            self.assertEqual(set(roles), EVIDENCE_ROLES)

    def test_heavy_idempotence_junit_is_bound_to_observed_module_change_results(self) -> None:
        role_task = (ROOT / "roles" / "keycloak_cac" / "tasks" / "cac_14_roles.yml").read_text(encoding="utf-8")
        verify = (ROOT / "molecule" / "keycloak-heavy" / "verify.yml").read_text(encoding="utf-8")
        self.assertIn("register: keycloak_cac_role_reconciliation", role_task)
        self.assertIn("keycloak_heavy_cac_idempotence_results", verify)
        self.assertIn("selectattr('changed', 'defined')", verify)
        self.assertIn("keycloak_cac_second_pass_changed", verify)
        self.assertIn("Record an observed CaC idempotence failure in Heavy JUnit", verify)
        self.assertIn("Enforce the observed zero-change CaC reconciliation after writing evidence", verify)
        self.assertLess(
            verify.index("Write meaningful Heavy JUnit results"),
            verify.index("Enforce the observed zero-change CaC reconciliation after writing evidence"),
        )

    def test_keycloak_failure_redaction_handles_missing_or_empty_admin_password(self) -> None:
        for task_name in ("cac_14_roles.yml", "cac_15_users.yml"):
            source = (ROOT / "roles" / "keycloak_cac" / "tasks" / task_name).read_text(encoding="utf-8")
            self.assertIn("keycloak_cac_admin_password | default('') | string", source)
            self.assertIn("failure_secret | length > 0", source)
            self.assertIn("| string", source)

    def test_heavy_proves_exact_restore_tls_trust_and_scoped_denial(self) -> None:
        converge = (ROOT / "molecule" / "keycloak-heavy" / "converge.yml").read_text(encoding="utf-8")
        verify = (ROOT / "molecule" / "keycloak-heavy" / "verify.yml").read_text(encoding="utf-8")
        self.assertIn("backup-baseline-v1", converge)
        self.assertIn("postgres_backup_restore_extra_pg_dump_args:", converge)
        self.assertIn("- --table=public.molecule_restore_probe", converge)
        self.assertIn("Destructively replace only the isolated restore-probe state", verify)
        self.assertIn("Empty only the isolated restore-probe table before data restore", verify)
        self.assertIn("postgres_backup_restore_action: restore", verify)
        self.assertIn("postgres_backup_restore_clean: false", verify)
        self.assertIn("- --data-only", verify)
        self.assertIn("(keycloak_heavy_restore_after.stdout | trim)", verify)
        self.assertIn("== (keycloak_heavy_restore_before.stdout | trim)", verify)
        self.assertIn("-verify_return_error", verify)
        self.assertIn("-verify_hostname", verify)
        self.assertIn("LDAPTLS_REQCERT: demand", verify)
        self.assertNotIn("LDAPTLS_REQCERT: never", verify)
        self.assertIn("status_code: 403", verify)
        self.assertIn("keycloak_heavy_cac_after_denial.json.description == 'reconciled-state'", verify)
        self.assertNotIn("Record expected unprivileged CaC denial", verify)
        self.assertIn("unprivileged-403-state-unchanged", verify)
        self.assertIn("postgres-isolated-restore-exact-state", verify)

    def test_heavy_ldap_provider_uses_the_declared_host_network(self) -> None:
        converge = (ROOT / "molecule" / "keycloak-heavy" / "converge.yml").read_text(encoding="utf-8")
        self.assertIn("keycloak_deploy_host_network: true", converge)
        self.assertIn("connection_url: ldaps://127.0.0.1:1636", converge)
        self.assertNotIn("connection_url: ldaps://host.containers.internal:1636", converge)
        self.assertIn("KC_TRUSTSTORE_PATHS: /opt/keycloak/data/trust/ldap-ca.crt", converge)
        self.assertIn("use_truststore_spi: always", converge)
        self.assertIn("Install the ephemeral LDAP CA in the Keycloak trust directory", converge)

    def test_keycloak_evidence_collects_immutable_image_inventory(self) -> None:
        shared = (ROOT / "molecule" / "shared" / "incus" / "collect-evidence.yml").read_text(encoding="utf-8")
        self.assertIn("- images\n      - --all\n      - --format\n      - json", shared)
        self.assertIn("if item.molecule_incus_evidence_command.name == 'podman-inventory'", shared)
        structured_input = (
            "item.stdout | default('')\n        if item.molecule_incus_evidence_command.name == 'podman-inventory'"
        )
        self.assertIn(structured_input, shared)
        self.assertIn("['--json-document']", shared)
        self.assertIn("selectattr('item.rc', 'equalto', 0)", shared)
        self.assertIn("Require successful redaction for each available structured inventory stream", shared)
        self.assertIn("selectattr('rc', 'equalto', 0)", shared)
        self.assertIn("molecule_incus_evidence_runtime_inventory_candidates | length > 0", shared)
        for scenario in ("keycloak-tiny", "keycloak-heavy", "keycloak-application-acceptance"):
            cleanup = (ROOT / "molecule" / scenario / "cleanup.yml").read_text(encoding="utf-8")
            self.assertIn("- images\n          - --all\n          - --format\n          - json", cleanup)
            self.assertNotIn("- ps\n          - --all\n          - --format\n          - json", cleanup)

    def test_acceptance_tests_have_one_supported_role_marker(self) -> None:
        source = (ROOT / "molecule" / "shared" / "keycloak" / "acceptance" / "test_acceptance.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        observed: set[str] = set()
        test_count = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            test_count += 1
            markers = [
                decorator
                for decorator in node.decorator_list
                if _decorator_name(decorator) == "pytest.mark.evidence_role"
            ]
            self.assertEqual(len(markers), 1, f"{node.name} needs exactly one evidence role")
            marker = markers[0]
            self.assertIsInstance(marker, ast.Call)
            assert isinstance(marker, ast.Call)
            self.assertEqual(len(marker.args), 1, f"{node.name} role marker must have one value")
            value = marker.args[0]
            self.assertIsInstance(value, ast.Constant)
            assert isinstance(value, ast.Constant)
            role = value.value
            self.assertIn(role, EVIDENCE_ROLES)
            observed.add(str(role))
        self.assertGreater(test_count, 1)
        self.assertEqual(observed, EVIDENCE_ROLES)

    def test_acceptance_jwt_tamper_changes_nonterminal_signature_bytes(self) -> None:
        source = (ROOT / "molecule" / "shared" / "keycloak" / "acceptance" / "test_acceptance.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("replacement + signature[1:]", source)
        self.assertIn("_b64url_decode(tampered_signature) != _b64url_decode(signature)", source)
        self.assertNotIn("token[:-1]", source)

    def test_tiny_jwt_payload_decode_handles_unpadded_urlsafe_segments(self) -> None:
        verify = (ROOT / "molecule" / "keycloak-tiny" / "verify.yml").read_text(encoding="utf-8")
        self.assertIn("base64.urlsafe_b64decode", verify)
        self.assertIn("'=' * (-len(segment) % 4)", verify)
        self.assertNotIn("| b64decode", verify)

        encoded = base64.urlsafe_b64encode(b"\xfb\xff").decode().rstrip("=")
        self.assertTrue({"-", "_"} & set(encoded))
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        self.assertEqual(b"\xfb\xff", decoded)

    def test_application_acceptance_reports_an_independent_cac_lifecycle(self) -> None:
        verify = (ROOT / "molecule" / "keycloak-application-acceptance" / "verify.yml").read_text(encoding="utf-8")
        self.assertIn("molecule-acceptance-cac-lifecycle", verify)
        self.assertIn("Apply an independently named Acceptance CaC lifecycle role", verify)
        self.assertIn("Mutate the Acceptance CaC lifecycle role through the collection role", verify)
        self.assertIn("keycloak_acceptance_cac_idempotence_passed", verify)
        self.assertIn("Delete the Acceptance CaC lifecycle role through the collection role", verify)
        self.assertIn("keycloak-application-acceptance-cac.xml", verify)
        self.assertIn('<property name="role" value="keycloak_cac"/>', verify)
        self.assertIn('<property name="commit_sha" value="{{ keycloak_acceptance_source_commit }}"/>', verify)
        self.assertIn('<property name="run_attempt" value="{{ keycloak_acceptance_run_attempt }}"/>', verify)
        self.assertIn("lookup('ansible.builtin.env', 'GITHUB_RUN_ATTEMPT')", verify)
        self.assertIn("and a positive run attempt", verify)
        self.assertLess(
            verify.index("Write independently reported Acceptance CaC lifecycle JUnit"),
            verify.index("Enforce independently reported Acceptance CaC lifecycle results"),
        )
        self.assertLess(
            verify.index("Enforce independently reported Acceptance CaC lifecycle results"),
            verify.index("Package acceptance evidence without secret-bearing runtime inputs"),
        )

    def test_acceptance_inventories_the_exact_playwright_browser_runtime(self) -> None:
        verify = (ROOT / "molecule" / "keycloak-application-acceptance" / "verify.yml").read_text(encoding="utf-8")
        helper = (ROOT / "molecule" / "shared" / "keycloak" / "acceptance" / "browser_inventory.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("browser_inventory.py", verify)
        self.assertIn("browser-runtime-keycloak-acceptance-target.json", verify)
        self.assertIn("playwright install --with-deps chrome", verify)
        self.assertIn("--browser-channel", verify)
        self.assertIn("/opt/google/chrome/chrome", verify)
        self.assertNotIn("creates: /root/.cache/ms-playwright", verify)
        self.assertIn('browser_channel != "chrome"', helper)
        self.assertIn('"dpkg-query"', helper)
        self.assertIn('"rpm"', helper)
        self.assertIn("platform.freedesktop_os_release", helper)
        self.assertIn("${source:Package}", helper)
        self.assertNotIn("${binary:Package}", helper)
        self.assertIn('"sha256": _sha256(executable)', helper)
        self.assertIn('"channel": browser_channel', helper)

    def test_browser_inventory_accepts_only_playwright_browser_version_formats(self) -> None:
        module = self._browser_inventory_module()
        self.assertEqual("150.0.7871.125", module._browser_version("Google Chrome 150.0.7871.125", channel="chrome"))
        for output in (
            "Google Chrome for Testing 149.0.7827.55 extra",
            "Chromium 149.0.7827.55\nmalformed",
        ):
            with self.subTest(output=output), self.assertRaisesRegex(RuntimeError, "unexpected Playwright Chromium"):
                module._browser_version(output, channel="chrome")
        with self.assertRaisesRegex(ValueError, "unsupported Playwright browser channel"):
            module._browser_version("Chromium 149.0.7827.55", channel="chromium")

    def test_browser_inventory_binds_distro_and_source_package_identity(self) -> None:
        module = self._browser_inventory_module()
        with patch.object(
            module.platform,
            "freedesktop_os_release",
            return_value={"ID": "ubuntu", "VERSION_ID": "24.04"},
        ):
            self.assertEqual(
                {"id": "ubuntu", "version_id": "24.04", "distro": "ubuntu-24.04"},
                module._operating_system("ubuntu-24.04"),
            )
            with self.assertRaisesRegex(RuntimeError, "differs from operating system"):
                module._operating_system("rhel-9")
        with patch.object(
            module,
            "_run",
            return_value=(
                "config-files\tremoved-demo\t1.0\tamd64\t\t\n"
                "installed\tlibc6\t2.39-0ubuntu8.4\tamd64\tglibc\t2.39-0ubuntu8.4\n"
            ),
        ):
            self.assertEqual(
                [
                    {
                        "name": "libc6",
                        "version": "2.39-0ubuntu8.4",
                        "architecture": "amd64",
                        "source_name": "glibc",
                        "source_version": "2.39-0ubuntu8.4",
                    }
                ],
                module._os_packages("ubuntu"),
            )
        with patch.object(
            module,
            "_run",
            return_value=(
                "gpg-pubkey\tfd431d51-4ae0493b\t(none)\t(none)\t0\nbash\t5.2-1.el9\tx86_64\tbash-5.2-1.el9.src.rpm\t0\n"
            ),
        ):
            packages = module._os_packages("rhel")
            self.assertEqual(["bash"], [package["name"] for package in packages])
            self.assertEqual("bash", packages[0]["source_name"])
            self.assertEqual("5.2-1.el9", packages[0]["source_version"])

        with patch.object(
            module,
            "_run",
            return_value="mod_ssl\t2.4.62-13.el9\tx86_64\thttpd-2.4.62-13.el9.src.rpm\t1\n",
        ):
            package = module._os_packages("rhel")[0]
            self.assertEqual("1:2.4.62-13.el9", package["version"])
            self.assertEqual("httpd", package["source_name"])
            self.assertEqual("2.4.62-13.el9", package["source_version"])

        with patch.object(
            module,
            "_run",
            return_value="demo\t1.0-1.el9\tx86_64\tnot-a-source-rpm\t0\n",
        ):
            with self.assertRaisesRegex(RuntimeError, "exact source-RPM identity"):
                module._os_packages("rhel")

    def test_acceptance_fixture_writes_junit_and_allure_role_identity(self) -> None:
        fixture = (ROOT / "molecule" / "shared" / "keycloak" / "acceptance" / "conftest.py").read_text(encoding="utf-8")
        tree = ast.parse(fixture)
        calls = {_decorator_name(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)}
        self.assertIn("config.addinivalue_line", calls)
        self.assertIn("record_property", calls)
        self.assertIn("allure.dynamic.label", calls)

    def test_acceptance_oidc_state_is_server_side_and_session_identifier_rotates(self) -> None:
        source = (ROOT / "molecule" / "shared" / "keycloak" / "acceptance" / "protected_app.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
        self.assertIn("BoundedMemorySessionInterface", classes)
        self.assertIn("ServerSideSession", classes)
        self.assertIn("app.session_interface = server_sessions", source)
        self.assertIn('SESSION_COOKIE_NAME="oidc_acceptance_sid"', source)
        self.assertIn("server_sessions.rotate", source)
        self.assertLess(source.index("server_sessions.rotate"), source.index('session["id_token"]'))
        self.assertIn("current.sid", source)
        self.assertNotIn("SecureCookieSession", source)

    def test_acceptance_failure_trace_starts_before_journey_and_is_sanitized(self) -> None:
        source = (ROOT / "molecule" / "shared" / "keycloak" / "acceptance" / "conftest.py").read_text(encoding="utf-8")
        self.assertIn("diagnostic_context = browser.new_context", source)
        self.assertIn("diagnostic_context.cookies()", source)
        self.assertIn("_diagnostic_html", source)
        self.assertIn("context.tracing.start(screenshots=False, snapshots=False, sources=False)", source)
        self.assertLess(source.index("context.tracing.start"), source.index("yield page"))
        self.assertIn("sanitize_trace", source)
        self.assertNotIn("diagnostic_context.tracing.start", source)
        self.assertNotIn("page.reload", source)
        self.assertNotIn("response.request.headers", source)
        self.assertNotIn("response.body", source)

    def test_trace_sanitizer_removes_network_cookie_token_and_input_material(self) -> None:
        sanitizer_path = ROOT / "molecule" / "shared" / "keycloak" / "acceptance" / "trace_sanitizer.py"
        spec = importlib.util.spec_from_file_location("keycloak_trace_sanitizer", sanitizer_path)
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        sanitizer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sanitizer)
        password = "known-password-material"  # noqa: S105 - synthetic sanitizer fixture
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ2aWV3ZXIifQ.abcdefghijklmnop"  # noqa: S105
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw.zip"
            destination = root / "safe.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr(
                    "trace.trace",
                    "\n".join(
                        (
                            json.dumps(
                                {
                                    "type": "before",
                                    "apiName": "locator.fill",
                                    "params": {"selector": "#password", "value": password},
                                    "url": "https://id.example/callback?code=authorization-code",
                                    "headers": {"Cookie": "oidc_acceptance_sid=private-cookie"},
                                }
                            ),
                            json.dumps({"type": "after", "token": token, "message": f"Bearer {token}"}),
                        )
                    ),
                )
                archive.writestr("trace.network", "Cookie: oidc_acceptance_sid=private-cookie")
                archive.writestr("resources/body", token)
                archive.writestr("trace.stacks", json.dumps({"files": ["test_acceptance.py"]}))

            sanitizer.sanitize_trace(source, destination, secrets=(password,))

            with zipfile.ZipFile(destination) as archive:
                self.assertEqual({"trace.trace", "trace.stacks"}, set(archive.namelist()))
                rendered = b"".join(archive.read(name) for name in archive.namelist()).decode("utf-8")
            self.assertIn("locator.fill", rendered)
            self.assertIn("https://id.example/callback", rendered)
            for forbidden in (password, token, "authorization-code", "private-cookie", "?code="):
                self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
