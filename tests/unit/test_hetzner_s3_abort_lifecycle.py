"""Hetzner's Prefix normalization must not duplicate a lifecycle rule."""

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

MODULE_PATH = Path(__file__).resolve().parents[2] / "plugins/modules/hetzner_s3_abort_lifecycle.py"
SPEC = importlib.util.spec_from_file_location("hetzner_s3_abort_lifecycle", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Completed(Exception):
    def __init__(self, result):
        self.result = result


class Rejected(Exception):
    def __init__(self, result):
        self.result = result


class FakeModule:
    params = {
        "bucket": "dedicated-backup",
        "endpoint_url": "https://nbg1.your-objectstorage.com",
        "region": "nbg1",
        "access_key": "synthetic-access",
        "secret_key": "synthetic-secret",
        "abort_days": 7,
        "validate_certs": True,
    }
    check_mode = False

    def exit_json(self, **result):
        raise Completed(result)

    def fail_json(self, **result):
        raise Rejected(result)


def rule(identifier, *, extra=None):
    result = {
        "ID": identifier,
        "Status": "Enabled",
        "Prefix": "",
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7},
    }
    result.update(extra or {})
    return result


class FakeS3:
    def __init__(self, rules):
        self.rules = rules
        self.put_calls = 0

    def get_bucket_lifecycle_configuration(self, **kwargs):
        return {"Rules": self.rules}

    def put_bucket_lifecycle_configuration(self, **kwargs):
        self.put_calls += 1
        requested = kwargs["LifecycleConfiguration"]["Rules"][0]
        self.rules = [requested]


class HetznerAbortLifecycleTests(unittest.TestCase):
    def test_malformed_endpoints_are_refused_before_creating_a_client(self):
        for endpoint in [
            "https://",
            "https://user:secret@example.test",
            "https://example.test/path",
            "https://example.test?query=1",
            "https://example.test#fragment",
            "https://[invalid",
            "https://example.test:99999",
            "https://example.test:bad",
            "https://example.test\n",
            "http://example.test",
        ]:
            with self.subTest(endpoint=endpoint):
                module = FakeModule()
                module.params = {**module.params, "endpoint_url": endpoint}
                client = Mock()
                with (
                    patch.object(MODULE, "AnsibleModule", return_value=module),
                    patch.object(MODULE, "boto3", SimpleNamespace(client=client)),
                ):
                    with self.assertRaises(Rejected) as outcome:
                        MODULE.main()
                    client.assert_not_called()
                    self.assertNotIn("secret", str(outcome.exception.result))

    def test_insecure_tls_is_rejected_before_creating_a_client(self):
        module = FakeModule()
        module.params = {**module.params, "validate_certs": False}
        client = Mock()
        with (
            patch.object(MODULE, "AnsibleModule", return_value=module),
            patch.object(MODULE, "boto3", SimpleNamespace(client=client)),
        ):
            with self.assertRaises(Rejected):
                MODULE.main()
            client.assert_not_called()

    def run_module(self, rules, *, check_mode=False, abort_days=7):
        client = FakeS3(rules)
        module = FakeModule()
        module.check_mode = check_mode
        module.params = {**module.params, "abort_days": abort_days}
        with (
            patch.object(MODULE, "AnsibleModule", return_value=module),
            patch.object(MODULE, "boto3", SimpleNamespace(client=lambda *args, **kwargs: client)),
            patch.object(MODULE, "Config", lambda **kwargs: kwargs, create=True),
        ):
            try:
                MODULE.main()
            except (Completed, Rejected) as outcome:
                return outcome, client
        self.fail("Module did not complete")

    def test_provider_prefix_form_is_idempotent(self):
        outcome, client = self.run_module([rule("provider-normalized-id")])
        self.assertIsInstance(outcome, Completed)
        self.assertFalse(outcome.result["changed"])
        self.assertEqual(client.put_calls, 0)

    def test_duplicate_provider_rules_converge_to_one(self):
        outcome, client = self.run_module([rule(MODULE.RULE_ID), rule("provider-duplicate")])
        self.assertIsInstance(outcome, Completed)
        self.assertTrue(outcome.result["changed"])
        self.assertEqual(client.put_calls, 1)
        self.assertEqual(len(client.rules), 1)

    def test_changed_days_update_once_and_then_converge(self):
        outcome, client = self.run_module([rule(MODULE.RULE_ID)], abort_days=14)
        self.assertIsInstance(outcome, Completed)
        self.assertTrue(outcome.result["changed"])
        self.assertEqual(client.rules[0]["AbortIncompleteMultipartUpload"], {"DaysAfterInitiation": 14})
        repeated, client = self.run_module(client.rules, abort_days=14)
        self.assertFalse(repeated.result["changed"])
        self.assertEqual(client.put_calls, 0)

    def test_changed_days_preview_never_writes(self):
        outcome, client = self.run_module([rule(MODULE.RULE_ID)], abort_days=14, check_mode=True)
        self.assertTrue(outcome.result["changed"])
        self.assertEqual(client.put_calls, 0)

    def test_unrelated_rule_fails_closed(self):
        outcome, client = self.run_module([rule("other", extra={"Expiration": {"Days": 30}})])
        self.assertIsInstance(outcome, Rejected)
        self.assertEqual(client.put_calls, 0)

    def test_check_mode_does_not_write(self):
        outcome, client = self.run_module([rule(MODULE.RULE_ID), rule("duplicate")], check_mode=True)
        self.assertIsInstance(outcome, Completed)
        self.assertTrue(outcome.result["changed"])
        self.assertEqual(client.put_calls, 0)


if __name__ == "__main__":
    unittest.main()


class TransportFailureTests(unittest.TestCase):
    def test_transport_failures_are_sanitized_at_every_client_boundary(self):
        class TransportError(Exception):
            pass

        class ServiceError(Exception):
            pass

        for stage in ("create", "read", "write", "readback"):
            with self.subTest(stage=stage):
                client = Mock()
                error = TransportError("https://SENSITIVE-CANARY")
                client.get_bucket_lifecycle_configuration.side_effect = (
                    [{"Rules": []}, error] if stage == "readback" else error if stage == "read" else [{"Rules": []}]
                )
                if stage == "write":
                    client.put_bucket_lifecycle_configuration.side_effect = error
                creator = Mock(side_effect=error) if stage == "create" else Mock(return_value=client)
                with (
                    patch.object(MODULE, "AnsibleModule", return_value=FakeModule()),
                    patch.object(MODULE, "boto3", SimpleNamespace(client=creator)),
                    patch.object(MODULE, "Config", lambda **kwargs: kwargs, create=True),
                    patch.object(MODULE, "BotoCoreError", TransportError, create=True),
                    patch.object(MODULE, "ClientError", ServiceError, create=True),
                ):
                    with self.assertRaises(Rejected) as outcome:
                        MODULE.main()
                self.assertNotIn("SENSITIVE-CANARY", str(outcome.exception.result))
                self.assertIn("transport failure", outcome.exception.result["msg"])
