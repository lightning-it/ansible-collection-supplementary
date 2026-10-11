# vault_connection_credentials

Read existing KV v2 desktop-account documents over verified TLS and AppRole. No credential generation, rotation or migration occurs. Results remain in RAM and sensitive tasks use `no_log`.

## Requirements

Prepared HashiCorp Vault KV v2, a trusted CA file and an existing read-only AppRole. The pinned controller needs `community.hashi_vault`.

## Variables

Declare `vault_connection_credentials_sources` with `vault_path`, `subject`, `purpose`, `username`, `tier`, and unique `destination`. Each source must have exactly one matching username/tier pair with a password of at least 32 characters, schema version 1 and the declared subject/purpose. Authentication supplies `url`, `ca_cert`, `namespace`, `auth_mount_point`, `role_id` and `secret_id`; `vault_connection_credentials_kv_mount` is separate. The output is `vault_connection_credentials_result`.

## Dependencies

No dependent role. Read-only credentials and prepared accounts belong to the caller.

## Example Playbook

```yaml
- hosts: application
  roles:
    - role: lit.supplementary.vault_connection_credentials
      vault_connection_credentials_auth: "{{ controller_vault_auth }}"
      vault_connection_credentials_kv_mount: service-secrets
      vault_connection_credentials_sources:
        - vault_path: desktop/accounts
          subject: desktop.example.com
          purpose: remote-desktop
          username: desktop_user
          tier: user
          destination: desktop_password
```

## License

MIT, as declared by the collection.

## Author

Lightning IT
