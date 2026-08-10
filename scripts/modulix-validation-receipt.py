"""Dispatch and verify the signed ModuLix validation receipt for one candidate.

The request contains only immutable, non-secret publication bindings.  The
GitHub App installation, controller workflow, run actor/ref/SHA/attempt,
canonical receipt artifact, keyless signature, and release decision are all
checked before the command succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

SOURCE_REPOSITORY = "lightning-it/ansible-collection-supplementary"
SOURCE_WORKFLOW = ".github/workflows/collection-publish.yml"
CONTROLLER_REPOSITORY = "lightning-it/modulix-validation"
CONTROLLER_REF = "refs/heads/main"
CONTROLLER_BRANCH = "main"
CONTROLLER_WORKFLOW = ".github/workflows/mlx90-collection-candidate-validation.yml"
CONTROLLER_WORKFLOW_FILE = "mlx90-collection-candidate-validation.yml"
APP_SLUG = "lightning-it-release-automation"
APP_INSTALLATION_ID = 148019054
APP_ACTOR = f"{APP_SLUG}[bot]"
APP_ACTOR_ID = 307565056
APP_PERMISSIONS = {
    "actions": "write",
    "checks": "read",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "write",
}
REQUEST_API_VERSION = "lit.mlx90.collection-validation-request/v2"
REQUEST_KIND = "CollectionValidationRequest"
RECEIPT_API_VERSION = "lit.mlx90.collection-validation-receipt/v2"
RECEIPT_KIND = "CollectionValidationReceipt"
RECEIPT_NAME = "mlx90-collection-validation-receipt.json"
RECEIPT_BUNDLE_NAME = f"{RECEIPT_NAME}.sigstore.json"
RUN_TITLE_PREFIX = "MLX-90 collection candidate / "
ARTIFACT_PREFIX = "mlx90-collection-validation-"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
REQUEST_ID_RE = re.compile(r"[0-9a-f]{64}\Z")
VERSION_RE = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
ARTIFACT_RE = re.compile(
    r"lit-supplementary-(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\.tar\.gz\Z"
)
EVIDENCE_ID_RE = re.compile(r"MLX90-[A-Z0-9][A-Z0-9._-]{2,121}\Z")
NEXUS_REPOSITORY_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,126}\Z")
# The controller executes validation, Nexus readback, the Heavy and Application
# matrices in parallel, then signs its receipt.  Keep the bounded Producer wait
# below the 360-minute publish-job limit while covering the controller's full
# 255-minute execution budget plus queue/startup allowance.
DEFAULT_TIMEOUT_SECONDS = 16_200
DEFAULT_POLL_SECONDS = 10
COMMAND_TIMEOUT_SECONDS = 120


class ReceiptError(ValueError):
    """The dispatch or receipt contract was not satisfied."""


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ReceiptError(f"{label} must be a regular non-symlink file")
    try:
        source = path.read_text(encoding="utf-8")
        value = json.loads(source, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ReceiptError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ReceiptError(f"{label} must be a JSON object")
    if source != json.dumps(value, indent=2, sort_keys=True) + "\n":
        raise ReceiptError(f"{label} bytes are not canonical sorted UTF-8 JSON")
    return value


def exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ReceiptError(f"{label} fields differ: expected {sorted(expected)}, got {sorted(actual)}")


def string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ReceiptError(f"{label} must be a non-empty trimmed string")
    return value


def positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReceiptError(f"{label} must be a positive integer")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def validate_nexus_manifest(path: Path) -> dict[str, Any]:
    manifest = load_json(path, "Nexus staging manifest")
    exact_keys(manifest, {"apiVersion", "kind", "repository", "artifact", "readback", "uploaded"}, "manifest")
    if manifest["apiVersion"] != "lit.mlx90.nexus-stage/v1" or manifest["kind"] != "NexusGalaxyV3Stage":
        raise ReceiptError("Nexus staging manifest schema is unsupported")
    if not isinstance(manifest["uploaded"], bool):
        raise ReceiptError("Nexus staging uploaded flag must be boolean")

    repository = manifest["repository"]
    artifact = manifest["artifact"]
    readback = manifest["readback"]
    if not isinstance(repository, dict) or not isinstance(artifact, dict) or not isinstance(readback, dict):
        raise ReceiptError("Nexus staging manifest sections must be objects")
    exact_keys(repository, {"format", "name", "type", "url"}, "manifest.repository")
    exact_keys(artifact, {"name", "sha256", "size", "url"}, "manifest.artifact")
    exact_keys(readback, {"sha256", "size", "verified"}, "manifest.readback")

    repository_name = string(repository["name"], "manifest.repository.name")
    if (
        repository["format"] != "ansiblegalaxy"
        or repository["type"] != "hosted"
        or NEXUS_REPOSITORY_RE.fullmatch(repository_name) is None
    ):
        raise ReceiptError("Nexus repository is not a native hosted Ansible Galaxy repository")
    repository_url = string(repository["url"], "manifest.repository.url")
    parsed_repository_url = urllib.parse.urlsplit(repository_url)
    if (
        parsed_repository_url.scheme != "https"
        or not parsed_repository_url.hostname
        or parsed_repository_url.username is not None
        or parsed_repository_url.password is not None
        or parsed_repository_url.query
        or parsed_repository_url.fragment
        or not parsed_repository_url.path.endswith(f"/repository/{repository_name}")
        or "//" in parsed_repository_url.path
        or any(part in {".", ".."} for part in parsed_repository_url.path.split("/"))
    ):
        raise ReceiptError("Nexus repository URL is not bound to its repository name")

    artifact_name = string(artifact["name"], "manifest.artifact.name")
    artifact_digest = string(artifact["sha256"], "manifest.artifact.sha256")
    artifact_size = positive_integer(artifact["size"], "manifest.artifact.size")
    artifact_url = string(artifact["url"], "manifest.artifact.url")
    if ARTIFACT_RE.fullmatch(artifact_name) is None or DIGEST_RE.fullmatch(artifact_digest) is None:
        raise ReceiptError("Nexus artifact identity is invalid")
    expected_url = f"{repository_url}/api/v3/plugin/ansible/content/published/collections/artifacts/{artifact_name}"
    if artifact_url != expected_url:
        raise ReceiptError("Nexus artifact URL differs from the native Galaxy v3 endpoint")
    parsed_artifact_url = urllib.parse.urlsplit(artifact_url)
    if (
        parsed_artifact_url.scheme != parsed_repository_url.scheme
        or parsed_artifact_url.netloc != parsed_repository_url.netloc
        or parsed_artifact_url.query
        or parsed_artifact_url.fragment
    ):
        raise ReceiptError("Nexus artifact URL origin differs from the configured repository")
    if readback != {"sha256": artifact_digest, "size": artifact_size, "verified": True}:
        raise ReceiptError("Nexus readback does not exactly match the staged artifact")
    return manifest


def build_request(
    *,
    manifest: dict[str, Any],
    source_sha: str,
    source_run_id: int,
    source_run_attempt: int,
    evidence_id: str,
    version: str,
    controller_sha: str,
) -> tuple[dict[str, Any], str, str]:
    if SHA_RE.fullmatch(source_sha) is None or SHA_RE.fullmatch(controller_sha) is None:
        raise ReceiptError("source and controller SHAs must be full lowercase commit IDs")
    if EVIDENCE_ID_RE.fullmatch(evidence_id) is None:
        raise ReceiptError("Security evidence ID is invalid")
    if VERSION_RE.fullmatch(version) is None:
        raise ReceiptError("Security release version must be stable semantic versioning")
    positive_integer(source_run_id, "source run ID")
    positive_integer(source_run_attempt, "source run attempt")
    artifact = manifest["artifact"]
    if artifact["name"] != f"lit-supplementary-{version}.tar.gz":
        raise ReceiptError("Nexus artifact name differs from the Security release version")

    request: dict[str, Any] = {
        "apiVersion": REQUEST_API_VERSION,
        "kind": REQUEST_KIND,
        "source": {
            "actor": APP_ACTOR,
            "actorId": APP_ACTOR_ID,
            "actorType": "Bot",
            "event": "workflow_dispatch",
            "ref": "refs/heads/main",
            "repository": SOURCE_REPOSITORY,
            "runAttempt": source_run_attempt,
            "runId": source_run_id,
            "sha": source_sha,
            "workflow": SOURCE_WORKFLOW,
        },
        "security": {"evidenceId": evidence_id, "humanActions": 0},
        "candidate": {
            "name": artifact["name"],
            "sha256": artifact["sha256"],
            "size": artifact["size"],
            "version": version,
            "nexus": {
                "repository": manifest["repository"]["name"],
                "repositoryUrl": manifest["repository"]["url"],
                "url": artifact["url"],
            },
        },
        "controller": {
            "ref": CONTROLLER_REF,
            "repository": CONTROLLER_REPOSITORY,
            "sha": controller_sha,
            "workflow": CONTROLLER_WORKFLOW,
        },
    }
    request_json = canonical_json(request)
    request_id = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
    return request, request_json, request_id


class ControllerClient(Protocol):
    def installation(self) -> dict[str, Any]: ...

    def installation_repositories(self) -> list[str]: ...

    def controller_sha(self) -> str: ...

    def workflow(self) -> dict[str, Any]: ...

    def dispatch(self, request_json: str, request_id: str) -> None: ...

    def workflow_runs(self) -> list[dict[str, Any]]: ...

    def jobs(self, run_id: int) -> list[dict[str, Any]]: ...

    def artifacts(self, run_id: int) -> list[dict[str, Any]]: ...

    def download(self, run_id: int, artifact_name: str, destination: Path) -> None: ...

    def verify_signature(self, receipt: Path, bundle: Path, controller_sha: str) -> None: ...


class GhControllerClient:
    def __init__(self) -> None:
        if not os.environ.get("GH_TOKEN"):
            raise ReceiptError("a repository-scoped release automation App token is required")

    def _command(self, arguments: list[str], *, capture: bool = True) -> str:
        completed = subprocess.run(  # noqa: S603 -- fixed binaries and validated arguments.
            arguments,
            check=False,
            capture_output=capture,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise ReceiptError(f"command failed without satisfying the validation contract: {arguments[0]}")
        return completed.stdout

    def _json(self, endpoint: str) -> dict[str, Any]:
        try:
            value = json.loads(self._command(["gh", "api", endpoint]), object_pairs_hook=reject_duplicate_keys)
        except json.JSONDecodeError as exc:
            raise ReceiptError("GitHub API returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ReceiptError("GitHub API response must be an object")
        return value

    def installation(self) -> dict[str, Any]:
        return self._json("/installation")

    def installation_repositories(self) -> list[str]:
        payload = self._json("/installation/repositories?per_page=100")
        repositories = payload.get("repositories")
        if not isinstance(repositories, list) or payload.get("total_count") != len(repositories):
            raise ReceiptError("GitHub App repository response is incomplete")
        result = []
        for repository in repositories:
            if not isinstance(repository, dict):
                raise ReceiptError("GitHub App repository entry is invalid")
            result.append(string(repository.get("full_name"), "installation repository"))
        return result

    def controller_sha(self) -> str:
        payload = self._json(f"repos/{CONTROLLER_REPOSITORY}/git/ref/heads/{CONTROLLER_BRANCH}")
        target = payload.get("object")
        if not isinstance(target, dict):
            raise ReceiptError("controller main ref response is invalid")
        return string(target.get("sha"), "controller main SHA")

    def workflow(self) -> dict[str, Any]:
        return self._json(f"repos/{CONTROLLER_REPOSITORY}/actions/workflows/{CONTROLLER_WORKFLOW_FILE}")

    def dispatch(self, request_json: str, request_id: str) -> None:
        self._command(
            [
                "gh",
                "api",
                "--method",
                "POST",
                f"repos/{CONTROLLER_REPOSITORY}/actions/workflows/{CONTROLLER_WORKFLOW_FILE}/dispatches",
                "-f",
                f"ref={CONTROLLER_BRANCH}",
                "-f",
                f"inputs[request_id]={request_id}",
                "-f",
                f"inputs[request_json]={request_json}",
            ]
        )

    def workflow_runs(self) -> list[dict[str, Any]]:
        payload = self._json(
            f"repos/{CONTROLLER_REPOSITORY}/actions/workflows/{CONTROLLER_WORKFLOW_FILE}/runs"
            f"?branch={CONTROLLER_BRANCH}&event=workflow_dispatch&per_page=100"
        )
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise ReceiptError("controller workflow runs response is invalid")
        if any(not isinstance(run, dict) for run in runs):
            raise ReceiptError("controller workflow run entry is invalid")
        return runs

    def artifacts(self, run_id: int) -> list[dict[str, Any]]:
        payload = self._json(f"repos/{CONTROLLER_REPOSITORY}/actions/runs/{run_id}/artifacts?per_page=100")
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise ReceiptError("controller artifacts response is invalid")
        if payload.get("total_count") != len(artifacts) or any(not isinstance(item, dict) for item in artifacts):
            raise ReceiptError("controller artifacts response is incomplete")
        return artifacts

    def jobs(self, run_id: int) -> list[dict[str, Any]]:
        payload = self._json(f"repos/{CONTROLLER_REPOSITORY}/actions/runs/{run_id}/jobs?filter=all&per_page=100")
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise ReceiptError("controller jobs response is invalid")
        if payload.get("total_count") != len(jobs) or any(not isinstance(item, dict) for item in jobs):
            raise ReceiptError("controller jobs response is incomplete")
        return jobs

    def download(self, run_id: int, artifact_name: str, destination: Path) -> None:
        self._command(
            [
                "gh",
                "run",
                "download",
                str(run_id),
                "--repo",
                CONTROLLER_REPOSITORY,
                "--name",
                artifact_name,
                "--dir",
                str(destination),
            ]
        )

    def verify_signature(self, receipt: Path, bundle: Path, controller_sha: str) -> None:
        identity = f"https://github.com/{CONTROLLER_REPOSITORY}/{CONTROLLER_WORKFLOW}@refs/heads/main"
        self._command(
            [
                "cosign",
                "verify-blob",
                "--bundle",
                str(bundle),
                "--certificate-oidc-issuer",
                "https://token.actions.githubusercontent.com",
                "--certificate-identity",
                identity,
                "--certificate-github-workflow-sha",
                controller_sha,
                str(receipt),
            ]
        )


def validate_installation(client: ControllerClient, app_slug: str, installation_id: int) -> None:
    if app_slug != APP_SLUG or installation_id != APP_INSTALLATION_ID:
        raise ReceiptError("GitHub App action outputs do not identify the approved installation")
    installation = client.installation()
    account = installation.get("account")
    permissions = installation.get("permissions")
    if not isinstance(account, dict) or not isinstance(permissions, dict):
        raise ReceiptError("GitHub App installation response is incomplete")
    if (
        installation.get("id") != APP_INSTALLATION_ID
        or installation.get("app_slug") != APP_SLUG
        or installation.get("repository_selection") != "selected"
        or installation.get("target_type") != "Organization"
        or account.get("login") != "lightning-it"
        or permissions != APP_PERMISSIONS
    ):
        raise ReceiptError("GitHub App installation identity or permissions differ")
    if client.installation_repositories() != [CONTROLLER_REPOSITORY]:
        raise ReceiptError("GitHub App token is not scoped exclusively to ModuLix")


def validate_workflow(payload: Mapping[str, Any], controller_sha: str) -> None:
    if SHA_RE.fullmatch(controller_sha) is None:
        raise ReceiptError("controller main SHA is invalid")
    if (
        payload.get("path") != CONTROLLER_WORKFLOW
        or payload.get("state") != "active"
        or payload.get("name") != "MLX-90 collection candidate validation"
    ):
        raise ReceiptError("ModuLix controller workflow identity differs")


def matching_run(run: Mapping[str, Any], request_id: str, controller_sha: str) -> bool:
    repository = run.get("repository")
    head_repository = run.get("head_repository")
    actor = run.get("actor")
    triggering_actor = run.get("triggering_actor")
    return bool(
        isinstance(repository, dict)
        and isinstance(head_repository, dict)
        and isinstance(actor, dict)
        and isinstance(triggering_actor, dict)
        and run.get("display_title") == f"{RUN_TITLE_PREFIX}{request_id}"
        and run.get("event") == "workflow_dispatch"
        and run.get("path") == CONTROLLER_WORKFLOW
        and run.get("head_branch") == CONTROLLER_BRANCH
        and run.get("head_sha") == controller_sha
        and repository.get("full_name") == CONTROLLER_REPOSITORY
        and head_repository.get("full_name") == CONTROLLER_REPOSITORY
        and actor.get("login") == APP_ACTOR
        and actor.get("id") == APP_ACTOR_ID
        and actor.get("type") == "Bot"
        and triggering_actor.get("login") == APP_ACTOR
        and triggering_actor.get("id") == APP_ACTOR_ID
        and triggering_actor.get("type") == "Bot"
    )


def dispatch_if_absent(
    client: ControllerClient,
    request_json: str,
    request_id: str,
    controller_sha: str,
) -> bool:
    if (
        REQUEST_ID_RE.fullmatch(request_id) is None
        or hashlib.sha256(request_json.encode("utf-8")).hexdigest() != request_id
    ):
        raise ReceiptError("ModuLix request ID is not the SHA-256 of the canonical request")
    matches = [run for run in client.workflow_runs() if matching_run(run, request_id, controller_sha)]
    if len(matches) > 1:
        raise ReceiptError("multiple ModuLix runs already match the exact validation request")
    if matches:
        return False
    client.dispatch(request_json, request_id)
    return True


def wait_for_run(
    client: ControllerClient,
    request_id: str,
    controller_sha: str,
    timeout_seconds: int,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        matches = [run for run in client.workflow_runs() if matching_run(run, request_id, controller_sha)]
        if len(matches) > 1:
            raise ReceiptError("multiple ModuLix runs match the exact validation request")
        if matches:
            run = matches[0]
            positive_integer(run.get("id"), "controller run ID")
            positive_integer(run.get("run_attempt"), "controller run attempt")
            status = run.get("status")
            if status == "completed":
                if run.get("conclusion") != "success":
                    raise ReceiptError("exact ModuLix validation run did not succeed")
                return run
            if status not in {"queued", "in_progress", "pending", "requested", "waiting"}:
                raise ReceiptError("exact ModuLix validation run has an unknown status")
        sleep(DEFAULT_POLL_SECONDS)
    raise ReceiptError("timed out waiting for the exact ModuLix validation run")


def validate_run_jobs(jobs: list[dict[str, Any]]) -> None:
    if not jobs:
        raise ReceiptError("ModuLix validation run has no jobs")
    names: list[str] = []
    for job in jobs:
        name = string(job.get("name"), "controller job name")
        positive_integer(job.get("id"), f"controller job {name} ID")
        if job.get("status") != "completed" or job.get("conclusion") != "success":
            raise ReceiptError(f"ModuLix validation job did not succeed: {name}")
        names.append(name)
    for exact in ("Validate immutable request", "Nexus exact-byte readback", "Sign validation receipt"):
        if names.count(exact) != 1:
            raise ReceiptError(f"ModuLix validation run lacks the exact required job: {exact}")
    for prefix in ("Heavy / ", "Application Acceptance / "):
        if not any(name.startswith(prefix) for name in names):
            raise ReceiptError(f"ModuLix validation run lacks a successful {prefix.strip()} job")


def validate_receipt(
    receipt: Mapping[str, Any],
    request: Mapping[str, Any],
    request_id: str,
    run: Mapping[str, Any],
) -> None:
    exact_keys(receipt, {"apiVersion", "kind", "request", "requestId", "validation", "decision"}, "receipt")
    if receipt["apiVersion"] != RECEIPT_API_VERSION or receipt["kind"] != RECEIPT_KIND:
        raise ReceiptError("ModuLix validation receipt schema is unsupported")
    if receipt["request"] != request:
        raise ReceiptError("ModuLix validation receipt is not bound to the exact request")
    if receipt["requestId"] != f"sha256:{request_id}":
        raise ReceiptError("ModuLix validation receipt request ID differs")
    validation = receipt["validation"]
    decision = receipt["decision"]
    if not isinstance(validation, dict) or not isinstance(decision, dict):
        raise ReceiptError("ModuLix validation receipt sections must be objects")
    exact_keys(
        validation,
        {
            "actor",
            "actorId",
            "actorType",
            "conclusion",
            "event",
            "humanActions",
            "observations",
            "receiptArtifact",
            "ref",
            "repository",
            "runAttempt",
            "runId",
            "sha",
            "workflow",
        },
        "receipt.validation",
    )
    expected_artifact = f"{ARTIFACT_PREFIX}{request_id}"
    expected_validation = {
        "actor": APP_ACTOR,
        "actorId": APP_ACTOR_ID,
        "actorType": "Bot",
        "conclusion": "success",
        "event": "workflow_dispatch",
        "humanActions": 0,
        "receiptArtifact": expected_artifact,
        "ref": CONTROLLER_REF,
        "repository": CONTROLLER_REPOSITORY,
        "runAttempt": run["run_attempt"],
        "runId": run["id"],
        "sha": run["head_sha"],
        "workflow": CONTROLLER_WORKFLOW,
    }
    for key, expected in expected_validation.items():
        if validation.get(key) != expected:
            raise ReceiptError(f"ModuLix receipt validation.{key} differs")
    expected_observations = {
        "applicationAcceptance": "passed",
        "candidateDigest": request["candidate"]["sha256"],
        "heavy": "passed",
        "nexusReadback": request["candidate"]["sha256"],
        "sourceRun": {
            **request["source"],
        },
    }
    if validation["observations"] != expected_observations:
        raise ReceiptError("ModuLix receipt observations are incomplete or substituted")
    exact_keys(
        decision,
        {"candidateUnchanged", "galaxyPublicationAuthorized", "releaseEligible"},
        "receipt.decision",
    )
    if decision != {
        "candidateUnchanged": True,
        "galaxyPublicationAuthorized": True,
        "releaseEligible": True,
    }:
        raise ReceiptError("ModuLix validation receipt does not authorize exact-byte publication")


def download_and_verify_receipt(
    client: ControllerClient,
    request: dict[str, Any],
    request_id: str,
    run: dict[str, Any],
    output_directory: Path,
) -> tuple[Path, Path]:
    run_id = positive_integer(run.get("id"), "controller run ID")
    expected_artifact = f"{ARTIFACT_PREFIX}{request_id}"
    matches = [
        artifact
        for artifact in client.artifacts(run_id)
        if artifact.get("name") == expected_artifact and artifact.get("expired") is False
    ]
    if len(matches) != 1:
        raise ReceiptError("exact ModuLix validation receipt artifact is missing or ambiguous")

    temporary = output_directory.parent / f".{output_directory.name}-{request_id}"
    if temporary.exists() or temporary.is_symlink() or output_directory.exists() or output_directory.is_symlink():
        raise ReceiptError("validation receipt output must start absent")
    temporary.mkdir(parents=True)
    try:
        client.download(run_id, expected_artifact, temporary)
        entries = sorted(path.name for path in temporary.iterdir())
        if entries != [RECEIPT_NAME, RECEIPT_BUNDLE_NAME]:
            raise ReceiptError("ModuLix receipt artifact contains an unexpected file set")
        receipt_path = temporary / RECEIPT_NAME
        bundle_path = temporary / RECEIPT_BUNDLE_NAME
        if receipt_path.is_symlink() or bundle_path.is_symlink() or not bundle_path.is_file():
            raise ReceiptError("ModuLix receipt artifact contains an unsafe file")
        receipt = load_json(receipt_path, "ModuLix validation receipt")
        validate_receipt(receipt, request, request_id, run)
        client.verify_signature(receipt_path, bundle_path, string(run.get("head_sha"), "controller run SHA"))
        temporary.rename(output_directory)
    except Exception:
        if temporary.exists() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        raise
    return output_directory / RECEIPT_NAME, output_directory / RECEIPT_BUNDLE_NAME


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nexus-manifest", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-run-attempt", type=int, required=True)
    parser.add_argument("--security-evidence-id", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--app-slug", required=True)
    parser.add_argument("--installation-id", type=int, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()

    try:
        if args.timeout_seconds <= 0 or args.timeout_seconds > DEFAULT_TIMEOUT_SECONDS:
            raise ReceiptError("validation timeout is outside the bounded contract")
        manifest = validate_nexus_manifest(args.nexus_manifest)
        client = GhControllerClient()
        validate_installation(client, args.app_slug, args.installation_id)
        controller_sha = client.controller_sha()
        validate_workflow(client.workflow(), controller_sha)
        request, request_json, request_id = build_request(
            manifest=manifest,
            source_sha=args.source_sha,
            source_run_id=args.source_run_id,
            source_run_attempt=args.source_run_attempt,
            evidence_id=args.security_evidence_id,
            version=args.version,
            controller_sha=controller_sha,
        )
        dispatch_if_absent(client, request_json, request_id, controller_sha)
        run = wait_for_run(client, request_id, controller_sha, args.timeout_seconds)
        validate_run_jobs(client.jobs(positive_integer(run.get("id"), "controller run ID")))
        receipt_path = download_and_verify_receipt(client, request, request_id, run, args.output_directory)[0]
    except ReceiptError as exc:
        parser.error(str(exc))

    result = {
        "controllerRunAttempt": run["run_attempt"],
        "controllerRunId": run["id"],
        "receipt": str(receipt_path),
        "receiptSha256": file_sha256(receipt_path),
        "requestId": f"sha256:{request_id}",
        "verifiedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
