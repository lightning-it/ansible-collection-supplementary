# vault_validate

Validate Vault runtime and SELinux state without changing config.

## Requirements

None.

## Variables

See `roles/vault_validate/defaults/main.yml`.

Key variables:

- `vault_validate_mode`: `fail` (default) or `report`.
- `vault_validate_strict`: derived from the mode.
- `vault_validate_expected_lifecycle`: expected strict lifecycle state. `ready` (default) requires initialized and
  unsealed; `sealed` requires initialized and sealed; `initialized` accepts either seal state; `uninitialized` and
  `any` support bootstrap and reporting workflows.
- `vault_validate_lifecycle_retries` and `vault_validate_lifecycle_delay`: bound startup and auto-unseal polling.
- `vault_validate_ca_cert_path`: optional trusted CA bundle on the managed host for all Vault HTTPS checks.

TLS certificate validation remains enabled by default.

## Dependencies

None.

## Example Playbook

```yaml
- name: Validate Vault
  hosts: vault_hosts
  gather_facts: true
  roles:
    - role: vault_validate
  tags:
    - validate
```

## License

MIT

## Author

Lightning IT
