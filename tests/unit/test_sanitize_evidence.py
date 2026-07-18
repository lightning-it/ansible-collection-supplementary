"""Regression tests for controller-side Incus evidence redaction."""

from __future__ import annotations

import importlib.util
import json
import os
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
        source = {
            "records": [
                {"name": "password", "value": "structured-secret"},
                {"key": "client_token", "content": "token-secret"},
            ],
            "safe": "retained",
        }

        result = json.loads(SANITIZER.sanitize(json.dumps(source), []))

        self.assertEqual(result["records"][0]["value"], "[REDACTED]")
        self.assertEqual(result["records"][1]["content"], "[REDACTED]")
        self.assertEqual(result["safe"], "retained")
        self.assertNotIn("structured-secret", json.dumps(result))
        self.assertNotIn("token-secret", json.dumps(result))

    def test_redacts_sensitive_json_keys_recursively(self) -> None:
        source = {"nested": {"authorization": "Basic dXNlcjpwYXNz"}}

        result = json.loads(SANITIZER.sanitize(json.dumps(source), []))

        self.assertEqual(result["nested"]["authorization"], "[REDACTED]")

    def test_json_redaction_preserves_valid_escaped_content(self) -> None:
        source = {
            "images": [
                {
                    "name": "registry.example/keycloak:26",
                    "annotation": 'token="quoted\\value"',
                }
            ]
        }

        rendered = SANITIZER.sanitize(json.dumps(source), [])
        result = json.loads(rendered)

        self.assertEqual(result["images"][0]["name"], "registry.example/keycloak:26")
        self.assertEqual(result["images"][0]["annotation"], "token=[REDACTED]")

    def test_json_document_mode_extracts_payload_after_command_diagnostic(self) -> None:
        source = 'level=warning msg="runtime notice"\n[{"Id":"sha256:abc"}]\n'

        rendered = SANITIZER.sanitize(source, [], require_json=True)

        self.assertEqual(json.loads(rendered), [{"Id": "sha256:abc"}])

    def test_json_document_mode_rejects_non_json_input(self) -> None:
        with self.assertRaises(ValueError):
            SANITIZER.sanitize("runtime warning only", [], require_json=True)

    def test_redacts_exact_environment_value_and_credential_shapes(self) -> None:
        source = (
            "password=plain-secret\n"
            "Authorization: Bearer eyJabcdefghijk.abcdefghijk.abcdefghijk\n"
            "exact-environment-secret\n"
        )
        with patch.dict(
            os.environ,
            {"TEST_EVIDENCE_PASSWORD": "exact-environment-secret"},
            clear=False,
        ):
            result = SANITIZER.sanitize(source, ["TEST_EVIDENCE_PASSWORD"])

        self.assertNotIn("plain-secret", result)
        self.assertNotIn("eyJabcdefghijk", result)
        self.assertNotIn("exact-environment-secret", result)
        self.assertGreaterEqual(result.count("[REDACTED]"), 3)

    def test_redacts_long_escaped_quoted_values_without_backtracking(self) -> None:
        source = 'password="' + (r"\!" * 4096) + "\nclient_secret='" + (r"\&" * 4096) + "\n"

        result = SANITIZER.sanitize(source, [])

        self.assertEqual(result, "password=[REDACTED]\nclient_secret=[REDACTED]\n")


if __name__ == "__main__":
    unittest.main()
