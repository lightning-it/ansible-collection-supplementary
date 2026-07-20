# Test troubleshooting

Start with the stable aggregate job, then inspect the exact profile/target child
and its JUnit/Allure evidence.

## Registry or generated matrix failure

```bash
python3 scripts/validate-role-coverage.py validate
python3 scripts/validate-role-coverage.py generate
python3 scripts/validate-role-coverage.py check
```

Generation is an intentional edit; commit the registry and generated documents
together.

## Incus preflight failure

```bash
incus version
incus info
incus image list
df -h .
grep MemAvailable /proc/meminfo
test -e /dev/kvm || echo 'VM profiles unavailable'
```

Do not recategorize an application failure as infrastructure error. Image,
daemon, KVM, disk, and runner outages are infrastructure errors; a deployed
service failing readiness is a test failure.

## Owned-resource cleanup

Read the ownership label shown by the shared lifecycle before deletion. If it
does not exactly match the current run, stop. Never bulk-delete by prefix.

## Evidence failure

```bash
python3 scripts/quality_evidence.py validate --root artifacts/evidence
sha256sum -c artifacts/evidence/checksums/SHA256SUMS
```

Missing/malformed reports, zero tests, mandatory skips, secret findings,
unchecksummed files, or a commit mismatch are release blockers. Preserve the
failed evidence before rerunning; repeated retries are not a flakiness fix.

## External blocker

Confirm the registry state and required protected environment in
[`external-integrations.md`](external-integrations.md). Never bypass licensing,
use a customer environment, or substitute a stub for an unavailable service.
