"""Dispatch the fixed MLX-90 consumer with an immutable evidence pointer."""

from __future__ import annotations

import argparse
import os
import re
import subprocess

EVIDENCE_URL = re.compile(
    r"^https://github\.com/lightning-it/ansible-collection-supplementary/"
    r"releases/download/v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)/security-release-evidence\.json$"
)
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
WORKFLOW_ENDPOINT = (
    "repos/lightning-it/container-ee-wunder-ansible-ubi9/actions/workflows/security-release-update.yml/dispatches"
)
CONTROLLER_REF = "main"
DISPATCH_TIMEOUT_SECONDS = 60


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-url", required=True)
    parser.add_argument("--evidence-sha256", required=True)
    args = parser.parse_args()

    if EVIDENCE_URL.fullmatch(args.evidence_url) is None:
        parser.error("evidence URL must be the fixed producer release asset URL")
    if DIGEST.fullmatch(args.evidence_sha256) is None:
        parser.error("evidence SHA-256 must include the canonical sha256: prefix")
    if not os.environ.get("GH_TOKEN"):
        parser.error("a release automation App token is required as GH_TOKEN")

    command = [
        "gh",
        "api",
        "--method",
        "POST",
        WORKFLOW_ENDPOINT,
        "-f",
        f"ref={CONTROLLER_REF}",
        "-f",
        f"inputs[evidence_url]={args.evidence_url}",
        "-f",
        f"inputs[evidence_sha256]={args.evidence_sha256}",
    ]
    subprocess.run(  # noqa: S603 -- fixed executable and validated arguments.
        command,
        check=True,
        timeout=DISPATCH_TIMEOUT_SECONDS,
    )
    print("Dispatched immutable MLX-90 producer evidence to the allowlisted consumer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
