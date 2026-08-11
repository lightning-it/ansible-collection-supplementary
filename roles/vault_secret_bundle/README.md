# vault_secret_bundle

Reads an application secret map from HashiCorp Vault KV v2, generates only
missing fields, writes the complete map back to Vault, and exposes it only as
an in-memory Ansible fact. The role never writes a local plaintext fallback.

Each item needs a `name` and may define `length` and password-lookup `chars`.
The returned map is always published as the role-prefixed
`vault_secret_bundle_result` fact. Callers may copy that value to a
service-local fact immediately after the role invocation.

The read/generate/write transaction runs once per play batch. Vault KV v2
check-and-set protects the version observed by that transaction, so another
controller cannot silently overwrite a newly generated bundle. A competing
write fails closed and must be retried from a fresh read.

Set `vault_secret_bundle_generate_missing=false` for read-only operational
workflows such as backup and restore. Missing requested fields then fail closed.
