# MLX-90 synthetic fixture transition policy

This file documents the temporary, centrally managed classification used to
remove pre-existing credential-shaped test and example values from
`lightning-it/ansible-collection-supplementary` without transmitting those
values to external reviewers.

The canonical policy is owned by `lightning-it/shared-assets-lit` and is
delivered only through `scripts/sync-enterprise-collection-assets.py`. The
synchronizer validates the manifest with the live `lit-push-ready` schema and
fails closed unless every path, UTF-8 line, and one-based line position still
matches the unchanged Producer target. The manifest permits only `examples/`,
`molecule/`, and `tests/` fixture paths and cannot authorize `.npmrc`, secret
paths, control characters, changed content, moved lines, or newly introduced
values.

Lowercase hex is an auditable, reversible representation of the exact existing
UTF-8 fixture line. It prevents the classification file itself from duplicating
credential-shaped plaintext and is not a scanner exclusion. No gitleaks,
detect-secrets, workflow, permission, or scanner configuration is weakened.
The history-free review engine masks only an exact documented path/content/
position match; all other material remains subject to the normal full-workspace
and diff scans.

This policy is transitional. After the separately reviewed Producer cleanup
removes the classified fixture strings, Shared Assets must remove both the
manifest and this document through the same guarded synchronization path. The
sync PR, cleanup PR, and retirement PR each remain subject to their protected
current-head gates. Real keys, tokens, credentials, customer values, or private
source history are never eligible for this mechanism.
