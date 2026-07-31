"""Generate deterministic producer evidence for the MLX-90 contract.

Signing/attestation and consumer dispatch happen only after this payload and all
referenced release assets have been verified by the release workflow.
"""

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def file_ref(path: Path, url: str):
    return {"url": url, "digest": sha256(path)}


def timestamp(value: str, field: str):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{field} must be RFC3339") from None
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--id", required=True)
    p.add_argument("--security-id", required=True)
    p.add_argument("--affected-version", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--workflow-ref", required=True)
    p.add_argument("--artifact", type=Path, required=True)
    p.add_argument("--artifact-url", required=True)
    p.add_argument("--signature", type=Path, required=True)
    p.add_argument("--signature-url", required=True)
    p.add_argument("--sbom", type=Path, required=True)
    p.add_argument("--sbom-url", required=True)
    p.add_argument("--provenance", type=Path, required=True)
    p.add_argument("--provenance-url", required=True)
    p.add_argument("--consumer", action="append", required=True)
    p.add_argument("--acceptance-profile", required=True)
    p.add_argument("--created-at", required=True)
    p.add_argument("--not-before", required=True)
    p.add_argument("--expires-at", required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    for path in (a.artifact, a.signature, a.sbom, a.provenance):
        if path.is_symlink() or not path.is_file():
            p.error(f"release asset must be a regular non-symlink file: {path}")
    if not SHA.fullmatch(a.source_sha) or not SHA.fullmatch(a.workflow_ref):
        p.error("source/workflow refs must be full SHAs")
    for field in (a.artifact_url, a.signature_url, a.sbom_url, a.provenance_url):
        if not field.startswith("https://"):
            p.error("all artifact references must use HTTPS")
    try:
        created = timestamp(a.created_at, "--created-at")
        not_before = timestamp(a.not_before, "--not-before")
        expires = timestamp(a.expires_at, "--expires-at")
    except ValueError as exc:
        p.error(str(exc))
    if expires <= not_before:
        p.error("--expires-at must be after --not-before")
    if created < not_before or created >= expires:
        p.error("--created-at must be within the evidence validity interval")
    evidence = {
        "apiVersion": "lit.security-release/v1",
        "kind": "SecurityReleaseEvidence",
        "metadata": {"id": a.id, "createdAt": a.created_at},
        "security": {"identifiers": [a.security_id], "affectedVersion": a.affected_version, "fixedVersion": a.version},
        "producer": {
            "repository": "lightning-it/ansible-collection-supplementary",
            "sourceSha": a.source_sha,
            "workflowRepository": "lightning-it/ansible-collection-supplementary",
            "workflowRef": a.workflow_ref,
        },
        "artifact": {
            "collection": "lit.supplementary",
            "version": a.version,
            "digest": sha256(a.artifact),
            "releaseUrl": a.artifact_url,
            "signature": file_ref(a.signature, a.signature_url),
            "sbom": file_ref(a.sbom, a.sbom_url),
            "provenance": file_ref(a.provenance, a.provenance_url),
        },
        "consumers": sorted(set(a.consumer)),
        "acceptance": {
            "profile": a.acceptance_profile,
            "expectedCollection": "lit.supplementary",
            "expectedVersion": a.version,
        },
        "validity": {"notBefore": a.not_before, "expiresAt": a.expires_at, "revoked": False},
        "status": "approved",
    }
    a.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
