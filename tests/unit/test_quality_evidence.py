"""Focused tests for the collection-wide evidence implementation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import quality_evidence as evidence


class QualityEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repository = self.base / "repository"
        self.artifacts = self.repository / "artifacts"
        self.evidence_root = self.artifacts / "evidence"
        (self.artifacts / "junit").mkdir(parents=True)
        (self.repository / "meta").mkdir(parents=True)
        (self.repository / "galaxy.yml").write_text(
            "namespace: lit\nname: supplementary\nversion: 1.2.3\n", encoding="utf-8"
        )

    def _registry(self) -> Path:
        registry = {
            "schema_version": 1,
            "allowed_profile_states": ["supported", "not-applicable"],
            "targets": {"ubuntu-24.04": {"family": "ubuntu"}},
            "roles": {
                "demo_role": {
                    "maturity": "production",
                    "supported_targets": ["ubuntu-24.04"],
                    "tiny": "supported",
                    "heavy": "not-applicable",
                    "application_acceptance": "not-applicable",
                }
            },
            "scenarios": {
                "demo-tiny": {
                    "profile": "tiny",
                    "state": "supported",
                    "implementation": "real",
                    "roles": ["demo_role"],
                    "test_application": {
                        "mode": "runtime-container",
                        "reason": ("The scenario deploys an independently versioned application container."),
                        "dependencies": [],
                    },
                }
            },
        }
        path = self.repository / "meta" / "role-coverage.yml"
        # JSON is a YAML subset and keeps this unit test independent of emitters.
        path.write_text(json.dumps(registry), encoding="utf-8")
        return path

    def _junit(
        self,
        *,
        status: str = "passed",
        opaque: bool = False,
        commit: str = "a" * 40,
        framework: str = "junit",
    ) -> Path:
        problem = ""
        if status == "failure":
            problem = '<failure type="AssertionError" message="expected readiness"/>'
        name = "molecule process" if opaque else "readiness endpoint"
        content = f"""<?xml version="1.0"?>
<testsuite name="demo-tiny" tests="99" failures="0">
  <properties>
    <property name="role" value="demo_role"/>
    <property name="profile" value="tiny"/>
    <property name="scenario" value="demo-tiny"/>
    <property name="target" value="ubuntu-24.04"/>
    <property name="run_attempt" value="2"/>
    <property name="commit_sha" value="{commit}"/>
    <property name="framework" value="{framework}"/>
  </properties>
  <testcase classname="demo.health" name="{name}" time="0.2">{problem}</testcase>
  <testcase classname="demo.security" name="permissions" time="0.1"/>
</testsuite>
"""
        path = self.artifacts / "junit" / "demo-tiny-ubuntu-24.04.xml"
        path.write_text(content, encoding="utf-8")
        return path

    def _environment(self, sha: str = "a" * 40) -> dict[str, str]:
        return {
            "GITHUB_SHA": sha,
            "GITHUB_RUN_ATTEMPT": "2",
            "GITHUB_RUN_ID": "1234",
            "GITHUB_REPOSITORY": "lightning-it/ansible-collection-supplementary",
        }

    def _release_security(self, sha: str) -> None:
        security = self.evidence_root / "security"
        security.mkdir(parents=True, exist_ok=True)
        (security / "sbom.cdx.json").write_text(
            json.dumps(
                {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.5",
                    "version": 1,
                    "metadata": {
                        "component": {
                            "type": "application",
                            "group": "lit",
                            "name": "supplementary",
                            "version": "1.2.3",
                            "hashes": [{"alg": "SHA-256", "content": "f" * 64}],
                        }
                    },
                    "components": [],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (security / "vulnerability-report.json").write_text(
            json.dumps(
                {
                    "matches": [],
                    "descriptor": {"name": "grype", "version": "0.99.0"},
                    "source": {
                        "type": "sbom-file",
                        "target": "artifacts/evidence/security/sbom.cdx.json",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (security / "provenance.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "repository": "lightning-it/ansible-collection-supplementary",
                    "commit_sha": sha,
                    "workflow_run_id": "1234",
                    "workflow_attempt": "2",
                    "candidate": "lit-supplementary-1.2.3.tar.gz",
                    "candidate_sha256": "f" * 64,
                    "generated_at": "2026-07-14T00:00:00+00:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (security / "secret-scan-summary.json").write_text(
            json.dumps(
                {
                    "version": "1.5.0",
                    "plugins_used": [{"name": "KeywordDetector"}],
                    "filters_used": [],
                    "results": {},
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _release_dependencies(self, root: Path | None = None, *, source_commit: str = "a" * 40) -> None:
        dependencies = (root or self.artifacts) / "dependencies"
        dependencies.mkdir(parents=True, exist_ok=True)
        registry_path = self._registry()
        registry_content = registry_path.read_bytes()
        (dependencies / "ansible-version.txt").write_text("ansible [core 2.19.3]\n", encoding="utf-8")
        (dependencies / "molecule-version.txt").write_text("molecule 25.9.0\n", encoding="utf-8")
        (dependencies / "python-version.txt").write_text("Python 3.13.7\n", encoding="utf-8")
        (dependencies / "python-packages.json").write_text(
            json.dumps([{"name": "ansible-core", "version": "2.19.3"}]) + "\n", encoding="utf-8"
        )
        (dependencies / "collection-dependencies.json").write_text(
            json.dumps({"/collections": {"lit.supplementary": {"version": "1.2.3"}}}) + "\n",
            encoding="utf-8",
        )
        (dependencies / "incus-base-image.json").write_text(
            json.dumps({"fingerprint": "a" * 64, "architecture": "x86_64"}) + "\n",
            encoding="utf-8",
        )
        (dependencies / "execution-environment-digest.txt").write_text(
            "mode=host-native\ndigest=not-applicable\nreason=no execution-environment image is used by this profile\n",
            encoding="utf-8",
        )
        inventory = dependencies / "demo-tiny" / "ubuntu-24.04"
        inventory.mkdir(parents=True, exist_ok=True)
        container_inventory = inventory / "demo-container-image-digests.json"
        container_inventory.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "scenario": "demo-tiny",
                    "target": "ubuntu-24.04",
                    "instance": "demo-instance",
                    "requested_image": "images:ubuntu/24.04",
                    "incus_base_image_fingerprint": "a" * 64,
                    "container_inventory_available": True,
                    "images": [
                        {
                            "Names": ["quay.io/keycloak/keycloak:26.4"],
                            "Digest": "sha256:" + "b" * 64,
                            "Id": "c" * 64,
                        }
                    ],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        config_content = "---\ndriver:\n  name: incus\n"
        config_evidence = dependencies / "scenario-config-demo-tiny-ubuntu-24.04.yml"
        config_evidence.write_text(config_content, encoding="utf-8")
        source_config = self.repository / "molecule" / "demo-tiny" / "molecule.yml"
        source_config.parent.mkdir(parents=True, exist_ok=True)
        source_config.write_text(config_content, encoding="utf-8")
        config_sha = hashlib.sha256(config_content.encode()).hexdigest()
        registry_evidence = dependencies / "role-coverage-demo-tiny-ubuntu-24.04.yml"
        registry_evidence.write_bytes(registry_content)
        registry_policy = json.loads(registry_content)["scenarios"]["demo-tiny"]["test_application"]
        (dependencies / "test-application-dependencies.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "profile": "tiny",
                    "scenario": "demo-tiny",
                    "target": "ubuntu-24.04",
                    "source_commit": source_commit,
                    "scenario_config": {
                        "path": "molecule/demo-tiny/molecule.yml",
                        "sha256": config_sha,
                        "evidence_file": config_evidence.name,
                    },
                    "registry_policy": {
                        "path": "meta/role-coverage.yml",
                        "sha256": hashlib.sha256(registry_content).hexdigest(),
                        "evidence_file": registry_evidence.name,
                    },
                    "test_application_policy": registry_policy,
                    "applications": [
                        {
                            "type": "container",
                            "name": "quay.io/keycloak/keycloak:26.4",
                            "version": "sha256:" + "b" * 64,
                            "digest": "sha256:" + "b" * 64,
                            "source": "runtime-container",
                            "source_inventory": ("demo-tiny/ubuntu-24.04/demo-container-image-digests.json"),
                            "evidence_sha256": hashlib.sha256(container_inventory.read_bytes()).hexdigest(),
                        }
                    ],
                    "disposition": None,
                    "descriptor": None,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _native_allure(
        self,
        *,
        sha: str = "a" * 40,
        target: str = "ubuntu-24.04",
        first_status: str = "passed",
    ) -> None:
        root = self.artifacts / "allure-results"
        root.mkdir(parents=True)
        cases = (
            ("demo.health", "readiness endpoint", first_status),
            ("demo.security", "permissions", "passed"),
        )
        for index, (classname, name, status) in enumerate(cases):
            payload = {
                "uuid": f"native-{index}",
                "name": name,
                "fullName": f"{classname}.{name}",
                "status": status,
                "labels": [
                    {"name": "role", "value": "demo_role"},
                    {"name": "profile", "value": "tiny"},
                    {"name": "suite", "value": "demo-tiny"},
                    {"name": "host", "value": target},
                    {"name": "runAttempt", "value": "2"},
                    {"name": "commit_sha", "value": sha},
                ],
            }
            (root / f"native-{index}-result.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def _rewrite_checksums(self) -> None:
        checksum = self.evidence_root / "checksums" / "SHA256SUMS"
        paths = [path for path in sorted(self.evidence_root.rglob("*")) if path.is_file() and path != checksum]
        checksum.write_text(
            "".join(f"{evidence.sha256(path)}  {path.relative_to(self.evidence_root).as_posix()}\n" for path in paths),
            encoding="utf-8",
        )

    @staticmethod
    def _prerequisites(status: str = "success") -> dict[str, str]:
        values = {name: "success" for name in evidence.MANDATORY_PREREQUISITES}
        values["heavy"] = status
        return values

    def test_parse_junit_uses_testcases_and_rejects_opaque_process_pass(self) -> None:
        path = self._junit()
        report = evidence.parse_junit(path)
        self.assertEqual(report["totals"], {"tests": 2, "failures": 0, "errors": 0, "skipped": 0})
        self.assertEqual(report["status"], "passed")

        path.write_text(
            '<testsuite name="x"><testcase classname="molecule" name="molecule process"/></testsuite>',
            encoding="utf-8",
        )
        opaque = evidence.parse_junit(path)
        self.assertFalse(opaque["meaningful"])
        self.assertEqual(opaque["status"], "failed")

    def test_assemble_copies_redacts_and_derives_per_test_allure(self) -> None:
        self._registry()
        self._junit()
        (self.artifacts / "logs").mkdir()
        (self.artifacts / "logs" / "molecule.log").write_text("password=never-publish-this\n", encoding="utf-8")
        (self.artifacts / "configuration").mkdir()
        (self.artifacts / "configuration" / "inventory.yml").write_text(
            "client_secret: hidden-value\n", encoding="utf-8"
        )
        (self.artifacts / "dependencies").mkdir()
        (self.artifacts / "dependencies" / "python-version.txt").write_text("3.11\n", encoding="utf-8")
        (self.artifacts / "playwright-traces").mkdir()
        with zipfile.ZipFile(self.artifacts / "playwright-traces" / "trace.zip", "w") as archive:
            archive.writestr("network.txt", f"authorization={evidence.CANARY}\n")

        with patch.dict(os.environ, self._environment(), clear=False):
            result = evidence.assemble(
                self.evidence_root,
                input_roots=[self.artifacts],
                registry_path=self.repository / "meta" / "role-coverage.yml",
                repository_root=self.repository,
            )
        self.assertEqual(result, 0)
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["release_eligible"])
        self.assertEqual(manifest["results"][0]["id"], "demo_role/tiny/demo-tiny/ubuntu-24.04/attempt-2")
        self.assertEqual(len(manifest["results"][0]["allure_results"]), 2)
        self.assertTrue(manifest["secret_scan"]["canary_detected_before_redaction"])
        self.assertTrue(manifest["secret_scan"]["clean"])
        self.assertNotIn(
            "never-publish-this",
            (self.evidence_root / "logs" / "molecule.log").read_text(encoding="utf-8"),
        )
        with zipfile.ZipFile(self.evidence_root / "playwright-traces" / "trace.zip") as archive:
            self.assertNotIn(evidence.CANARY, archive.read("network.txt").decode("utf-8"))
        with patch.dict(os.environ, self._environment(), clear=False):
            self.assertEqual(evidence.validate(self.evidence_root), 0)

    def test_candidate_evidence_passes_execution_but_is_never_release_eligible(self) -> None:
        registry_path = self._registry()
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["roles"]["demo_role"]["candidate_targets"] = ["ubuntu-24.04"]
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        self._junit()

        cells = evidence.expected_cells(
            registry,
            run_attempt="2",
            target_disposition="candidate",
        )
        self.assertEqual(1, len(cells))
        self.assertEqual("candidate", cells[0]["target_disposition"])
        self.assertFalse(cells[0]["release_required"])

        with patch.dict(os.environ, self._environment(), clear=False):
            result = evidence.assemble(
                self.evidence_root,
                input_roots=[self.artifacts],
                registry_path=registry_path,
                repository_root=self.repository,
                candidate_mode=True,
            )
        self.assertEqual(0, result)
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("candidate", manifest["mode"])
        self.assertTrue(manifest["candidate_execution_passed"])
        self.assertFalse(manifest["release_eligible"])
        with patch.dict(os.environ, self._environment(), clear=False):
            self.assertEqual(0, evidence.validate(self.evidence_root))

    def test_shared_scenario_target_mismatch_fails_closed_in_evidence_matrix(self) -> None:
        registry = {
            "targets": {
                "ubuntu-24.04": {},
                "rhel-9": {},
            },
            "roles": {
                "role_a": {
                    "maturity": "production",
                    "tiny": "supported",
                    "supported_targets": ["ubuntu-24.04", "rhel-9"],
                    "candidate_targets": [],
                },
                "role_b": {
                    "maturity": "production",
                    "tiny": "supported",
                    "supported_targets": ["ubuntu-24.04"],
                    "candidate_targets": [],
                },
            },
            "scenarios": {
                "shared-tiny": {
                    "profile": "tiny",
                    "state": "supported",
                    "implementation": "real",
                    "roles": ["role_a", "role_b"],
                }
            },
        }
        errors = evidence.shared_scenario_target_errors(registry)
        self.assertTrue(any("must declare identical supported_targets" in error for error in errors), errors)
        with self.assertRaisesRegex(evidence.EvidenceError, "must declare identical supported_targets"):
            evidence.expected_cells(registry, run_attempt="1")

        registry["roles"]["role_b"]["supported_targets"] = ["ubuntu-24.04", "rhel-9"]
        cells = evidence.expected_cells(registry, run_attempt="1")
        self.assertEqual({"ubuntu-24.04", "rhel-9"}, {cell["target"] for cell in cells})
        self.assertTrue(all(cell["roles"] == ["role_a", "role_b"] for cell in cells))

    def test_missing_junit_is_recorded_as_infrastructure_error(self) -> None:
        self._registry()
        with patch.dict(os.environ, self._environment(), clear=False):
            result = evidence.assemble(
                self.evidence_root,
                input_roots=[self.artifacts],
                registry_path=self.repository / "meta" / "role-coverage.yml",
                repository_root=self.repository,
            )
        self.assertEqual(result, 1)
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["release_eligible"])
        self.assertEqual(manifest["results"][0]["status"], "infrastructure-error")
        self.assertTrue(manifest["results"][0]["junit"])

    def test_release_requires_security_and_rejects_commit_mismatch(self) -> None:
        sha = "b" * 40
        self._registry()
        self._junit(commit=sha)
        self._release_security(sha)
        self._release_dependencies(source_commit=sha)
        environment = {
            **self._environment(sha),
            "QUALITY_EVIDENCE_PREREQUISITES_JSON": json.dumps(self._prerequisites()),
        }
        with patch.dict(os.environ, environment, clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                    release_mode=True,
                ),
                0,
            )
            self.assertEqual(evidence.validate(self.evidence_root, release_mode=True), 0)
            self.assertEqual(evidence.validate(self.evidence_root, release_mode=True, expected_commit="c" * 40), 1)
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["prerequisites"], self._prerequisites())

    def test_release_fails_closed_without_dependency_evidence(self) -> None:
        sha = "b" * 40
        self._registry()
        self._junit(commit=sha)
        self._release_security(sha)
        environment = {
            **self._environment(sha),
            "QUALITY_EVIDENCE_PREREQUISITES_JSON": json.dumps(self._prerequisites()),
        }
        with patch.dict(os.environ, environment, clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                    release_mode=True,
                ),
                1,
            )
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["release_eligible"])
        expected_blockers = {
            "release dependency evidence lacks controller Ansible version",
            "release dependency evidence lacks controller Molecule version",
            "release dependency evidence lacks controller Python version",
            "release dependency evidence lacks a Python package inventory",
            "release dependency evidence lacks an Ansible collection inventory",
            "release dependency evidence lacks an Incus base-image identity",
            "release dependency evidence lacks an execution-environment disposition",
            "release dependency evidence lacks a test-application inventory",
            "mandatory matrix cell demo-tiny/ubuntu-24.04 lacks a test-application inventory",
        }
        self.assertTrue(expected_blockers.issubset(set(manifest["blockers"])), manifest["blockers"])

    def test_checksum_validation_detects_tampering(self) -> None:
        self._registry()
        self._junit()
        with patch.dict(os.environ, self._environment(), clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                ),
                0,
            )
            (self.evidence_root / "environment.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(evidence.validate(self.evidence_root), 1)

    def test_test_report_commit_mismatch_is_ineligible(self) -> None:
        self._registry()
        junit = self._junit()
        content = junit.read_text(encoding="utf-8").replace(
            "</properties>",
            f'<property name="commit_sha" value="{"d" * 40}"/></properties>',
        )
        junit.write_text(content, encoding="utf-8")
        with patch.dict(os.environ, self._environment("e" * 40), clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                ),
                1,
            )
            manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["commit_consistent"])
            self.assertEqual(evidence.validate(self.evidence_root), 1)

    def test_release_rejects_semantically_empty_security_json(self) -> None:
        sha = "b" * 40
        self._registry()
        self._junit(commit=sha)
        self._release_security(sha)
        for name in evidence.REQUIRED_RELEASE_SECURITY_FILES:
            (self.evidence_root / "security" / name).write_text("{}\n", encoding="utf-8")
        with patch.dict(os.environ, self._environment(sha), clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                    release_mode=True,
                ),
                1,
            )
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["security_evidence"]["semantic_valid"])
        self.assertFalse(manifest["release_eligible"])

    def test_security_evidence_binds_exact_collection_version_and_candidate_digest(self) -> None:
        sha = "b" * 40
        self._release_security(sha)
        collection = self.evidence_root / "collection"
        collection.mkdir()
        (collection / "galaxy.yml").write_text(
            (self.repository / "galaxy.yml").read_text(encoding="utf-8"), encoding="utf-8"
        )
        summary, errors = evidence.assess_security(self.evidence_root, release_mode=True, commit_sha=sha)
        self.assertEqual(errors, [])
        self.assertTrue(summary["semantic_valid"])

        sbom_path = self.evidence_root / "security" / "sbom.cdx.json"
        valid_sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        cases = (
            ("identity", "group", "unrelated", "collection identity and version"),
            ("version", "version", "9.9.9", "collection identity and version"),
        )
        for label, field, value, expected_error in cases:
            with self.subTest(label=label):
                changed = json.loads(json.dumps(valid_sbom))
                changed["metadata"]["component"][field] = value
                sbom_path.write_text(json.dumps(changed) + "\n", encoding="utf-8")
                summary, errors = evidence.assess_security(self.evidence_root, release_mode=True, commit_sha=sha)
                self.assertFalse(summary["semantic_valid"])
                self.assertTrue(any(expected_error in error for error in errors), errors)

        changed = json.loads(json.dumps(valid_sbom))
        changed.pop("metadata")
        changed["components"] = [{"type": "library", "name": "unrelated", "version": "1.2.3"}]
        sbom_path.write_text(json.dumps(changed) + "\n", encoding="utf-8")
        summary, errors = evidence.assess_security(self.evidence_root, release_mode=True, commit_sha=sha)
        self.assertFalse(summary["semantic_valid"])
        self.assertTrue(any("metadata candidate component" in error for error in errors), errors)

        changed = json.loads(json.dumps(valid_sbom))
        changed["metadata"]["component"]["hashes"][0]["content"] = "e" * 64
        sbom_path.write_text(json.dumps(changed) + "\n", encoding="utf-8")
        summary, errors = evidence.assess_security(self.evidence_root, release_mode=True, commit_sha=sha)
        self.assertFalse(summary["semantic_valid"])
        self.assertTrue(any("not bound to candidate_sha256" in error for error in errors), errors)

        sbom_path.write_text(json.dumps(valid_sbom) + "\n", encoding="utf-8")
        provenance_path = self.evidence_root / "security" / "provenance.json"
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["candidate"] = "lit-supplementary-9.9.9.tar.gz"
        provenance_path.write_text(json.dumps(provenance) + "\n", encoding="utf-8")
        summary, errors = evidence.assess_security(self.evidence_root, release_mode=True, commit_sha=sha)
        self.assertFalse(summary["semantic_valid"])
        self.assertTrue(any("candidate does not match" in error for error in errors), errors)

    def test_vulnerability_report_must_name_grype_and_the_bound_sbom_source(self) -> None:
        sha = "b" * 40
        self._release_security(sha)
        collection = self.evidence_root / "collection"
        collection.mkdir()
        (collection / "galaxy.yml").write_text(
            (self.repository / "galaxy.yml").read_text(encoding="utf-8"), encoding="utf-8"
        )
        report_path = self.evidence_root / "security" / "vulnerability-report.json"
        valid_report = json.loads(report_path.read_text(encoding="utf-8"))
        cases = (
            ("directory source", {"type": "directory", "target": "artifacts/candidate"}, "SBOM source"),
            ("different SBOM", {"type": "sbom-file", "target": "other.cdx.json"}, "sbom.cdx.json"),
        )
        for label, source, expected_error in cases:
            with self.subTest(label=label):
                changed = json.loads(json.dumps(valid_report))
                changed["source"] = source
                report_path.write_text(json.dumps(changed) + "\n", encoding="utf-8")
                summary, errors = evidence.assess_security(self.evidence_root, release_mode=True, commit_sha=sha)
                self.assertFalse(summary["semantic_valid"])
                self.assertTrue(any(expected_error in error for error in errors), errors)

        changed = json.loads(json.dumps(valid_report))
        changed["descriptor"]["name"] = "unrelated-scanner"
        report_path.write_text(json.dumps(changed) + "\n", encoding="utf-8")
        summary, errors = evidence.assess_security(self.evidence_root, release_mode=True, commit_sha=sha)
        self.assertFalse(summary["semantic_valid"])
        self.assertTrue(any("Grype scanner identity" in error for error in errors), errors)

    def test_release_dependencies_require_controller_and_dependency_inventories(self) -> None:
        self._release_dependencies(self.evidence_root)
        self.assertEqual(evidence.assess_dependencies(self.evidence_root, release_mode=True), [])

        dependencies = self.evidence_root / "dependencies"
        version_cases = (
            ("ansible-version.txt", "controller Ansible version"),
            ("molecule-version.txt", "controller Molecule version"),
            ("python-version.txt", "controller Python version"),
        )
        for filename, expected_error in version_cases:
            with self.subTest(filename=filename):
                self._release_dependencies(self.evidence_root)
                (dependencies / filename).unlink()
                errors = evidence.assess_dependencies(self.evidence_root, release_mode=True)
                self.assertTrue(any(expected_error in error for error in errors), errors)

        self._release_dependencies(self.evidence_root)
        (dependencies / "python-packages.json").write_text("[]\n", encoding="utf-8")
        errors = evidence.assess_dependencies(self.evidence_root, release_mode=True)
        self.assertTrue(any("empty or malformed Python package inventory" in error for error in errors), errors)

        self._release_dependencies(self.evidence_root)
        (dependencies / "collection-dependencies.json").write_text("{}\n", encoding="utf-8")
        errors = evidence.assess_dependencies(self.evidence_root, release_mode=True)
        self.assertTrue(any("empty or malformed Ansible collection inventory" in error for error in errors), errors)

        self._release_dependencies(self.evidence_root)
        (dependencies / "incus-base-image.json").write_text(
            json.dumps({"fingerprint": "mutable-alias"}) + "\n", encoding="utf-8"
        )
        errors = evidence.assess_dependencies(self.evidence_root, release_mode=True)
        self.assertTrue(any("immutable Incus base-image fingerprint" in error for error in errors), errors)

        self._release_dependencies(self.evidence_root)
        (dependencies / "execution-environment-digest.txt").write_text(
            "mode=host-native\ndigest=not-applicable\n", encoding="utf-8"
        )
        errors = evidence.assess_dependencies(self.evidence_root, release_mode=True)
        self.assertTrue(any("invalid execution-environment disposition" in error for error in errors), errors)

    def test_release_dependencies_bind_acceptance_target_venv_inventory_to_cell(self) -> None:
        sha = "a" * 40
        self._release_dependencies(self.evidence_root, source_commit=sha)
        dependencies = self.evidence_root / "dependencies"
        target_inventory = dependencies / "python-packages-keycloak-acceptance-target.json"
        payload = {
            "schema_version": 1,
            "source": "target-venv",
            "profile": "application-acceptance",
            "scenario": "keycloak-application-acceptance",
            "target": "ubuntu-24.04",
            "source_commit": sha,
            "packages": [
                {"name": "Flask", "version": "3.1.2"},
                {"name": "playwright", "version": "1.55.0"},
            ],
        }
        target_inventory.write_text(json.dumps(payload), encoding="utf-8")
        cell = {
            "profile": "application-acceptance",
            "scenario": "keycloak-application-acceptance",
            "target": "ubuntu-24.04",
        }
        self.assertEqual(
            [],
            evidence.assess_dependencies(
                self.evidence_root,
                release_mode=True,
                expected_commit=sha,
            ),
        )

        payload["source_commit"] = "b" * 40
        target_inventory.write_text(json.dumps(payload), encoding="utf-8")
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            expected_commit=sha,
        )
        self.assertTrue(any("unbound target Python package inventory" in error for error in errors), errors)

        target_inventory.unlink()
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            expected_commit=sha,
            matrix_cells=[cell],
        )
        self.assertTrue(any("lacks a cell-bound target Python" in error for error in errors), errors)

    def test_release_dependencies_require_an_available_immutable_container_inventory(self) -> None:
        self._release_dependencies(self.evidence_root)
        inventory = (
            self.evidence_root / "dependencies" / "demo-tiny" / "ubuntu-24.04" / "demo-container-image-digests.json"
        )
        applications = self.evidence_root / "dependencies" / "test-application-dependencies.json"

        def bind_runtime_inventory(digest: str) -> None:
            application_payload = json.loads(applications.read_text(encoding="utf-8"))
            application_payload["applications"][0]["version"] = digest
            application_payload["applications"][0]["digest"] = digest
            application_payload["applications"][0]["evidence_sha256"] = hashlib.sha256(
                inventory.read_bytes()
            ).hexdigest()
            applications.write_text(json.dumps(application_payload) + "\n", encoding="utf-8")

        payload = json.loads(inventory.read_text(encoding="utf-8"))
        payload["images"] = [{"Names": ["quay.io/keycloak/keycloak:26.4"], "Id": "c" * 64}]
        inventory.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        bind_runtime_inventory("sha256:" + "c" * 64)
        self.assertEqual(evidence.assess_dependencies(self.evidence_root, release_mode=True), [])

        payload["container_inventory_available"] = False
        inventory.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        bind_runtime_inventory("sha256:" + "c" * 64)
        errors = evidence.assess_dependencies(self.evidence_root, release_mode=True)
        self.assertTrue(any("digests differ from container evidence" in error for error in errors), errors)

        payload["container_inventory_available"] = True
        payload["images"] = [{"Names": ["quay.io/keycloak/keycloak:latest"], "Id": "short-id"}]
        inventory.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        bind_runtime_inventory("sha256:" + "c" * 64)
        errors = evidence.assess_dependencies(self.evidence_root, release_mode=True)
        self.assertTrue(any("lacks an immutable digest or image ID" in error for error in errors), errors)

    def test_release_dependencies_require_cell_bound_playwright_browser_runtime(self) -> None:
        sha = "a" * 40
        self._release_dependencies(self.evidence_root, source_commit=sha)
        dependencies = self.evidence_root / "dependencies"
        (dependencies / "python-packages-keycloak-acceptance-target.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source": "target-venv",
                    "profile": "application-acceptance",
                    "scenario": "keycloak-application-acceptance",
                    "target": "ubuntu-24.04",
                    "source_commit": sha,
                    "packages": [{"name": "playwright", "version": "1.55.0"}],
                }
            ),
            encoding="utf-8",
        )
        cell = {
            "profile": "application-acceptance",
            "scenario": "keycloak-application-acceptance",
            "target": "ubuntu-24.04",
        }
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            expected_commit=sha,
            matrix_cells=[cell],
        )
        self.assertTrue(any("Playwright Chromium runtime inventory" in error for error in errors), errors)

        browser_inventory = dependencies / "browser-runtime-keycloak-acceptance-target.json"
        payload = {
            "schema_version": 1,
            "source": "playwright-target-runtime",
            "profile": "application-acceptance",
            "scenario": "keycloak-application-acceptance",
            "target": "ubuntu-24.04",
            "source_commit": sha,
            "playwright_version": "1.55.0",
            "chromium": {
                "name": "chromium",
                "revision": "1187",
                "version": "140.0.7339.16",
                "executable": "/root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome",
                "sha256": "b" * 64,
            },
            "operating_system": {
                "id": "ubuntu",
                "version_id": "24.04",
                "distro": "ubuntu-24.04",
            },
            "os_packages": [
                {
                    "name": "libc6",
                    "version": "2.39-0ubuntu8.4",
                    "architecture": "amd64",
                    "source_name": "glibc",
                    "source_version": "2.39-0ubuntu8.4",
                }
            ],
        }
        browser_inventory.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(
            [],
            evidence.assess_dependencies(
                self.evidence_root,
                release_mode=True,
                expected_commit=sha,
            ),
        )
        payload["chromium"]["sha256"] = "mutable"  # type: ignore[index]
        browser_inventory.write_text(json.dumps(payload), encoding="utf-8")
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            expected_commit=sha,
        )
        self.assertTrue(any("malformed browser runtime inventory" in error for error in errors), errors)

    def test_release_dependencies_require_matching_test_application_inventory(self) -> None:
        self._release_dependencies(self.evidence_root)
        applications = self.evidence_root / "dependencies" / "test-application-dependencies.json"
        applications.unlink()
        errors = evidence.assess_dependencies(self.evidence_root, release_mode=True)
        self.assertTrue(any("lacks a test-application inventory" in error for error in errors), errors)
        self.assertTrue(any("has no test-application inventory" in error for error in errors), errors)

        self._release_dependencies(self.evidence_root)
        payload = json.loads(applications.read_text(encoding="utf-8"))
        payload["applications"][0]["digest"] = "sha256:" + "e" * 64
        payload["applications"][0]["version"] = "sha256:" + "e" * 64
        applications.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        errors = evidence.assess_dependencies(self.evidence_root, release_mode=True)
        self.assertTrue(any("digests differ" in error for error in errors), errors)

    def test_declared_and_not_applicable_test_applications_are_source_bound(self) -> None:
        self._release_dependencies(self.evidence_root)
        dependencies = self.evidence_root / "dependencies"
        inventory_path = dependencies / "test-application-dependencies.json"
        container_inventory = dependencies / "demo-tiny" / "ubuntu-24.04" / "demo-container-image-digests.json"
        container_inventory.unlink()
        declared_evidence = self.evidence_root / "test-applications" / "demo-tiny" / "declared-application-version.txt"
        declared_evidence.parent.mkdir(parents=True)
        declared_evidence.write_text("demo-api=2026.07.14\n", encoding="utf-8")
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        declared_policy = {
            "mode": "declared-evidence",
            "reason": "The scenario exercises a versioned external API dependency.",
            "dependencies": [
                {
                    "type": "external-api",
                    "name": "demo-api",
                    "version": "2026.07.14",
                    "evidence_path": ("test-applications/demo-tiny/declared-application-version.txt"),
                }
            ],
        }
        payload["applications"] = [
            {
                "type": "external-api",
                "name": "demo-api",
                "version": "2026.07.14",
                "source": "declared-evidence",
                "evidence_path": "test-applications/demo-tiny/declared-application-version.txt",
                "evidence_sha256": hashlib.sha256(declared_evidence.read_bytes()).hexdigest(),
            }
        ]
        payload["descriptor"] = None
        payload["test_application_policy"] = declared_policy
        registry_path = self.repository / "meta" / "role-coverage.yml"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["scenarios"]["demo-tiny"]["test_application"] = declared_policy
        registry_content = json.dumps(registry).encode()
        registry_path.write_bytes(registry_content)
        registry_evidence = dependencies / payload["registry_policy"]["evidence_file"]
        registry_evidence.write_bytes(registry_content)
        payload["registry_policy"]["sha256"] = hashlib.sha256(registry_content).hexdigest()
        inventory_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        matrix = [{"scenario": "demo-tiny", "target": "ubuntu-24.04", "profile": "tiny"}]
        self.assertEqual(
            evidence.assess_dependencies(
                self.evidence_root,
                release_mode=True,
                expected_commit="a" * 40,
                repository_root=self.repository,
                matrix_cells=matrix,
            ),
            [],
        )

        not_applicable_policy = {
            "mode": "not-applicable",
            "reason": "This scenario has no separate test application dependency.",
            "dependencies": [],
        }
        payload["applications"] = []
        payload["disposition"] = {
            "status": "not-applicable",
            "reason": not_applicable_policy["reason"],
        }
        payload["test_application_policy"] = not_applicable_policy
        registry["scenarios"]["demo-tiny"]["state"] = "experimental"
        registry["scenarios"]["demo-tiny"]["implementation"] = "partial"
        registry["scenarios"]["demo-tiny"]["test_application"] = not_applicable_policy
        registry_content = json.dumps(registry).encode()
        registry_path.write_bytes(registry_content)
        registry_evidence.write_bytes(registry_content)
        payload["registry_policy"]["sha256"] = hashlib.sha256(registry_content).hexdigest()
        inventory_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        self.assertEqual(
            evidence.assess_dependencies(
                self.evidence_root,
                release_mode=True,
                expected_commit="a" * 40,
                repository_root=self.repository,
                matrix_cells=matrix,
            ),
            [],
        )

        registry_path.write_bytes(registry_content + b"\n")
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            expected_commit="a" * 40,
            repository_root=self.repository,
            matrix_cells=matrix,
        )
        self.assertTrue(any("registry differs from exact source" in error for error in errors), errors)

    def test_test_application_identity_rejects_wrong_source_and_descriptor_override(self) -> None:
        self._release_dependencies(self.evidence_root)
        applications = self.evidence_root / "dependencies" / "test-application-dependencies.json"
        payload = json.loads(applications.read_text(encoding="utf-8"))
        payload["profile"] = "application_acceptance"
        applications.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        matrix = [
            {
                "scenario": "demo-tiny",
                "target": "ubuntu-24.04",
                "profile": "application_acceptance",
            }
        ]
        self.assertEqual(
            evidence.assess_dependencies(
                self.evidence_root,
                release_mode=True,
                expected_commit="a" * 40,
                repository_root=self.repository,
                matrix_cells=matrix,
            ),
            [],
        )

        payload["source_commit"] = "b" * 40
        applications.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            expected_commit="a" * 40,
            repository_root=self.repository,
            matrix_cells=matrix,
        )
        self.assertTrue(any("source commit differs" in error for error in errors), errors)

        payload["source_commit"] = "a" * 40
        payload["descriptor"] = {
            "path": "molecule/demo-tiny/test-application-dependencies.yml",
            "sha256": "c" * 64,
            "evidence_file": "forged.yml",
        }
        applications.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            expected_commit="a" * 40,
            repository_root=self.repository,
            matrix_cells=matrix,
        )
        self.assertTrue(any("forbidden scenario-owned" in error for error in errors), errors)

        payload["descriptor"] = None
        applications.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        source_config = self.repository / "molecule" / "demo-tiny" / "molecule.yml"
        source_config.write_text("---\ndriver:\n  name: docker\n", encoding="utf-8")
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            expected_commit="a" * 40,
            repository_root=self.repository,
            matrix_cells=matrix,
        )
        self.assertTrue(any("scenario configuration differs from exact source" in error for error in errors), errors)

    def test_test_application_policy_and_mode_tampering_is_rejected(self) -> None:
        self._release_dependencies(self.evidence_root)
        inventory_path = self.evidence_root / "dependencies" / "test-application-dependencies.json"
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
        payload["test_application_policy"] = {
            "mode": "not-applicable",
            "reason": "A forged inventory cannot replace the exact registry policy.",
            "dependencies": [],
        }
        inventory_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            repository_root=self.repository,
        )
        self.assertTrue(any("policy differs from the exact registry" in error for error in errors), errors)

        payload["test_application_policy"] = json.loads(
            (self.repository / "meta" / "role-coverage.yml").read_text(encoding="utf-8")
        )["scenarios"]["demo-tiny"]["test_application"]
        payload["applications"] = []
        payload["disposition"] = {
            "status": "not-applicable",
            "reason": "A runtime scenario cannot self-declare that no application exists.",
        }
        inventory_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        errors = evidence.assess_dependencies(
            self.evidence_root,
            release_mode=True,
            repository_root=self.repository,
        )
        rendered = "\n".join(errors)
        self.assertIn("runtime-container policy has no test applications", rendered)
        self.assertIn("runtime-container policy has a disposition", rendered)

    def test_failed_or_wrong_identity_native_allure_cannot_satisfy_pytest_junit(self) -> None:
        self._registry()
        self._junit(framework="pytest")
        self._native_allure(first_status="failed")
        with patch.dict(os.environ, self._environment(), clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                ),
                1,
            )
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["release_eligible"])
        self.assertTrue(any("Allure status" in item for item in manifest["blockers"]))

        for path in (self.artifacts / "allure-results").glob("*-result.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["status"] = "passed"
            for label in payload["labels"]:
                if label["name"] == "host":
                    label["value"] = "wrong-target"
            path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        with patch.dict(os.environ, self._environment(), clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                ),
                1,
            )

    def test_shared_report_requires_meaningful_cases_for_each_role(self) -> None:
        registry = {
            "schema_version": 1,
            "allowed_profile_states": ["supported", "not-applicable"],
            "targets": {"ubuntu-24.04": {"family": "ubuntu"}},
            "roles": {
                role: {
                    "maturity": "production",
                    "supported_targets": ["ubuntu-24.04"],
                    "tiny": "supported",
                    "heavy": "not-applicable",
                    "application_acceptance": "not-applicable",
                }
                for role in ("role_a", "role_b")
            },
            "scenarios": {
                "shared-tiny": {
                    "profile": "tiny",
                    "state": "supported",
                    "implementation": "real",
                    "roles": ["role_a", "role_b"],
                }
            },
        }
        registry_path = self.repository / "meta" / "role-coverage.yml"
        registry_path.write_text(json.dumps(registry), encoding="utf-8")
        (self.artifacts / "junit" / "shared-tiny.xml").write_text(
            f"""<testsuite name="shared-tiny">
  <properties>
    <property name="roles" value="role_a,role_b"/>
    <property name="profile" value="tiny"/>
    <property name="scenario" value="shared-tiny"/>
    <property name="target" value="ubuntu-24.04"/>
    <property name="run_attempt" value="2"/>
    <property name="commit_sha" value="{"a" * 40}"/>
  </properties>
  <testcase classname="shared.role_a" name="role-a-proof" role="role_a"/>
</testsuite>\n""",
            encoding="utf-8",
        )
        with patch.dict(os.environ, self._environment(), clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=registry_path,
                    repository_root=self.repository,
                ),
                1,
            )
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        by_role = {item["role"]: item for item in manifest["results"]}
        self.assertEqual(by_role["role_a"]["status"], "passed")
        self.assertEqual(by_role["role_b"]["status"], "infrastructure-error")
        self.assertNotIn("role-a-proof", {case["name"] for case in by_role["role_b"]["test_cases"]})

    def test_structured_headers_basic_auth_and_api_keys_are_redacted_and_scanned(self) -> None:
        root = self.base / "redaction"
        root.mkdir()
        structured = root / "structured.json"
        structured.write_text(
            json.dumps(
                {
                    "properties": [
                        {"name": "password", "value": "lowentropy-secret-value"},
                        {"header": "Cookie", "value": "session=private-cookie"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        headers = root / "headers.txt"
        headers.write_text(
            "Authorization: Basic dXNlcjpwYXNzd29yZA==\n"
            "Cookie: session=private-cookie\n"
            "X-API-Key: lowentropy-api-key\n",
            encoding="utf-8",
        )
        before = evidence.scan_evidence(root)
        self.assertFalse(before["clean"])
        self.assertIn("structured-secret", {item["kind"] for item in before["findings"]})
        self.assertIn("basic-authorization", {item["kind"] for item in before["findings"]})
        evidence.redact_file(structured)
        evidence.redact_file(headers)
        after = evidence.scan_evidence(root)
        self.assertTrue(after["clean"], after)
        self.assertNotIn("lowentropy-secret-value", structured.read_text(encoding="utf-8"))
        self.assertNotIn("dXNlcjpwYXNzd29yZA", headers.read_text(encoding="utf-8"))

    def test_unknown_junit_commit_is_ineligible(self) -> None:
        self._registry()
        self._junit(commit="unknown")
        with patch.dict(os.environ, self._environment(), clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                ),
                1,
            )
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(any("exact tested commit" in item for item in manifest["blockers"]))

    def test_release_requires_authoritative_nonempty_registry_matrix(self) -> None:
        sha = "b" * 40
        self._junit(commit=sha)
        self._release_security(sha)
        with patch.dict(os.environ, self._environment(sha), clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "missing-role-coverage.yml",
                    repository_root=self.repository,
                    release_mode=True,
                ),
                1,
            )
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["matrix"]["expected"], [])
        self.assertEqual(manifest["support_classification"], "unregistered")
        self.assertFalse(manifest["release_eligible"])

    def test_validate_rederives_allure_and_manifest_structure(self) -> None:
        self._registry()
        self._junit()
        with patch.dict(os.environ, self._environment(), clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                ),
                0,
            )
            manifest_path = self.evidence_root / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            allure_path = self.evidence_root / manifest["results"][0]["allure_results"][0]
            allure = json.loads(allure_path.read_text(encoding="utf-8"))
            allure["status"] = "failed"
            allure_path.write_text(json.dumps(allure) + "\n", encoding="utf-8")
            self._rewrite_checksums()
            self.assertEqual(evidence.validate(self.evidence_root), 1)

            allure["status"] = "passed"
            allure_path.write_text(json.dumps(allure) + "\n", encoding="utf-8")
            del manifest["expected_commit_sha"]
            manifest["matrix"] = []
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            self._rewrite_checksums()
            self.assertEqual(evidence.validate(self.evidence_root), 1)

    def test_archive_processing_is_bounded(self) -> None:
        root = self.base / "bounded"
        root.mkdir()
        archive_path = root / "trace.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("member.txt", "x" * 64)
        with patch.object(evidence, "MAX_ARCHIVE_MEMBER_BYTES", 32):
            scan = evidence.scan_evidence(root)
            self.assertFalse(scan["clean"])
            self.assertTrue(any("member exceeds scan limit" in item for item in scan["errors"]))
            with self.assertRaises(evidence.EvidenceError):
                evidence.redact_file(archive_path)

    def test_supplied_prerequisites_must_be_complete_and_successful(self) -> None:
        self._registry()
        self._junit()
        environment = {
            **self._environment(),
            "QUALITY_EVIDENCE_PREREQUISITES_JSON": json.dumps(self._prerequisites("failure")),
        }
        with patch.dict(os.environ, environment, clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                ),
                1,
            )
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["prerequisites"]["heavy"], "failure")
        self.assertTrue(any("prerequisite heavy" in item for item in manifest["blockers"]))

        environment["QUALITY_EVIDENCE_PREREQUISITES_JSON"] = json.dumps({"lint": "success"})
        with patch.dict(os.environ, environment, clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                ),
                1,
            )
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(any("status is missing" in item for item in manifest["blockers"]))

        statuses = {**self._prerequisites(), "unexpected": "success"}
        environment["QUALITY_EVIDENCE_PREREQUISITES_JSON"] = json.dumps(statuses)
        with patch.dict(os.environ, environment, clear=False):
            self.assertEqual(
                evidence.assemble(
                    self.evidence_root,
                    input_roots=[self.artifacts],
                    registry_path=self.repository / "meta" / "role-coverage.yml",
                    repository_root=self.repository,
                ),
                1,
            )
        manifest = json.loads((self.evidence_root / "manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(any("unknown mandatory prerequisite" in item for item in manifest["blockers"]))

    def test_record_returns_success_but_preserves_failure_for_aggregation(self) -> None:
        log = self.artifacts / "scenario.log"
        log.write_text("molecule failed\n", encoding="utf-8")
        with patch.dict(os.environ, self._environment(), clear=False):
            result = evidence.record(
                scenario="demo-heavy",
                profile="heavy",
                target="ubuntu-24.04",
                roles=["demo_role"],
                exit_code=17,
                log_path=log,
                results_root=self.artifacts / "results",
            )
        self.assertEqual(result, 0)
        records = list((self.artifacts / "results").rglob("result.json"))
        self.assertEqual(len(records), 1)
        payload = json.loads(records[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "infrastructure-error")
        self.assertEqual(payload["process_exit_code"], 17)
        self.assertTrue(list((self.artifacts / "results").rglob("*-result.json")))


if __name__ == "__main__":
    unittest.main()
