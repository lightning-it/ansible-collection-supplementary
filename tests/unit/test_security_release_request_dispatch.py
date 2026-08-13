"""Tests for the protected-head MLX-90 Security request dispatcher."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/security-release-dispatch.py"
WORKFLOW = ROOT / ".github/workflows/security-release-dispatch.yml"
INTAKE_WORKFLOW = ROOT / ".github/workflows/security-release-intake.yml"
SPEC = importlib.util.spec_from_file_location("security_request_dispatch", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
REPOSITORY = "lightning-it/ansible-collection-supplementary"
VERSION = "3.2.4"
EVIDENCE_ID = "MLX90-KEYCLOAK-26.7.1-3.2.4"
PROFILE = "lit.supplementary/keycloak-26.7.1-security-v1"
NOW = datetime(2026, 8, 8, 23, 0, tzinfo=UTC)
HISTORICAL_FRAGMENT = b"""---
security_fixes:
  - >-
    Update the immutable Keycloak runtime to 26.7.1 to remediate
    CVE-2026-4629, CVE-2026-9793, CVE-2026-14209, CVE-2026-14614, and
    CVE-2026-14615.
"""
GIT = shutil.which("git")
assert GIT is not None


def git(root: Path, *args: str) -> str:
    environment = os.environ.copy()
    for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(variable, None)
    return subprocess.run(  # noqa: S603 -- fixed git binary and test-owned arguments.
        [GIT, *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
    ).stdout.strip()


class SecurityReleaseRequestDispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.name", "Test")
        git(self.root, "config", "user.email", "test@example.invalid")
        (self.root / ".lit").mkdir()
        (self.root / ".lit/security-release-profiles.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "profiles": {
                        PROFILE: {
                            "description": "Exact Keycloak acceptance",
                            "releaseEligible": True,
                        }
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        product = self.root / "roles/keycloak_deploy/defaults/main.yml"
        product.parent.mkdir(parents=True)
        product.write_text("---\nkeycloak_deploy_image: affected\n", encoding="utf-8")
        inventory = self.root / "meta/source-dependencies.yml"
        inventory.parent.mkdir(parents=True)
        inventory.write_text("---\ncontainer_images: []\n", encoding="utf-8")
        (self.root / "galaxy.yml").write_text(
            "---\nversion: 3.2.3\n",
            encoding="utf-8",
        )
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "base")
        self.base = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/main", self.base)

        product.write_text("---\nkeycloak_deploy_image: fixed\n", encoding="utf-8")
        inventory.write_text(
            "---\ncontainer_images:\n  - reference: fixed@sha256:example\n",
            encoding="utf-8",
        )
        metadata = self.root / f".lit/security-releases/{VERSION}.json"
        metadata.parent.mkdir()
        metadata.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "evidenceId": EVIDENCE_ID,
                    "createdAt": "2026-08-08T22:30:00Z",
                    "securityIdentifiers": ["CVE-2026-9793"],
                    "affectedVersion": "3.2.3",
                    "fixedVersion": VERSION,
                    "consumers": ["lightning-it/container-ee-wunder-ansible-ubi9"],
                    "acceptanceProfile": PROFILE,
                    "validity": {
                        "notBefore": "2026-08-08T22:30:00Z",
                        "expiresAt": "2026-09-08T22:30:00Z",
                        "revoked": False,
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        fragment = self.root / "changelogs/fragments/keycloak-security.yml"
        fragment.parent.mkdir(parents=True)
        fragment.write_bytes(MODULE.INTAKE.CONTRACT.canonical_security_fragment_bytes(["Keycloak fix."]))
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "Security candidate")
        self.head = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/develop", self.head)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def commit_candidate_mutation(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "mutate Security candidate")
        head = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/develop", head)
        return head

    def prepare_recovery_topology(
        self,
        *,
        mutate_marker: bool = False,
        add_receipt: bool = False,
    ) -> dict[str, Any]:
        """Create the exact protected-promotion shape required by recovery."""

        fragment_path = self.root / "changelogs/fragments/keycloak-security.yml"
        fragment_path.write_bytes(HISTORICAL_FRAGMENT)
        git(self.root, "add", fragment_path.relative_to(self.root).as_posix())
        git(self.root, "commit", "-q", "-m", "preserve historical Security fragment")
        historical_head = git(self.root, "rev-parse", "HEAD")
        approved_main = historical_head
        control_path = self.root / ".github/workflows/security-release-dispatch.yml"
        control_path.parent.mkdir(parents=True, exist_ok=True)
        control_path.write_text("name: recovered controller\n", encoding="utf-8")
        control_paths = {control_path.relative_to(self.root).as_posix()}

        metadata_path = self.root / f".lit/security-releases/{VERSION}.json"
        if mutate_marker:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata_path.write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            control_paths.add(metadata_path.relative_to(self.root).as_posix())

        if add_receipt:
            receipt_path = self.root / f".lit/security-release-intakes/{VERSION}.json"
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text('{"already":"present"}\n', encoding="utf-8")
            control_paths.add(receipt_path.relative_to(self.root).as_posix())

        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "protected recovery controller")
        promotion_head = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/develop", promotion_head)

        git(self.root, "checkout", "-q", "-B", "recovery-main", approved_main)
        git(
            self.root,
            "merge",
            "-q",
            "--no-ff",
            "-m",
            "promote protected recovery controller",
            promotion_head,
        )
        current_main = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/main", current_main)

        metadata_raw = metadata_path.read_bytes()
        fragment_path = "changelogs/fragments/keycloak-security.yml"
        return {
            "approved_main": approved_main,
            "current_main": current_main,
            "promotion_head": promotion_head,
            "bindings": {
                "RECOVERY_APPROVED_MAIN_SHA": approved_main,
                "RECOVERY_CANDIDATE_BASE_SHA": self.base,
                "RECOVERY_CANDIDATE_HEAD_SHA": historical_head,
                "RECOVERY_CANDIDATE_DIFF_SHA256": MODULE.INTAKE.sha256(
                    MODULE.INTAKE.canonical_diff(self.root, self.base, historical_head)
                ),
                "RECOVERY_METADATA_SHA256": MODULE.INTAKE.sha256(metadata_raw),
                "RECOVERY_EVIDENCE_ID": EVIDENCE_ID,
                "RECOVERY_FIXED_VERSION": VERSION,
                "RECOVERY_ACCEPTANCE_PROFILE": PROFILE,
                "RECOVERY_ISSUED_AT": "2026-08-08T22:30:00Z",
                "RECOVERY_EXPIRES_AT": "2026-09-08T22:30:00Z",
                "RECOVERY_FRAGMENT_PATH": fragment_path,
                "RECOVERY_FRAGMENT_SHA256": MODULE.INTAKE.sha256(HISTORICAL_FRAGMENT),
                "RECOVERY_CONTROL_PATHS": frozenset(control_paths),
            },
        }

    def recovery_request(self, current_main: str) -> dict[str, Any]:
        contract = MODULE.INTAKE.CONTRACT
        request = {
            "schemaVersion": contract.INTAKE_REQUEST_SCHEMA_VERSION,
            "event": contract.RECOVERY_EVENT,
            "repository": REPOSITORY,
            "repositoryId": contract.PRODUCER_REPOSITORY_ID,
            "baseSha": current_main,
            "candidateRef": "develop",
            "candidateBaseSha": contract.RECOVERY_CANDIDATE_BASE_SHA,
            "candidateHeadSha": contract.RECOVERY_CANDIDATE_HEAD_SHA,
            "candidateDiffSha256": contract.RECOVERY_CANDIDATE_DIFF_SHA256,
            "evidenceId": contract.RECOVERY_EVIDENCE_ID,
            "fixedVersion": contract.RECOVERY_FIXED_VERSION,
            "acceptanceProfile": contract.RECOVERY_ACCEPTANCE_PROFILE,
            "metadataSha256": contract.RECOVERY_METADATA_SHA256,
            "chainId": contract.compute_chain_id(
                repository=REPOSITORY,
                repository_id=contract.PRODUCER_REPOSITORY_ID,
                base_sha=current_main,
                candidate_head_sha=contract.RECOVERY_CANDIDATE_HEAD_SHA,
                candidate_diff_sha256=contract.RECOVERY_CANDIDATE_DIFF_SHA256,
                evidence_id=contract.RECOVERY_EVIDENCE_ID,
                fixed_version=contract.RECOVERY_FIXED_VERSION,
                acceptance_profile=contract.RECOVERY_ACCEPTANCE_PROFILE,
            ),
            "issuedAt": contract.RECOVERY_ISSUED_AT,
            "expiresAt": contract.RECOVERY_EXPIRES_AT,
            "humanActions": 0,
        }
        return MODULE.INTAKE.validate_request(request, REPOSITORY, NOW)

    def test_recovery_build_and_repository_verification_accept_exact_promotion(self) -> None:
        recovery = self.prepare_recovery_topology()
        with mock.patch.multiple(MODULE.INTAKE.CONTRACT, **recovery["bindings"]):
            envelope = MODULE.build_recovery_envelope(
                self.root,
                REPOSITORY,
                recovery["current_main"],
                recovery["promotion_head"],
                NOW,
            )
            self.assertIs(envelope["dispatch"], True)
            patch, result = MODULE.INTAKE.verify_recovery_repository(
                self.root,
                envelope["request"],
                NOW,
            )
        self.assertEqual(
            MODULE.INTAKE.canonical_diff(
                self.root,
                self.base,
                recovery["bindings"]["RECOVERY_CANDIDATE_HEAD_SHA"],
            ),
            patch,
        )
        self.assertEqual(EVIDENCE_ID, result["evidenceId"])
        self.assertEqual(0, result["humanActions"])

    def test_recovery_build_reads_source_state_from_git_objects(self) -> None:
        recovery = self.prepare_recovery_topology()
        git(self.root, "checkout", "-q", self.base)
        self.assertFalse((self.root / f".lit/security-releases/{VERSION}.json").exists())
        with mock.patch.multiple(MODULE.INTAKE.CONTRACT, **recovery["bindings"]):
            envelope = MODULE.build_recovery_envelope(
                self.root,
                REPOSITORY,
                recovery["current_main"],
                recovery["promotion_head"],
                NOW,
            )
        self.assertIs(envelope["dispatch"], True)
        self.assertEqual(recovery["current_main"], envelope["request"]["baseSha"])

    def test_recovery_rejects_non_merge_protected_main_topology(self) -> None:
        recovery = self.prepare_recovery_topology()
        git(
            self.root,
            "update-ref",
            "refs/remotes/origin/main",
            recovery["promotion_head"],
        )
        with (
            mock.patch.multiple(MODULE.INTAKE.CONTRACT, **recovery["bindings"]),
            self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "first protected promotion"),
        ):
            MODULE.build_recovery_envelope(
                self.root,
                REPOSITORY,
                recovery["promotion_head"],
                recovery["promotion_head"],
                NOW,
            )

    def test_recovery_rejects_control_path_outside_exact_allowlist(self) -> None:
        recovery = self.prepare_recovery_topology()
        bindings = dict(recovery["bindings"])
        bindings["RECOVERY_CONTROL_PATHS"] = frozenset()
        with (
            mock.patch.multiple(MODULE.INTAKE.CONTRACT, **bindings),
            self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "exact approved allowlist"),
        ):
            MODULE.build_recovery_envelope(
                self.root,
                REPOSITORY,
                recovery["current_main"],
                recovery["promotion_head"],
                NOW,
            )

    def test_recovery_rejects_mutated_immutable_marker(self) -> None:
        recovery = self.prepare_recovery_topology(mutate_marker=True)
        with (
            mock.patch.multiple(MODULE.INTAKE.CONTRACT, **recovery["bindings"]),
            self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "immutable Git identities"),
        ):
            MODULE.build_recovery_envelope(
                self.root,
                REPOSITORY,
                recovery["current_main"],
                recovery["promotion_head"],
                NOW,
            )

    def test_recovery_rejects_historical_diff_digest_mismatch(self) -> None:
        recovery = self.prepare_recovery_topology()
        bindings = dict(recovery["bindings"])
        bindings["RECOVERY_CANDIDATE_DIFF_SHA256"] = "sha256:" + ("0" * 64)
        with (
            mock.patch.multiple(MODULE.INTAKE.CONTRACT, **bindings),
            self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "historical Security candidate diff"),
        ):
            MODULE.build_recovery_envelope(
                self.root,
                REPOSITORY,
                recovery["current_main"],
                recovery["promotion_head"],
                NOW,
            )

    def test_recovery_rejects_historical_fragment_digest_mismatch(self) -> None:
        recovery = self.prepare_recovery_topology()
        bindings = dict(recovery["bindings"])
        bindings["RECOVERY_FRAGMENT_SHA256"] = "sha256:" + ("0" * 64)
        with (
            mock.patch.multiple(MODULE.INTAKE.CONTRACT, **bindings),
            self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "fragment digest"),
        ):
            MODULE.build_recovery_envelope(
                self.root,
                REPOSITORY,
                recovery["current_main"],
                recovery["promotion_head"],
                NOW,
            )

    def test_recovery_rejects_existing_app_owned_intake_receipt(self) -> None:
        recovery = self.prepare_recovery_topology(add_receipt=True)
        with mock.patch.multiple(MODULE.INTAKE.CONTRACT, **recovery["bindings"]):
            request = self.recovery_request(recovery["current_main"])
            with self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "receipt already exists"):
                MODULE.INTAKE.verify_recovery_repository(self.root, request, NOW)

    def test_exact_candidate_builds_a_valid_human_actions_zero_request(self) -> None:
        envelope = MODULE.build_envelope(
            self.root,
            REPOSITORY,
            self.base,
            self.head,
            NOW,
        )
        self.assertIs(envelope["dispatch"], True)
        request = envelope["request"]
        self.assertEqual(self.base, request["baseSha"])
        self.assertEqual(self.head, request["candidateHeadSha"])
        self.assertEqual(EVIDENCE_ID, request["evidenceId"])
        self.assertEqual(0, request["humanActions"])
        self.assertEqual(2, request["schemaVersion"])
        self.assertEqual(MODULE.INTAKE.CONTRACT.PRODUCER_REPOSITORY_ID, request["repositoryId"])
        self.assertEqual(PROFILE, request["acceptanceProfile"])
        self.assertRegex(request["chainId"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(request["metadataSha256"], r"^sha256:[0-9a-f]{64}$")

    def test_candidate_diff_is_independent_of_hostile_local_git_diff_config(self) -> None:
        expected = MODULE.INTAKE.canonical_diff(self.root, self.base, self.head)
        attributes = self.root / "host-global-attributes"
        attributes.write_text("*.yml diff=hostile\n", encoding="utf-8")
        git(self.root, "config", "core.attributesFile", str(attributes))
        git(self.root, "config", "diff.renames", "copies")
        git(self.root, "config", "diff.algorithm", "histogram")
        git(self.root, "config", "diff.indentHeuristic", "true")
        git(self.root, "config", "diff.external", "false")
        git(self.root, "config", "diff.hostile.textconv", "false")
        self.assertEqual(
            expected,
            MODULE.INTAKE.canonical_diff(self.root, self.base, self.head),
        )

    def test_dispatch_cli_emits_canonical_request_json_for_workflow_input(self) -> None:
        envelope_path = self.root / "dispatch-envelope.json"
        request_path = self.root / "workflow-request.json"
        arguments = [
            "security-release-dispatch.py",
            "--repository",
            REPOSITORY,
            "--base-sha",
            self.base,
            "--head-sha",
            self.head,
            "--root",
            str(self.root),
            "--now",
            "2026-08-08T23:00:00Z",
            "--output-json",
            str(envelope_path),
            "--output-request-json",
            str(request_path),
        ]
        with (
            mock.patch.object(sys, "argv", arguments),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(0, MODULE.main())
        envelope = MODULE.INTAKE.CONTRACT.load_json_file(
            self.root,
            envelope_path.relative_to(self.root),
            "dispatch envelope",
        )
        request = MODULE.INTAKE.load_canonical_request(request_path)
        self.assertEqual(envelope["request"], request)
        self.assertEqual(request_path.read_bytes(), MODULE.INTAKE.CONTRACT.canonical_document_bytes(request))

    def test_intake_cli_emits_only_canonical_observed_app_receipt(self) -> None:
        request = MODULE.build_envelope(self.root, REPOSITORY, self.base, self.head, NOW)["request"]
        request_path = self.root / "intake-request.json"
        request_path.write_bytes(MODULE.INTAKE.CONTRACT.canonical_document_bytes(request))
        result_path = self.root / "intake-result.json"
        receipt_path = self.root / "intake-receipt.json"
        permissions_path = self.root / "app-permissions.json"
        permissions_path.write_bytes(
            MODULE.INTAKE.CONTRACT.canonical_document_bytes(MODULE.INTAKE.CONTRACT.RELEASE_APP_PERMISSIONS)
        )
        arguments = [
            "security-release-intake.py",
            "--request",
            str(request_path),
            "--repository",
            REPOSITORY,
            "--root",
            str(self.root),
            "--now",
            "2026-08-08T23:00:00Z",
            "--output-json",
            str(result_path),
            "--output-intake-receipt",
            str(receipt_path),
            "--workflow-run-id",
            "123456",
            "--workflow-attempt",
            "1",
            "--workflow-ref",
            f"{REPOSITORY}/.github/workflows/security-release-intake.yml@refs/heads/main",
            "--workflow-event",
            "workflow_dispatch",
            "--workflow-actor",
            MODULE.INTAKE.CONTRACT.RELEASE_APP_LOGIN,
            "--workflow-triggering-actor",
            MODULE.INTAKE.CONTRACT.RELEASE_APP_LOGIN,
            "--observed-app-slug",
            MODULE.INTAKE.CONTRACT.RELEASE_APP_SLUG,
            "--observed-app-installation-id",
            MODULE.INTAKE.CONTRACT.RELEASE_APP_INSTALLATION_ID,
            "--observed-app-login",
            MODULE.INTAKE.CONTRACT.RELEASE_APP_LOGIN,
            "--observed-app-account-id",
            MODULE.INTAKE.CONTRACT.RELEASE_APP_ACCOUNT_ID,
            "--observed-app-permissions",
            str(permissions_path),
        ]
        for repository in MODULE.INTAKE.CONTRACT.RELEASE_APP_SELECTED_REPOSITORIES:
            arguments.extend(("--observed-app-repository", repository))
        with (
            mock.patch.object(sys, "argv", arguments),
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(0, MODULE.INTAKE.main())
        result = MODULE.INTAKE.CONTRACT.load_json_file(
            self.root,
            result_path.relative_to(self.root),
            "intake result",
        )
        receipt = MODULE.INTAKE.CONTRACT.load_json_file(
            self.root,
            receipt_path.relative_to(self.root),
            "intake receipt",
        )
        self.assertEqual(result_path.read_bytes(), MODULE.INTAKE.CONTRACT.canonical_document_bytes(result))
        self.assertEqual(receipt_path.read_bytes(), MODULE.INTAKE.CONTRACT.canonical_document_bytes(receipt))
        self.assertEqual(MODULE.INTAKE.CONTRACT.RELEASE_APP_IDENTITY, receipt["automation"])
        noncanonical = self.root / "noncanonical-request.json"
        noncanonical.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "canonical compact JSON"):
            MODULE.INTAKE.load_canonical_request(noncanonical)

    def test_ordinary_develop_change_does_not_mint_a_dispatch_request(self) -> None:
        git(self.root, "checkout", "-q", self.base)
        product = self.root / "roles/keycloak_deploy/defaults/main.yml"
        product.write_text("---\nkeycloak_deploy_image: ordinary\n", encoding="utf-8")
        git(self.root, "add", ".")
        git(self.root, "commit", "-q", "-m", "ordinary change")
        head = git(self.root, "rev-parse", "HEAD")
        git(self.root, "update-ref", "refs/remotes/origin/develop", head)
        self.assertEqual(
            {"dispatch": False},
            MODULE.build_envelope(self.root, REPOSITORY, self.base, head, NOW),
        )

    def test_wrong_consumer_fails_before_dispatch(self) -> None:
        metadata_path = self.root / f".lit/security-releases/{VERSION}.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["consumers"] = [
            "lightning-it/container-ee-wunder-ansible-ubi9",
            "example/unapproved",
        ]
        head = self.commit_candidate_mutation(
            metadata_path,
            json.dumps(metadata, sort_keys=True) + "\n",
        )
        with self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "exact MLX-90 consumer"):
            MODULE.build_envelope(self.root, REPOSITORY, self.base, head, NOW)

    def test_noncanonical_security_fragment_fails_before_dispatch(self) -> None:
        fragment = self.root / "changelogs/fragments/keycloak-security.yml"
        head = self.commit_candidate_mutation(
            fragment,
            "---\nsecurity_fixes:\n  - Non-canonical YAML.\n",
        )
        with self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "invalid quoted YAML scalar"):
            MODULE.build_envelope(self.root, REPOSITORY, self.base, head, NOW)

    def test_candidate_cannot_supply_or_mutate_app_owned_receipts(self) -> None:
        receipt = self.root / f".lit/security-release-intakes/{VERSION}.json"
        head = self.commit_candidate_mutation(receipt, '{"forged":true}\n')
        with self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "App-owned Security intake receipts"):
            MODULE.build_envelope(self.root, REPOSITORY, self.base, head, NOW)

    def test_duplicate_metadata_keys_fail_closed(self) -> None:
        metadata_path = self.root / f".lit/security-releases/{VERSION}.json"
        content = metadata_path.read_text(encoding="utf-8").rstrip()
        duplicate = content[:-1] + ',"fixedVersion":"3.2.4"}\n'
        head = self.commit_candidate_mutation(metadata_path, duplicate)
        with self.assertRaisesRegex(MODULE.INTAKE.IntakeError, "duplicate JSON key"):
            MODULE.build_envelope(self.root, REPOSITORY, self.base, head, NOW)

    def test_controller_workflow_is_default_branch_bound_and_least_privilege(self) -> None:
        dispatch = WORKFLOW.read_text(encoding="utf-8")
        intake = INTAKE_WORKFLOW.read_text(encoding="utf-8")
        allowlist = tuple(MODULE.INTAKE.CONTRACT.RELEASE_APP_SELECTED_REPOSITORIES)

        self.assertIn("workflow_run:", dispatch)
        self.assertIn("workflows: [Collection CI]", dispatch)
        self.assertIn("branches: [develop, main]", dispatch)
        self.assertIn("source_run_id:", dispatch)
        self.assertIn("gh workflow run security-release-dispatch.yml", dispatch)
        self.assertIn("--ref main", dispatch)
        self.assertIn("github.actor == 'github-actions[bot]'", dispatch)
        self.assertIn("github.triggering_actor == 'github-actions[bot]'", dispatch)
        self.assertIn("github.event.workflow_run.event == 'push'", dispatch)
        self.assertNotIn("pull_request:", dispatch)
        self.assertEqual(4, dispatch.count("ref: ${{ github.sha }}"))
        self.assertNotIn("ref: develop", dispatch)
        self.assertNotIn("ref: ${{ github.event.workflow_run.head_sha }}", dispatch)
        self.assertNotIn("ref: ${{ needs.classify.outputs.source-sha }}", dispatch)
        self.assertIn("needs.classify.outputs['source-sha']", dispatch)
        self.assertIn("needs.classify.outputs.dispatch == 'true'", dispatch)
        self.assertIn("environment: mlx90-security-release-evidence", dispatch)
        self.assertIn("permission-actions: write", dispatch)
        self.assertEqual(2, dispatch.count("permission-metadata: read"))
        self.assertNotIn("permission-contents: write", dispatch)
        self.assertNotIn("permission-pull-requests: write", dispatch)
        self.assertNotIn("permission-workflows", dispatch)
        self.assertNotIn("repository_dispatch", dispatch)
        self.assertIn("--output-request-json", dispatch)
        self.assertIn("--recover-existing-marker", dispatch)
        self.assertIn("mlx90-security-release-recovery", dispatch)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", dispatch)
        recovery_flow = dispatch[dispatch.index("  classify-recovery:") : dispatch.index("\n  classify:\n")]
        self.assertEqual(3, recovery_flow.count("CONTROLLER_SHA: ${{ github.sha }}"))
        self.assertNotIn('CONTROLLER_SHA="$(git rev-parse HEAD)"', recovery_flow)
        self.assertNotIn("steps.request.outputs.controller_sha", recovery_flow)
        self.assertEqual(
            3,
            recovery_flow.count('test "$(git show -s --format=%T "$CONTROLLER_SHA")" ='),
        )
        self.assertIn("Bind the single approved existing-marker recovery", dispatch)
        self.assertIn("Dispatch approved recovery as release App", dispatch)
        self.assertNotIn("needs.classify-recovery", dispatch)
        self.assertNotIn("steps.recovery-app", dispatch)
        self.assertEqual(4, dispatch.count("needs['classify-recovery']"))
        self.assertGreaterEqual(dispatch.count("steps['recovery-app"), 6)
        self.assertIn("inputs:{request_json:$request_json}", dispatch)
        self.assertIn(
            "actions/workflows/security-release-intake.yml/dispatches",
            dispatch,
        )
        self.assertIn('test "$APP_INSTALLATION_ID" = 148019054', dispatch)
        self.assertIn(".id == 307565056", dispatch)
        self.assertIn('gh api "apps/${APP_SLUG}"', dispatch)
        self.assertIn('"checks": "read"', dispatch)
        self.assertIn("gh api --paginate --slurp", dispatch)
        self.assertEqual(
            2,
            dispatch.count("repositories: ${{ github.event.repository.name }}"),
        )
        dispatch_attestation = dispatch[
            dispatch.index("- name: Mint installation-wide metadata-only App attestation token") : dispatch.index(
                "- name: Verify exact App installation and repository scope"
            )
        ]
        dispatch_mutation = dispatch[
            dispatch.index("- name: Mint repository-scoped release automation App token") : dispatch.index(
                "- name: Revalidate and dispatch exact request to immutable main intake"
            )
        ]
        self.assertIn("permission-metadata: read", dispatch_attestation)
        self.assertNotIn("repositories:", dispatch_attestation)
        self.assertNotIn("permission-actions: write", dispatch_attestation)
        self.assertIn(
            "repositories: ${{ github.event.repository.name }}",
            dispatch_mutation,
        )
        self.assertIn("permission-actions: write", dispatch_mutation)
        self.assertNotIn("permission-metadata: read", dispatch_mutation)
        for repository in allowlist:
            self.assertEqual(2, dispatch.count(f'"{repository}"'))
        self.assertLess(
            dispatch.index("Reconstruct exact validated request before token access"),
            dispatch.index("Mint installation-wide metadata-only App attestation token"),
        )
        self.assertLess(
            dispatch.index("Mint installation-wide metadata-only App attestation token"),
            dispatch.index("Verify exact App installation and repository scope"),
        )
        self.assertLess(
            dispatch.index("Verify exact App installation and repository scope"),
            dispatch.index("Mint repository-scoped release automation App token"),
        )
        self.assertLess(
            dispatch.index("Mint repository-scoped release automation App token"),
            dispatch.index("Revalidate and dispatch exact request to immutable main intake"),
        )
        relay_run = dispatch[
            dispatch.index("- name: Dispatch immutable main-ref controller") : dispatch.index("  classify-recovery:")
        ]
        classify_start = dispatch.index("- name: Construct and fully validate immutable Security request")
        classify_run = dispatch[classify_start : dispatch.index("\n  dispatch:\n", classify_start)]
        self.assertNotIn("authenticated_fetch()", relay_run)
        self.assertIn("authenticated_fetch()", classify_run)

        self.assertIn("workflow_dispatch:", intake)
        self.assertIn("request_json:", intake)
        self.assertNotIn("repository_dispatch:", intake)
        self.assertNotIn("client_payload", intake)
        self.assertIn("github.ref == 'refs/heads/main'", intake)
        self.assertGreaterEqual(
            intake.count("github.actor == 'lightning-it-release-automation[bot]'"),
            2,
        )
        self.assertGreaterEqual(
            intake.count("github.triggering_actor == 'lightning-it-release-automation[bot]'"),
            2,
        )
        self.assertIn("permission-contents: write", intake)
        self.assertIn("permission-pull-requests: write", intake)
        self.assertEqual(1, intake.count("permission-metadata: read"))
        self.assertNotIn("permission-actions: write", intake)
        self.assertNotIn("permission-workflows", intake)
        self.assertEqual(
            1,
            intake.count("repositories: ${{ github.event.repository.name }}"),
        )
        intake_attestation = intake[
            intake.index("- name: Mint installation-wide metadata-only App attestation token") : intake.index(
                "- name: Verify exact App installation identity and complete allowlist"
            )
        ]
        intake_mutation = intake[
            intake.index("- name: Mint repository-scoped release automation App token") : intake.index(
                "- name: Revalidate exact request and mint canonical v2 receipt before mutation"
            )
        ]
        self.assertIn("permission-metadata: read", intake_attestation)
        self.assertNotIn("repositories:", intake_attestation)
        self.assertNotIn("permission-contents: write", intake_attestation)
        self.assertNotIn("permission-pull-requests: write", intake_attestation)
        self.assertIn(
            "repositories: ${{ github.event.repository.name }}",
            intake_mutation,
        )
        self.assertIn("permission-contents: write", intake_mutation)
        self.assertIn("permission-pull-requests: write", intake_mutation)
        self.assertNotIn("permission-metadata: read", intake_mutation)
        self.assertIn("--output-intake-receipt", intake)
        self.assertIn("mlx90-security-release-recovery", intake)
        self.assertIn('git merge-base --is-ancestor "$candidate_head" origin/develop', intake)
        self.assertIn('if [ "$REQUEST_EVENT" = mlx90-security-release ]; then', intake)
        self.assertIn("--workflow-triggering-actor", intake)
        self.assertIn(".schemaVersion == 2", intake)
        self.assertIn('.controller.event == "workflow_dispatch"', intake)
        self.assertIn('test "$APP_INSTALLATION_ID" = 148019054', intake)
        self.assertIn(".id == 307565056", intake)
        self.assertIn('gh api "apps/${APP_SLUG}"', intake)
        self.assertIn("--observed-app-permissions", intake)
        self.assertIn(".automation.permissions == {", intake)
        self.assertIn("gh api --paginate --slurp", intake)
        for repository in allowlist:
            self.assertGreaterEqual(intake.count(repository), 2)
        self.assertLess(
            intake.index("Revalidate live request and run before App token access"),
            intake.index("Mint installation-wide metadata-only App attestation token"),
        )
        self.assertLess(
            intake.index("Mint installation-wide metadata-only App attestation token"),
            intake.index("Verify exact App installation identity and complete allowlist"),
        )
        self.assertLess(
            intake.index("Verify exact App installation identity and complete allowlist"),
            intake.index("Mint repository-scoped release automation App token"),
        )
        self.assertLess(
            intake.index("Mint repository-scoped release automation App token"),
            intake.index("Revalidate exact request and mint canonical v2 receipt before mutation"),
        )
        self.assertIn(
            'test "$MUTATION_APP_INSTALLATION_ID" = "$APP_INSTALLATION_ID"',
            intake,
        )
        self.assertLess(
            intake.index("Revalidate exact request and mint canonical v2 receipt before mutation"),
            intake.index("Create or prove exact App-authored isolated commit"),
        )
        self.assertIn('test "$(git show -s --format=%P "$head_sha")" = "$BASE_SHA"', intake)
        self.assertIn('test "$(git show -s --format=%T "$head_sha")" = "$tree_sha"', intake)
        self.assertIn(".user.id == 307565056", intake)
        self.assertIn("--auto --merge --match-head-commit", intake)
        self.assertIn('.auto_merge.merge_method == "merge"', intake)
        self.assertIn(".merged_by.id == 307565056", intake)
        self.assertIn('test "$first_parent" = "$BASE_SHA"', intake)
        self.assertIn('test "$second_parent" = "$HEAD_SHA"', intake)
        self.assertNotIn("--admin", intake)
        self.assertNotIn("--force", intake)


if __name__ == "__main__":
    unittest.main()
