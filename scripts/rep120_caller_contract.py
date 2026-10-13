"""Credential-free caller description; never a broker client or admission proof."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import TypeGuard, TypeVar

ExactValue = TypeVar("ExactValue")

REPOSITORY = "lightning-it/ansible-collection-supplementary"
REPOSITORY_ID = "1103407173"
OWNER_ID = "54334171"
WORKFLOW = ".github/workflows/rep120-ledger-caller.yml"
REF = "refs/heads/main"
BROKER_SOURCE = "c3ba9663b6467d8fb336cc11b954bf3716ded1b6"
BROKER_BLOB = "36824fc60fd1e8465eb895966938eb5e4d1c819c"
AUDIENCE = "lit-rep120-ledger:1413923700:operation-ledger-core"
APPROVAL_REPOSITORY = "lightning-it/github-management-lit"
APPROVAL_ISSUE = 721
APPROVAL_ACTOR_ID = 76040632
DISPATCH_ACTOR = "litroc"
DISPATCH_ACTOR_ID = "76040632"
REQUEST_FIELDS = ("expected_head", "operation_key", "path", "contents", "run_id", "approval_id", "expires_at")
ROOT_FIELDS = (
    "caller.source_sha",
    "caller.owner_sha256",
    "caller.policy_epoch",
    "binding.writer_user_id",
    "binding.signer_user_id",
    "binding.signer_key_fingerprint",
    "binding.effective_policy_sha256",
    "runtime",
    "native_delivery_contract",
    "approved_oidc_job_permission",
    "authenticated_operation_and_append_plan",
)
CONTEXT_FIELDS = (
    "GITHUB_REPOSITORY",
    "GITHUB_REPOSITORY_ID",
    "GITHUB_REPOSITORY_OWNER_ID",
    "GITHUB_REF",
    "GITHUB_SHA",
    "GITHUB_WORKFLOW_REF",
    "GITHUB_WORKFLOW_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_EVENT_NAME",
    "GITHUB_ACTOR",
    "GITHUB_ACTOR_ID",
    "GITHUB_TRIGGERING_ACTOR",
    "GITHUB_REF_PROTECTED",
)


class HeldContext(ValueError):
    """Reject context without including untrusted input or secret values."""


def exact_type(value: object, expected: type[ExactValue]) -> TypeGuard[ExactValue]:
    """Require the exact builtin type; bool/int and subclasses are distinct."""
    observed = type(value)
    return observed is expected


def inspect_context(environ: Mapping[str, str]) -> dict[str, str]:
    """Inspect only metadata. Environment strings are NOT authenticated OIDC."""
    context = {key: environ.get(key, "") for key in CONTEXT_FIELDS}
    if any(not exact_type(value, str) or len(value) > 256 for value in context.values()):
        raise HeldContext("missing or malformed caller metadata")
    expected = {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_ID": REPOSITORY_ID,
        "GITHUB_REPOSITORY_OWNER_ID": OWNER_ID,
        "GITHUB_REF": REF,
        "GITHUB_WORKFLOW_REF": f"{REPOSITORY}/{WORKFLOW}@{REF}",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_ACTOR": DISPATCH_ACTOR,
        "GITHUB_ACTOR_ID": DISPATCH_ACTOR_ID,
        "GITHUB_TRIGGERING_ACTOR": DISPATCH_ACTOR,
        "GITHUB_REF_PROTECTED": "true",
    }
    if any(context[key] != value for key, value in expected.items()):
        raise HeldContext("caller metadata identity mismatch")
    if (
        re.fullmatch(r"[0-9a-f]{40}", context["GITHUB_SHA"]) is None
        or context["GITHUB_WORKFLOW_SHA"] != context["GITHUB_SHA"]
        or re.fullmatch(r"[1-9][0-9]{0,15}", context["GITHUB_RUN_ID"]) is None
        or int(context["GITHUB_RUN_ID"]) > 2**53 - 1
        or context["GITHUB_EVENT_NAME"] not in ("push", "workflow_dispatch")
    ):
        raise HeldContext("caller metadata revision/run mismatch")
    return context


def describe(context: Mapping[str, str] | None = None) -> dict[str, object]:
    """Emit a held description, never an executable request/configuration."""
    return {
        "schema": "lit-rep120-caller-description/v1",
        "enabled": False,
        "state": "held",
        "hosted_acceptance": False,
        "evidence_class": "untrusted local description; not OIDC, approval, attestation or CAS",
        "candidate": {
            "repository": REPOSITORY,
            "repository_id": int(REPOSITORY_ID),
            "owner_id": int(OWNER_ID),
            "workflow": WORKFLOW,
            "ref": REF,
        },
        "broker_source": {"commit": BROKER_SOURCE, "blob": BROKER_BLOB},
        "root_binding_decisions": {
            "audience": AUDIENCE,
            "approval_repository": APPROVAL_REPOSITORY,
            "approval_issue": APPROVAL_ISSUE,
            "approval_actor_id": APPROVAL_ACTOR_ID,
            "dispatch_actor": DISPATCH_ACTOR,
            "dispatch_actor_id": int(DISPATCH_ACTOR_ID),
        },
        "observed_context": None if context is None else inspect_context(context),
        "request_fields": list(REQUEST_FIELDS),
        "required_root_fields": list(ROOT_FIELDS),
        "request": None,
        "oidc": None,
        "native_delivery": None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-context", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = describe(os.environ if args.inspect_context else None)
    except HeldContext as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
