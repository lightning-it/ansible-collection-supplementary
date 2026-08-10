from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "modulix-validation-receipt.py"
SOURCE_SHA = "a" * 40
CONTROLLER_SHA = "b" * 40
ARTIFACT_DIGEST = f"sha256:{'c' * 64}"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("modulix_validation_receipt", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load ModuLix receipt script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = load_script()


def manifest_payload() -> dict[str, object]:
    repository_url = "https://nexus.example.test/repository/ansible-security-candidates"
    artifact_name = "lit-supplementary-3.2.4.tar.gz"
    artifact_url = f"{repository_url}/api/v3/plugin/ansible/content/published/collections/artifacts/{artifact_name}"
    return {
        "apiVersion": "lit.mlx90.nexus-stage/v1",
        "kind": "NexusGalaxyV3Stage",
        "repository": {
            "format": "ansiblegalaxy",
            "name": "ansible-security-candidates",
            "type": "hosted",
            "url": repository_url,
        },
        "artifact": {
            "name": artifact_name,
            "sha256": ARTIFACT_DIGEST,
            "size": 1234,
            "url": artifact_url,
        },
        "readback": {"sha256": ARTIFACT_DIGEST, "size": 1234, "verified": True},
        "uploaded": True,
    }


def request_payload() -> tuple[dict[str, object], str]:
    request, _, request_id = MODULE.build_request(
        manifest=manifest_payload(),
        source_sha=SOURCE_SHA,
        source_run_id=12345,
        source_run_attempt=2,
        evidence_id="MLX90-GHSA-VJJF-WC74-GP86-3.2.4",
        version="3.2.4",
        controller_sha=CONTROLLER_SHA,
    )
    return request, request_id


def run_payload(request_id: str, *, status: str = "completed", conclusion: str | None = "success") -> dict[str, object]:
    return {
        "actor": {"id": MODULE.APP_ACTOR_ID, "login": MODULE.APP_ACTOR, "type": "Bot"},
        "conclusion": conclusion,
        "display_title": f"{MODULE.RUN_TITLE_PREFIX}{request_id}",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_repository": {"full_name": MODULE.CONTROLLER_REPOSITORY},
        "head_sha": CONTROLLER_SHA,
        "id": 998877,
        "path": MODULE.CONTROLLER_WORKFLOW,
        "repository": {"full_name": MODULE.CONTROLLER_REPOSITORY},
        "run_attempt": 1,
        "status": status,
        "triggering_actor": {"id": MODULE.APP_ACTOR_ID, "login": MODULE.APP_ACTOR, "type": "Bot"},
    }


def receipt_payload(request: dict[str, object], request_id: str, run: dict[str, object]) -> dict[str, object]:
    return {
        "apiVersion": MODULE.RECEIPT_API_VERSION,
        "kind": MODULE.RECEIPT_KIND,
        "request": request,
        "requestId": f"sha256:{request_id}",
        "validation": {
            "actor": MODULE.APP_ACTOR,
            "actorId": MODULE.APP_ACTOR_ID,
            "actorType": "Bot",
            "conclusion": "success",
            "event": "workflow_dispatch",
            "humanActions": 0,
            "observations": {
                "applicationAcceptance": "passed",
                "candidateDigest": ARTIFACT_DIGEST,
                "heavy": "passed",
                "nexusReadback": ARTIFACT_DIGEST,
                "sourceRun": {
                    "actor": MODULE.APP_ACTOR,
                    "actorId": MODULE.APP_ACTOR_ID,
                    "actorType": "Bot",
                    "event": "workflow_dispatch",
                    "ref": "refs/heads/main",
                    "repository": MODULE.SOURCE_REPOSITORY,
                    "runAttempt": request["source"]["runAttempt"],
                    "runId": request["source"]["runId"],
                    "sha": request["source"]["sha"],
                    "workflow": MODULE.SOURCE_WORKFLOW,
                },
            },
            "receiptArtifact": f"{MODULE.ARTIFACT_PREFIX}{request_id}",
            "ref": MODULE.CONTROLLER_REF,
            "repository": MODULE.CONTROLLER_REPOSITORY,
            "runAttempt": run["run_attempt"],
            "runId": run["id"],
            "sha": CONTROLLER_SHA,
            "workflow": MODULE.CONTROLLER_WORKFLOW,
        },
        "decision": {
            "candidateUnchanged": True,
            "galaxyPublicationAuthorized": True,
            "releaseEligible": True,
        },
    }


class FakeController:
    def __init__(self, request: dict[str, object], request_id: str, run: dict[str, object]) -> None:
        self.request = request
        self.request_id = request_id
        self.run = run
        self.runs = [run]
        self.dispatches = 0
        self.signature_verified = False

    def installation(self) -> dict[str, object]:
        return {
            "account": {"login": "lightning-it"},
            "app_slug": MODULE.APP_SLUG,
            "id": MODULE.APP_INSTALLATION_ID,
            "permissions": MODULE.APP_PERMISSIONS,
            "repository_selection": "selected",
            "target_type": "Organization",
        }

    def installation_repositories(self) -> list[str]:
        return [MODULE.CONTROLLER_REPOSITORY]

    def controller_sha(self) -> str:
        return CONTROLLER_SHA

    def workflow(self) -> dict[str, str]:
        return {
            "name": "MLX-90 collection candidate validation",
            "path": MODULE.CONTROLLER_WORKFLOW,
            "state": "active",
        }

    def dispatch(self, request_json: str, request_id: str) -> None:
        if json.loads(request_json) != self.request or request_id != self.request_id:
            raise AssertionError("dispatch did not contain the exact request")
        self.dispatches += 1

    def workflow_runs(self) -> list[dict[str, object]]:
        return self.runs

    def jobs(self, run_id: int) -> list[dict[str, object]]:
        if run_id != self.run["id"]:
            raise AssertionError("wrong run ID")
        return [
            {"conclusion": "success", "id": 1, "name": "Validate immutable request", "status": "completed"},
            {"conclusion": "success", "id": 2, "name": "Nexus exact-byte readback", "status": "completed"},
            {"conclusion": "success", "id": 3, "name": "Heavy / supplementary", "status": "completed"},
            {
                "conclusion": "success",
                "id": 4,
                "name": "Application Acceptance / supplementary",
                "status": "completed",
            },
            {"conclusion": "success", "id": 5, "name": "Sign validation receipt", "status": "completed"},
        ]

    def artifacts(self, run_id: int) -> list[dict[str, object]]:
        if run_id != self.run["id"]:
            raise AssertionError("wrong run ID")
        return [{"expired": False, "name": f"{MODULE.ARTIFACT_PREFIX}{self.request_id}"}]

    def download(self, run_id: int, artifact_name: str, destination: Path) -> None:
        if run_id != self.run["id"] or artifact_name != f"{MODULE.ARTIFACT_PREFIX}{self.request_id}":
            raise AssertionError("wrong artifact")
        receipt = receipt_payload(self.request, self.request_id, self.run)
        (destination / MODULE.RECEIPT_NAME).write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (destination / MODULE.RECEIPT_BUNDLE_NAME).write_text("signed-bundle\n", encoding="utf-8")

    def verify_signature(self, receipt: Path, bundle: Path, controller_sha: str) -> None:
        if not receipt.is_file() or not bundle.is_file() or controller_sha != CONTROLLER_SHA:
            raise AssertionError("wrong signature inputs")
        self.signature_verified = True


class ModuLixValidationReceiptTests(unittest.TestCase):
    def test_manifest_and_request_are_exact_digest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nexus.json"
            path.write_text(json.dumps(manifest_payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            manifest = MODULE.validate_nexus_manifest(path)
            request, request_json, request_id = MODULE.build_request(
                manifest=manifest,
                source_sha=SOURCE_SHA,
                source_run_id=12345,
                source_run_attempt=2,
                evidence_id="MLX90-GHSA-VJJF-WC74-GP86-3.2.4",
                version="3.2.4",
                controller_sha=CONTROLLER_SHA,
            )

        self.assertEqual(64, len(request_id))
        self.assertEqual(request, json.loads(request_json))
        self.assertEqual(0, request["security"]["humanActions"])
        self.assertEqual(ARTIFACT_DIGEST, request["candidate"]["sha256"])
        self.assertEqual(MODULE.CONTROLLER_WORKFLOW, request["controller"]["workflow"])

        with self.assertRaisesRegex(MODULE.ReceiptError, "evidence ID"):
            MODULE.build_request(
                manifest=manifest_payload(),
                source_sha=SOURCE_SHA,
                source_run_id=12345,
                source_run_attempt=2,
                evidence_id="LIT-SEC-UNBOUND",
                version="3.2.4",
                controller_sha=CONTROLLER_SHA,
            )

    def test_manifest_rejects_substituted_readback_or_native_endpoint(self) -> None:
        cases = []
        mismatched_digest = manifest_payload()
        mismatched_digest["readback"]["sha256"] = f"sha256:{'d' * 64}"
        cases.append(mismatched_digest)
        wrong_url = manifest_payload()
        wrong_url["artifact"]["url"] = "https://nexus.example.test/repository/raw/candidate.tar.gz"
        cases.append(wrong_url)
        for index, payload in enumerate(cases):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary_directory:
                path = Path(temporary_directory) / "nexus.json"
                path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                with self.assertRaises(MODULE.ReceiptError):
                    MODULE.validate_nexus_manifest(path)

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "nexus.json"
            path.write_text(json.dumps(manifest_payload()), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ReceiptError, "canonical"):
                MODULE.validate_nexus_manifest(path)

    def test_installation_must_be_exact_and_non_administrative(self) -> None:
        request, request_id = request_payload()
        run = run_payload(request_id)
        client = FakeController(request, request_id, run)
        MODULE.validate_installation(client, MODULE.APP_SLUG, MODULE.APP_INSTALLATION_ID)

        original = client.installation
        client.installation = lambda: {
            **original(),
            "permissions": {**MODULE.APP_PERMISSIONS, "administration": "write"},
        }
        with self.assertRaisesRegex(MODULE.ReceiptError, "differ"):
            MODULE.validate_installation(client, MODULE.APP_SLUG, MODULE.APP_INSTALLATION_ID)

    def test_run_requires_exact_app_actor_ref_sha_and_unique_match(self) -> None:
        _, request_id = request_payload()
        run = run_payload(request_id)
        self.assertTrue(MODULE.matching_run(run, request_id, CONTROLLER_SHA))
        for field, value in (
            ("head_sha", "d" * 40),
            ("head_branch", "develop"),
            ("path", ".github/workflows/other.yml"),
            ("actor", {"login": "octocat"}),
        ):
            changed = {**run, field: value}
            with self.subTest(field=field):
                self.assertFalse(MODULE.matching_run(changed, request_id, CONTROLLER_SHA))

    def test_dispatch_reuses_one_exact_run_and_fails_on_ambiguity(self) -> None:
        request, request_id = request_payload()
        request_json = MODULE.canonical_json(request)
        run = run_payload(request_id)
        client = FakeController(request, request_id, run)
        self.assertFalse(MODULE.dispatch_if_absent(client, request_json, request_id, CONTROLLER_SHA))
        self.assertEqual(0, client.dispatches)

        client.runs = []
        self.assertTrue(MODULE.dispatch_if_absent(client, request_json, request_id, CONTROLLER_SHA))
        self.assertEqual(1, client.dispatches)

        client.runs = [run, deepcopy(run)]
        with self.assertRaisesRegex(MODULE.ReceiptError, "multiple"):
            MODULE.dispatch_if_absent(client, request_json, request_id, CONTROLLER_SHA)

    def test_run_jobs_prove_real_nexus_heavy_application_and_signing(self) -> None:
        request, request_id = request_payload()
        client = FakeController(request, request_id, run_payload(request_id))
        jobs = client.jobs(998877)
        MODULE.validate_run_jobs(jobs)

        missing = [job for job in jobs if not str(job["name"]).startswith("Heavy / ")]
        with self.assertRaisesRegex(MODULE.ReceiptError, "Heavy"):
            MODULE.validate_run_jobs(missing)
        failed = deepcopy(jobs)
        failed[2]["conclusion"] = "failure"
        with self.assertRaisesRegex(MODULE.ReceiptError, "did not succeed"):
            MODULE.validate_run_jobs(failed)

    def test_signed_receipt_is_persisted_only_after_exact_validation(self) -> None:
        request, request_id = request_payload()
        run = run_payload(request_id)
        client = FakeController(request, request_id, run)
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "modulix"
            receipt, bundle = MODULE.download_and_verify_receipt(client, request, request_id, run, output)
            self.assertTrue(receipt.is_file())
            self.assertTrue(bundle.is_file())
        self.assertTrue(client.signature_verified)

    def test_receipt_fails_closed_for_decision_observation_or_run_substitution(self) -> None:
        request, request_id = request_payload()
        run = run_payload(request_id)
        base = receipt_payload(request, request_id, run)
        cases: list[dict[str, object]] = []
        denied = deepcopy(base)
        denied["decision"]["galaxyPublicationAuthorized"] = False
        cases.append(denied)
        skipped = deepcopy(base)
        skipped["validation"]["observations"]["heavy"] = "skipped"
        cases.append(skipped)
        foreign = deepcopy(base)
        foreign["validation"]["runId"] = 1
        cases.append(foreign)
        for index, receipt in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(MODULE.ReceiptError):
                    MODULE.validate_receipt(receipt, request, request_id, run)


if __name__ == "__main__":
    unittest.main()
