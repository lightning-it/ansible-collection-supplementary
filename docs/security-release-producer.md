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

The historical `lit.supplementary/mlx90-fixture` profile remains explicitly non-releaseable. The separately reviewed
`lit.supplementary/forgejo-manifest-secret-permissions-v1` profile is release eligible only for the fix identified by
`GHSA-vjjf-wc74-gp86`; its packaged offline verifier binds the Forgejo manifest writer to root:root mode 0600 and
`no_log: true`. The first real Security release remains blocked until this producer change, the matching central
final-acceptance allowlist, and the consumer workflow are all promoted to their protected `main` branches. There is no
fallback to labels, mutable claims, the historical fixture, or a weaker dispatch.

The producer evidence adapter is restricted to an exact `push` on `refs/heads/main`. It delegates Heavy and
Application Acceptance to the SHA-pinned reusable workflow in `lightning-it/modulix-validation`, using the producer's
protected runtime environment. The reusable jobs execute as part of the producer workflow run and publish their
exact-SHA evidence into that same run. No pull request, `develop` push, or manual dispatch can enter this path, and the
delegation neither inherits repository secrets nor mints an App token.

The producer aggregates those same-run artifacts as `collection-evidence-<sha>`. `Collection / Release Security`
directly depends on that aggregation before it may create `collection-release-evidence-<sha>` in the protected release
environment. The final `Collection / Release Validation` check verifies the exact protected-main SHA, workflow-run
identity, signatures, attestations, eligible gate receipts, and long-term archive digest. `collection-publish.yml`
continues to stop unless that exact named check succeeds and that exact artifact exists; it does not synthesize or
weaken the prerequisite. The release App's later transition and consumer dispatch remain separate, post-publication
operations.

Revocation is fail-closed: metadata with `revoked: true` cannot generate approved evidence, and consumers/finalizers
must additionally reject a release carrying a matching revocation asset. Published evidence and release assets are
never overwritten; a replacement requires a new reviewed release.
