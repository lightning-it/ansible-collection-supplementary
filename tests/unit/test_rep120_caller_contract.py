"""Offline description regressions; no token, network or broker execution."""

from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from scripts.rep120_caller_contract import (
    REF,
    REPOSITORY,
    WORKFLOW,
    HeldContext,
    describe,
    exact_type,
    inspect_context,
    main,
)

ROOT = Path(__file__).resolve().parents[2]


def context() -> dict[str, str]:
    return {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_ID": "1103407173",
        "GITHUB_REPOSITORY_OWNER_ID": "54334171",
        "GITHUB_REF": REF,
        "GITHUB_SHA": "a" * 40,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{WORKFLOW}@{REF}",
        "GITHUB_WORKFLOW_SHA": "a" * 40,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_ACTOR": "litroc",
        "GITHUB_ACTOR_ID": "76040632",
        "GITHUB_TRIGGERING_ACTOR": "litroc",
        "GITHUB_REF_PROTECTED": "true",
    }


class CallerContractTests(unittest.TestCase):
    def test_exact_builtin_types_reject_bool_and_subclasses(self):
        class IntegerSubclass(int):
            pass

        class StringSubclass(str):
            pass

        class DictSubclass(dict[str, object]):
            pass

        positive_cases: tuple[tuple[object, type[Any]], ...] = ((1, int), ("value", str), ({}, dict))
        for value, expected in positive_cases:
            self.assertTrue(exact_type(value, expected))
        negative_cases: tuple[tuple[object, type[Any]], ...] = (
            (True, int),
            (IntegerSubclass(1), int),
            (StringSubclass("value"), str),
            (DictSubclass(), dict),
        )
        for value, expected in negative_cases:
            self.assertFalse(exact_type(value, expected))

    def test_default_description_has_no_request_token_transport_or_acceptance(self):
        result = describe()
        self.assertFalse(result["enabled"])
        self.assertFalse(result["hosted_acceptance"])
        for key in ("request", "oidc", "native_delivery", "observed_context"):
            self.assertIsNone(result[key])
        candidate = result["candidate"]
        assert isinstance(candidate, dict)
        self.assertEqual(candidate["workflow"], WORKFLOW)
        self.assertEqual(
            result["root_binding_decisions"],
            {
                "audience": "lit-rep120-ledger:1413923700:operation-ledger-core",
                "approval_repository": "lightning-it/github-management-lit",
                "approval_issue": 721,
                "approval_actor_id": 76040632,
                "dispatch_actor": "litroc",
                "dispatch_actor_id": 76040632,
            },
        )

    def test_metadata_is_explicitly_not_admission(self):
        for event in ("push", "workflow_dispatch"):
            values = context() | {"GITHUB_EVENT_NAME": event}
            result = describe(values)
            self.assertEqual(result["observed_context"], values)
            self.assertFalse(result["enabled"])
            self.assertFalse(result["hosted_acceptance"])
            self.assertIsNone(result["request"])

    def test_drift_and_malformed_metadata_fail_closed(self):
        mutations: dict[str, list[Any]] = {
            "GITHUB_REPOSITORY": ["other/repository"],
            "GITHUB_REPOSITORY_ID": ["0", "1103407174", 1103407173],
            "GITHUB_REPOSITORY_OWNER_ID": ["54334172"],
            "GITHUB_REF": ["refs/heads/develop", "refs/tags/release"],
            "GITHUB_SHA": ["A" * 40, "a" * 39, "a" * 257],
            "GITHUB_WORKFLOW_REF": [f"{REPOSITORY}/{WORKFLOW}@refs/heads/develop"],
            "GITHUB_WORKFLOW_SHA": ["b" * 40],
            "GITHUB_RUN_ID": ["0", "01", "9007199254740992", "1; command"],
            "GITHUB_RUN_ATTEMPT": ["2", "01"],
            "GITHUB_EVENT_NAME": ["schedule", "pull_request", "workflow_call"],
            "GITHUB_ACTOR": ["other", "Litroc", "litroc ", "litroc[bot]"],
            "GITHUB_ACTOR_ID": ["76040633", "076040632", 76040632],
            "GITHUB_TRIGGERING_ACTOR": ["other", "Litroc", "litroc ", "litroc[bot]"],
            "GITHUB_REF_PROTECTED": ["false", "True", "1", True],
        }
        for key, values in mutations.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(HeldContext):
                    inspect_context(context() | {key: value})
        for key in context():
            missing = context()
            del missing[key]
            with self.subTest(missing=key), self.assertRaises(HeldContext):
                inspect_context(missing)

    def test_ambient_credentials_never_enter_description_or_errors(self):
        values = context() | {"GH_TOKEN": "secret-canary", "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "secret-canary"}
        self.assertNotIn("secret-canary", str(describe(values)))
        stdout, stderr = io.StringIO(), io.StringIO()
        values["GITHUB_SHA"] = "secret-canary"
        with patch.dict("os.environ", values, clear=True), contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                self.assertEqual(main(["--inspect-context"]), 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("secret-canary", stderr.getvalue())

    def test_workflow_manual_main_attempt_one_and_default_empty_inputs(self):
        workflow = yaml.safe_load((ROOT / WORKFLOW).read_text())
        events = workflow.get("on", workflow.get(True))
        self.assertEqual(set(events), {"workflow_dispatch"})
        inputs = events["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"delivery", "envelope"})
        for value in inputs.values():
            self.assertEqual(value["default"], "")
            self.assertEqual(value["type"], "string")
            self.assertIs(value["required"], False)
        self.assertEqual(workflow["permissions"], {})
        self.assertEqual(set(workflow["jobs"]), {"caller"})
        job = workflow["jobs"]["caller"]
        self.assertEqual(set(job), {"if", "runs-on", "timeout-minutes", "permissions", "steps"})
        self.assertEqual(job["permissions"], {"contents": "read", "id-token": "write"})
        self.assertEqual(
            job["if"],
            "github.repository == 'lightning-it/ansible-collection-supplementary' && "
            "github.event_name == 'workflow_dispatch' && "
            "github.ref == 'refs/heads/main' && github.ref_protected == true && "
            "github.actor_id == '76040632' && github.actor == 'litroc' && "
            "github.triggering_actor == 'litroc' && github.run_attempt == 1",
        )
        self.assertNotIn("environment", job)
        self.assertNotIn("uses", job)
        self.assertEqual(len(job["steps"]), 2)
        checkout, send = job["steps"]
        self.assertEqual(checkout["uses"], "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
        self.assertEqual(checkout["with"], {"ref": "${{ github.sha }}", "persist-credentials": False, "fetch-depth": 1})
        self.assertEqual(
            send["env"], {"REP120_DELIVERY": "${{ inputs.delivery }}", "REP120_ENVELOPE": "${{ inputs.envelope }}"}
        )
        self.assertEqual(send["run"], "python3 -m scripts.rep120_caller_sender")
        self.assertNotIn("continue-on-error", job)


if __name__ == "__main__":
    unittest.main()
