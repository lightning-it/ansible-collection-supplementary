# Vault-issued service certificate

Issues only the declared DNS server identity from an explicitly supplied Vault
issuer and issuing AppRole. Certificate and private-key custody uses Vault KV v2
with version-bound CAS and independent readback. Existing certificates are reused
unless their remaining validity is less than seven days.

The caller provides certificate-validated Vault transport, the KV token and issuing
identity in memory. Private data is protected by `no_log`. Only the service's required
private-key file is materialized on the target, with explicitly restricted ownership
and permissions. No self-signed or external-custody issuance path exists in this role.

The caller creates the destination directory and service key group before inclusion,
and restarts the consuming service only when `vault_pki_certificate_changed` is true.
