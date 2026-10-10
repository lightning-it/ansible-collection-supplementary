# vault_pki_leaf_role

Reconcile one explicitly supplied leaf role on an existing Vault PKI mount. Issuers are neither created nor rotated. Every declared field is checked against independent API readback.

## Requirements

An existing issuer/mount, verified TLS and narrowly authorized temporary administration. The caller revokes temporary authorization in its enclosing `always` block.

## Variables

Supply `vault_pki_leaf_role_api_url`, `vault_pki_leaf_role_ca_path`, `vault_pki_leaf_role_admin_token`, mount, role name and exact definition. The definition must restrict domains and exclude arbitrary names, subdomains, glob domains, IP SANs and localhost. Set `vault_pki_leaf_role_allow_change` explicitly to permit a delta. Check mode performs only safe reads and reports drift without POST or a nonexistent post-write readback.

## Dependencies

No dependent role. Existing issuer and authorization provisioning belong to the caller.

## Example Playbook

```yaml
- hosts: localhost
  roles:
    - role: lit.supplementary.vault_pki_leaf_role
      vault_pki_leaf_role_api_url: https://vault.example.com
      vault_pki_leaf_role_ca_path: /run/controller/vault-ca.pem
      vault_pki_leaf_role_admin_token: "{{ temporary_leaf_role_token }}"
      vault_pki_leaf_role_mount: pki
      vault_pki_leaf_role_name: server
      vault_pki_leaf_role_allow_change: true
      vault_pki_leaf_role_definition:
        issuer_ref: existing
        allowed_domains: [server.example.com]
        allow_any_name: false
        allow_subdomains: false
        allow_glob_domains: false
        allow_ip_sans: false
        allow_localhost: false
```

## License

MIT, as declared by the collection.

## Author

Lightning IT
