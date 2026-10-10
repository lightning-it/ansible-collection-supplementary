# vault_pki_certificate

Issue the declared DNS server identity from a specific existing Vault PKI issuer and role. Keep certificate/private-key custody in KV v2 with version-bound CAS and independent readback. Existing custody must match schema, subject and issue path; renew when less than seven days remain.

## Requirements

A prepared PKI issuer/leaf role, dedicated issuing AppRole, KV token, verified TLS and existing target directory/key group. Controller dependencies include `community.crypto`. Supply all authorization in memory; sensitive tasks use `no_log`.

## Variables

The role's `defaults/main.yml` lists the API URL/CA path, KV path/token, issuing identity, issue path, DNS common name and TTL. Set target certificate/key paths and restricted key ownership/mode explicitly. The role sets `vault_pki_certificate_changed`; restart the consumer when true. Check mode reads existing custody and predicts issuance without authentication, issuance or KV writes. An absent/expiring preview does not materialize an unavailable key.

## Dependencies

No dependent role. The caller prepares the service, destination directory, issuer and credentials.

## Example Playbook

```yaml
- hosts: application
  roles:
    - role: lit.supplementary.vault_pki_certificate
      vault_pki_certificate_api_url: https://vault.example.com
      vault_pki_certificate_ca_path: /run/controller/vault-ca.pem
      vault_pki_certificate_kv_token: "{{ controller_kv_token }}"
      vault_pki_certificate_kv_path: service-secrets/data/server/certificate
      vault_pki_certificate_issuing_identity: "{{ server_issuing_identity }}"
      vault_pki_certificate_issue_path: pki/issuer/existing/issue/server
      vault_pki_certificate_common_name: server.example.com
      vault_pki_certificate_cert_path: /etc/service/tls/server.pem
      vault_pki_certificate_key_path: /etc/service/tls/server.key
```

## License

MIT, as declared by the collection.

## Author

Lightning IT

The controller requires cryptography >= 40. The exact issuer PEM endpoint derived from the declared issue path is independently read through verified Vault HTTPS, including in check mode. Existing and final custody must pass a direct certificate signature check against that issuer before use. The materialized chain uses that independently fetched issuer, not the untrusted KV chain. Its API path must be readable by the controller. No issuer key or service secret is logged.
