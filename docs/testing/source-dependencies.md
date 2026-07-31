# Shipped Source Dependencies

`meta/source-dependencies.yml` is the authoritative inventory for dependencies
referenced by files that ship in the collection artifact. It covers:

- every literal container image used by shipped role source;
- pinned build bases, shipped manifests, validation/devtool images, and explicit
  locally built image outputs;
- every collection requirement in `galaxy.yml` and the exact licensed AAP
  runtime overlay in `collections/requirements-rh.yml`; and
- the licensed AAP 2.7 bundle that provides
  `ansible.containerized_installer`.

Container defaults retain a human-readable tag, but every reference is bound to
an OCI `sha256` manifest digest. A mutable tag without a digest fails repository
validation. Renovate updates the role default and inventory copies together;
the dependency validator rejects an incomplete or stale update.

`localhost/wunderbox-ldap:3.1-bootstrap` is the sole derived image. It has no
digest until the documented local build runs, so the inventory binds it to its
Containerfile and the immutable 389 Directory Server base instead of pretending
that a remote digest exists.

Run the source check directly:

```console
python scripts/source_dependencies.py
```

Validate an exact built collection candidate as well:

```console
python scripts/source_dependencies.py \
  --candidate dist/candidate/lit-supplementary-1.40.0.tar.gz
```

Candidate validation reads the archive without extracting it, rejects links and
unsafe members, compares every declared dependency-bearing file with the exact
checkout, and verifies that the candidate manifest and AAP overlay match the
inventory. Undeclared image or collection references fail closed.

Release Validation copies the exact inventory from `SOURCE_SHA`, compares it
with the checkout, records its hash and commit in the CycloneDX root component,
and adds all shipped images, collections, and external products to the root
dependency relationship before the high-severity vulnerability scan.

The AAP bundle remains explicitly `blocked-external-license`: untrusted CI has
neither the customer entitlement nor the protected installer artifact. The
source SBOM records the product/version and disposition, but it cannot claim a
bundle-content or image-layer scan. A protected AAP acceptance run must retain
the actual bundle checksum, embedded collection inventory, runtime image
digests, and scanner output when those licensed inputs become available.

Caller-provided runtime overrides are not source dependencies. Production
inventories should use immutable image digests and exact Git revisions; the
source check only proves the defaults contained in the released artifact.

## Quality-impact selection

As required by [MLX-70](https://wiki.cloud.l-it.io/wiki/spaces/LIT/pages/2893119515),
[MLX-10](https://wiki.cloud.l-it.io/wiki/spaces/LIT/pages/2886566105), and
[MLX-40](https://wiki.cloud.l-it.io/wiki/spaces/LIT/pages/2886926524), and tracked
in [#554](https://github.com/lightning-it/ansible-collection-supplementary/issues/554),
an inventory edit is not a blanket Keycloak change. The CI selector compares
the old and new declared dependency entries and classifies the changed entry by
its declared `locations`. A Rsyslog-only digest update therefore cannot select
Keycloak Heavy or Application Acceptance. An unreadable or unclassifiable
inventory fails closed only to the unprivileged Tiny Fast Lane; it never starts
a privileged PR validation.

### Central execution boundary

Supplementary runs only the Fast Lane. `modulix-validation` resolves the exact
protected `develop` SHA nightly, builds that candidate, and runs Heavy before
Application Acceptance in its protected environment. It publishes a compact
evidence artifact bound to that SHA.

`Collection / Fast` is the only required context on `develop`. A PR to `main`
also requires `Collection / Release Evidence`: the collection workflow obtains
the central artifact and accepts it only when its repository, SHA, schema, and
`release_eligible` value match exactly. Missing, expired, malformed, or
mismatched evidence fails closed. This keeps infrastructure validation out of
PR/release execution while preventing promotion without a completed central run.
