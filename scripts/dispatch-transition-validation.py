"""Dispatch the temporary central Collection validation without rebuilding."""

# Managed by lightning-it/shared-assets-lit. Change the canonical source there.

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import PurePath

REPOSITORY_RE = re.compile(r"lightning-it/ansible-collection-[a-z0-9-]+\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-.][0-9A-Za-z.-]+)?\Z")
REF_RE = re.compile(r"[0-9A-Za-z][0-9A-Za-z._/-]*\Z")
ARTIFACT_RE = re.compile(
    r"[a-z0-9_]+-[a-z0-9_]+-[0-9A-Za-z.-]+\.tar\.gz\Z"
)
WORKFLOW_ENDPOINT = (
    "repos/lightning-it/modulix-validation/actions/workflows/"
    "collection-release-transition.yml/dispatches"
)


def validated(value: str, pattern: re.Pattern[str], label: str) -> str:
    if not pattern.fullmatch(value):
        raise SystemExit(f"invalid {label}: {value!r}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--ref", default="main")
    args = parser.parse_args()

    repository = validated(args.source_repository, REPOSITORY_RE, "source repository")
    source_sha = validated(args.source_sha, SHA_RE, "source SHA")
    version = validated(args.version, VERSION_RE, "version")
    artifact_name = validated(args.artifact_name, ARTIFACT_RE, "artifact name")
    artifact_sha256 = validated(args.artifact_sha256, DIGEST_RE, "artifact SHA-256")
    controller_ref = validated(args.ref, REF_RE, "controller ref")
    if PurePath(artifact_name).name != artifact_name or not artifact_name.endswith(
        f"-{version}.tar.gz"
    ):
        raise SystemExit("artifact name must be a basename for the exact version")
    if not os.environ.get("GH_TOKEN"):
        raise SystemExit("a release automation App token is required as GH_TOKEN")

    command = [
        "gh",
        "api",
        "--method",
        "POST",
        WORKFLOW_ENDPOINT,
        "-f",
        f"ref={controller_ref}",
        "-f",
        f"inputs[source_repository]={repository}",
        "-f",
        f"inputs[source_sha]={source_sha}",
        "-f",
        f"inputs[version]={version}",
        "-f",
        f"inputs[artifact_sha256]={artifact_sha256}",
        "-f",
        f"inputs[artifact_name]={artifact_name}",
    ]
    subprocess.run(command, check=True)  # noqa: S603 -- fixed executable and validated arguments.
    print(f"Dispatched transition-mode validation for {repository}:{version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
