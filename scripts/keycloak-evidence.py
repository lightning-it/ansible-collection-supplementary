#!/usr/bin/env python3
"""Assemble, redact, checksum, and validate Keycloak test evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MANDATORY_SCENARIOS = ("keycloak-tiny", "keycloak-heavy", "keycloak-application-acceptance")
SECRET_KEYS = re.compile(
    r"(?i)(password|secret|client_secret|access_token|refresh_token|id_token|authorization|cookie|set-cookie|bind_credential|private_key)"
)
SECRET_VALUES = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~-]+|(?:password|secret|token|authorization|cookie|bind_credential)\s*[:=]\s*[^\s,}\]]+)"
)
CANARY = "LIT_KEYCLOAK_REDACTION_CANARY_7f38f67e"
REQUIRED_SECURITY_FILES = (
    "sbom.cdx.json",
    "vulnerability-report.json",
    "provenance.json",
    "secret-scan-summary.json",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_text(value: str) -> str:
    value = value.replace(CANARY, "[REDACTED]")
    return SECRET_VALUES.sub("[REDACTED]", value)


def redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if SECRET_KEYS.search(str(key)) else redact_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    return redact_text(value) if isinstance(value, str) else value


def redact_file(path: Path) -> None:
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            path.write_text(json.dumps(redact_json(data), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    try:
        path.write_text(redact_text(path.read_text(encoding="utf-8")), encoding="utf-8")
    except UnicodeDecodeError:
        return


def junit_summary(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    return {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assemble(root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    for name in ("source", "collection", "test-results", "allure-results", "allure-report", "logs", "screenshots", "playwright-traces", "configuration", "dependencies", "security", "checksums"):
        (root / name).mkdir(exist_ok=True)

    source = root / "source"
    metadata = {
        "repository.txt": os.getenv("GITHUB_REPOSITORY", "lightning-it/ansible-collection-supplementary"),
        "branch.txt": os.getenv("GITHUB_REF_NAME", "local"),
        "commit-sha.txt": os.getenv("GITHUB_SHA", "unknown"),
        "workflow-run-id.txt": os.getenv("GITHUB_RUN_ID", "local"),
        "workflow-attempt.txt": os.getenv("GITHUB_RUN_ATTEMPT", "1"),
    }
    for filename, value in metadata.items():
        (source / filename).write_text(f"{value}\n", encoding="utf-8")

    environment = {
        "target": os.getenv("KEYCLOAK_TEST_TARGET", "unknown"),
        "keycloak_version": os.getenv("KEYCLOAK_VERSION", "unknown"),
        "postgresql_version": os.getenv("POSTGRESQL_VERSION", "unknown"),
        "ldap_version": os.getenv("LDAP_VERSION", "unknown"),
        "collection_version": os.getenv("COLLECTION_VERSION", "unknown"),
        "commit_sha": metadata["commit-sha.txt"],
        "workflow_run_id": metadata["workflow-run-id.txt"],
        "generated_at": utc_now(),
    }
    (root / "environment.json").write_text(
        json.dumps(environment, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    results: dict[str, Any] = {}
    eligible = True
    for scenario in MANDATORY_SCENARIOS:
        junit = root.parent / "junit" / f"{scenario}.xml"
        destination = root / "test-results" / junit.name
        if junit.exists():
            shutil.copy2(junit, destination)
            try:
                summary = junit_summary(destination)
                status = (
                    "passed"
                    if summary["tests"] > 0
                    and not summary["failures"]
                    and not summary["errors"]
                    and not summary["skipped"]
                    else "failed"
                )
            except (ET.ParseError, ValueError) as error:
                summary, status = {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}, "failed"
                results[scenario] = {"status": status, "error": f"malformed JUnit: {error}", "totals": summary}
            else:
                results[scenario] = {"status": status, "totals": summary}
        else:
            status = "infrastructure-error"
            results[scenario] = {"status": status, "error": f"missing {junit}"}
        eligible = eligible and status == "passed"

    allure_present = any((root / "allure-results").iterdir())
    eligible = eligible and allure_present
    missing_security = [name for name in REQUIRED_SECURITY_FILES if not (root / "security" / name).is_file()]
    eligible = eligible and not missing_security
    manifest = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "repository": metadata["repository.txt"],
        "commit_sha": metadata["commit-sha.txt"],
        "branch": metadata["branch.txt"],
        "workflow_run_id": metadata["workflow-run-id.txt"],
        "workflow_attempt": metadata["workflow-attempt.txt"],
        "actor": os.getenv("GITHUB_ACTOR", "local"),
        "runner": os.getenv("RUNNER_NAME", "local"),
        "collection_version": os.getenv("COLLECTION_VERSION", "unknown"),
        "platform": os.getenv("KEYCLOAK_TEST_TARGET", "unknown"),
        "scenarios": results,
        "allure_results_present": allure_present,
        "security_evidence": {
            "required": list(REQUIRED_SECURITY_FILES),
            "missing": missing_security,
        },
        "long_term_archive": os.getenv("KEYCLOAK_EVIDENCE_ARCHIVE_STATUS", "not-configured"),
        "release_eligible": eligible,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    canary = root / "logs" / ".redaction-canary"
    canary.write_text(f"password={CANARY}\n", encoding="utf-8")
    if CANARY not in canary.read_text(encoding="utf-8"):
        raise RuntimeError("redaction canary was not detectable before redaction")
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.parent.name != "checksums":
            redact_file(path)
    if any(CANARY.encode() in path.read_bytes() for path in root.rglob("*") if path.is_file()):
        raise RuntimeError("redaction canary remains in evidence")
    canary.unlink()

    checksum_file = root / "checksums" / "SHA256SUMS"
    paths = [path for path in sorted(root.rglob("*")) if path.is_file() and path != checksum_file]
    checksum_file.write_text("".join(f"{sha256(path)}  {path.relative_to(root)}\n" for path in paths), encoding="utf-8")
    return 0 if eligible else 1


def validate(root: Path) -> int:
    manifest_path = root / "manifest.json"
    checksum_path = root / "checksums" / "SHA256SUMS"
    if not manifest_path.is_file() or not checksum_path.is_file():
        print("missing evidence manifest or checksums", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            failures.append(relative)
    if manifest.get("release_eligible") is not True:
        failures.append("release_eligible=false")
    for name in REQUIRED_SECURITY_FILES:
        if not (root / "security" / name).is_file():
            failures.append(f"missing security/{name}")
    scenarios = manifest.get("scenarios", {})
    for scenario in MANDATORY_SCENARIOS:
        if scenarios.get(scenario, {}).get("status") != "passed":
            failures.append(f"{scenario} did not pass")
    if manifest.get("commit_sha") != os.getenv("GITHUB_SHA", manifest.get("commit_sha")):
        failures.append("tested commit differs from release commit")
    if failures:
        print("evidence validation failed: " + ", ".join(failures), file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("assemble", "validate"))
    parser.add_argument("--root", type=Path, default=Path("artifacts/evidence"))
    args = parser.parse_args()
    return assemble(args.root) if args.command == "assemble" else validate(args.root)


if __name__ == "__main__":
    raise SystemExit(main())
