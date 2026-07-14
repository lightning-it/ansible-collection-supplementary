# Keycloak Audit Evidence

Heavy and Application Acceptance runs produce `artifacts/evidence/`, including
source identity, collection metadata, JUnit, Allure data, redacted logs, failure
screenshots/traces, sanitized configuration, dependencies, SBOM, provenance,
secret-scan status, and SHA-256 checksums. `manifest.json` computes
`release_eligible`; it is never a manually maintained flag.

```bash
python3 scripts/keycloak-evidence.py assemble
python3 scripts/keycloak-evidence.py validate
```

Assembly plants a synthetic canary, proves it is detectable, redacts it, and
fails if it remains. Missing/malformed mandatory JUnit, skipped tests, missing
Allure, checksum mismatch, secret leakage, or commit mismatch is ineligible.

GitHub retains immediate artifacts for 90 days. Optional S3-compatible archival
uses `KEYCLOAK_EVIDENCE_S3_BUCKET`, `KEYCLOAK_EVIDENCE_S3_ENDPOINT`, and protected
access-key secrets. Enable encryption, versioning, and Object Lock/WORM; grant
least privilege to the collection prefix and place no secrets in metadata.

The pipeline creates a CycloneDX SBOM and provenance tied to the exact commit.
Trusted release environments use GitHub artifact attestations and keyless Cosign
where available. Private signing keys are never committed.
