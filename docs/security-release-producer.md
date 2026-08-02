# MLX-90 producer security release contract

The collection publish workflow treats a release as an MLX-90 security release only when the exact protected-main
release SHA contains `.lit/security-releases/<fixed-version>.json`. A missing file selects the normal asynchronous
transition path and cannot dispatch the zero-touch consumer workflow.

The reviewed metadata file has this exact shape:

```json
{
  "schemaVersion": 1,
  "evidenceId": "LIT-SEC-EXAMPLE",
  "createdAt": "2026-08-02T00:00:00Z",
  "securityIdentifiers": ["LIT-SEC-EXAMPLE"],
  "affectedVersion": "3.1.2",
  "fixedVersion": "3.1.3",
  "consumers": ["lightning-it/container-ee-wunder-ansible-ubi9"],
  "acceptanceProfile": "lit.supplementary/example",
  "validity": {
    "notBefore": "2026-08-02T00:00:00Z",
    "expiresAt": "2026-08-09T00:00:00Z",
    "revoked": false
  }
}
```

Security classification, identifiers, versions, consumer, profile, and validity cannot be supplied as workflow or
dispatch inputs. The generator validates the metadata against `.lit/security-release-profiles.json`, binds it to the
exact source SHA and verified release materials, then creates `security-release-evidence.json` without replacement.
The workflow signs and attests that evidence, stores it as an immutable GitHub Release asset, downloads and verifies
the published copy, and only then dispatches the allowlisted consumer with the evidence URL and its `sha256:` digest.
The consumer derives all trusted claims and the signature-bundle URL from that verified evidence.

## Current fail-closed dependency

The only currently defined profile is `lit.supplementary/mlx90-fixture`; it is deliberately marked
`releaseEligible: false` because v3.1.2/#488 is historical dry-run data, not retrospective release attestation. A real
Security release therefore remains blocked until a separately reviewed, fix-specific acceptance profile is added to
both the producer registry and the central final-acceptance allowlist. The consumer
`.github/workflows/security-release-update.yml` must also be promoted and registered on its protected `main` branch
before the first producer Security release. There is no fallback to labels, mutable claims, or a weaker dispatch.

The current producer `main` additionally leaves the former source-repository `Release Security` and
`Release Validation` jobs as non-executed adapters while `collection-publish.yml` still requires their exact-SHA
`Collection / Release Validation` result and `collection-release-evidence-<sha>` artifact. Publication therefore
continues to stop before this new Security path until the reviewed central evidence adapter restores that prerequisite.
This PR does not remove, synthesize, or weaken the existing gate.

Revocation is fail-closed: metadata with `revoked: true` cannot generate approved evidence, and consumers/finalizers
must additionally reject a release carrying a matching revocation asset. Published evidence and release assets are
never overwritten; a replacement requires a new reviewed release.
