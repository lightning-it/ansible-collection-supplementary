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
