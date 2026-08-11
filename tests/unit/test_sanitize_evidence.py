"""Regression tests for controller-side Incus evidence redaction."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import secrets
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[2] / "molecule" / "shared" / "incus" / "helpers" / "sanitize_evidence.py"
SPEC = importlib.util.spec_from_file_location("sanitize_evidence", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
SANITIZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SANITIZER)


class SanitizeEvidenceTests(unittest.TestCase):
    def test_redacts_structured_name_value_credentials(self) -> None:
        credential_value = secrets.token_urlsafe(24)
        client_token = secrets.token_urlsafe(24)
        source = {
            "records": [
                {"name": "password", "value": credential_value},
                {"key": "client_token", "content": client_token},
            ],
            "safe": "retained",
        }
        serialized = json.dumps(source)
        self.assertIn(credential_value, serialized)
        self.assertIn(client_token, serialized)

        result = json.loads(SANITIZER.sanitize(serialized, []))

        self.assertEqual(result["records"][0]["value"], "[REDACTED]")
        self.assertEqual(result["records"][1]["content"], "[REDACTED]")
        self.assertEqual(result["safe"], "retained")
        rendered = json.dumps(result)
        self.assertNotIn(credential_value, rendered)
        self.assertNotIn(client_token, rendered)

    def test_redacts_sensitive_json_keys_recursively(self) -> None:
        basic_payload = base64.b64encode(f"fixture:{secrets.token_urlsafe(24)}".encode()).decode()
        source = {"nested": {"authorization": f"Basic {basic_payload}"}}
        self.assertIn(basic_payload, json.dumps(source))

        result = json.loads(SANITIZER.sanitize(json.dumps(source), []))

        self.assertEqual(result["nested"]["authorization"], "[REDACTED]")
        self.assertNotIn(basic_payload, json.dumps(result))

    def test_json_redaction_preserves_valid_escaped_content(self) -> None:
        quoted_token = f"{secrets.token_urlsafe(24)}\\value"
        source = {
            "images": [
                {
                    "name": "registry.example/keycloak:26",
                    "annotation": f'token="{quoted_token}"',
                }
            ]
        }

        serialized = json.dumps(source)
        self.assertIn(quoted_token.replace("\\", "\\\\"), serialized)
        rendered = SANITIZER.sanitize(serialized, [])
        result = json.loads(rendered)

        self.assertEqual(result["images"][0]["name"], "registry.example/keycloak:26")
        self.assertEqual(result["images"][0]["annotation"], "token=[REDACTED]")
        self.assertNotIn(quoted_token, rendered)

    def test_json_document_mode_extracts_payload_after_command_diagnostic(self) -> None:
        source = 'level=warning msg="runtime notice"\n[{"Id":"sha256:abc"}]\n'

        rendered = SANITIZER.sanitize(source, [], require_json=True)

        self.assertEqual(json.loads(rendered), [{"Id": "sha256:abc"}])

    def test_json_document_mode_rejects_non_json_input(self) -> None:
        with self.assertRaises(ValueError):
            SANITIZER.sanitize("runtime warning only", [], require_json=True)

    def test_json_document_mode_normalizes_null_inventory(self) -> None:
        self.assertEqual("[]\n", SANITIZER.sanitize("null\n", [], require_json=True))

    def test_json_document_mode_collects_json_lines_as_array(self) -> None:
        rendered = SANITIZER.sanitize('{"Id":"one"}\n{"Id":"two"}\n', [], require_json=True)
        self.assertEqual([{"Id": "one"}, {"Id": "two"}], json.loads(rendered))

    def test_json_document_mode_prefers_complete_document_over_nested_array(self) -> None:
        source = 'warning: inspect output follows\n{"Config":{"Entrypoint":["/catatonit","-P"]},"Id":"sha256:abc"}\n'
        rendered = SANITIZER.sanitize(source, [], require_json=True)
        self.assertEqual("sha256:abc", json.loads(rendered)["Id"])

    def test_redacts_exact_environment_value_and_credential_shapes(self) -> None:
        fixture_nonce = secrets.token_urlsafe(24)
        credential_fixture = f"credential-{fixture_nonce}"
        environment_fixture = f"environment-{fixture_nonce}"
        synthetic_bearer_token = (
            f"eyJ{secrets.token_urlsafe(12)}.{secrets.token_urlsafe(12)}.{secrets.token_urlsafe(12)}"
        )
        source = (
            f"password={credential_fixture}\nAuthorization: Bearer {synthetic_bearer_token}\n{environment_fixture}\n"
        )
        for fixture in (credential_fixture, synthetic_bearer_token, environment_fixture):
            self.assertIn(fixture, source)
        self.assertIsNotNone(SANITIZER.KEY_VALUE_SECRET.search(source))
        self.assertIsNotNone(SANITIZER.BEARER_TOKEN.search(source))
        self.assertIsNotNone(SANITIZER.JWT.search(source))
        with patch.dict(
            os.environ,
            {"TEST_EVIDENCE_PASSWORD": environment_fixture},
            clear=False,
        ):
            result = SANITIZER.sanitize(source, ["TEST_EVIDENCE_PASSWORD"])

        self.assertNotIn(credential_fixture, result)
        self.assertNotIn(synthetic_bearer_token, result)
        self.assertNotIn(environment_fixture, result)
        self.assertGreaterEqual(result.count("[REDACTED]"), 3)

    def test_redacts_jwt_with_base64url_terminal_dash(self) -> None:
        synthetic_jwt = "eyJheaderpayload.fixturepayload.signaturepayload-"
        source = f"diagnostic token {synthetic_jwt}."

        self.assertIsNotNone(SANITIZER.JWT.fullmatch(synthetic_jwt))
        result = SANITIZER.sanitize(source, [])

        self.assertNotIn(synthetic_jwt, result)
        self.assertIn("[REDACTED JWT]", result)

    def test_redacts_long_escaped_quoted_values_without_backtracking(self) -> None:
        password = (r"\!" * 4096) + secrets.token_urlsafe(24)
        client_secret = (r"\&" * 4096) + secrets.token_urlsafe(24)
        source = f"password=\"{password}\nclient_secret='{client_secret}\n"
        self.assertIn(password, source)
        self.assertIn(client_secret, source)

        result = SANITIZER.sanitize(source, [])

        self.assertEqual(result, "password=[REDACTED]\nclient_secret=[REDACTED]\n")
        self.assertNotIn(password, result)
        self.assertNotIn(client_secret, result)


if __name__ == "__main__":
    unittest.main()
