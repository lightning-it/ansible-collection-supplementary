# vault_validate

Validate Vault runtime and SELinux state without changing config.

## Requirements

None.

## Variables

See `roles/vault_deploy/defaults/main.yml`.

Key variables:
- `vault_deploy_validate_mode`: `fail` (default) or `report`.

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

GPL-3.0-only

## Author

Lightning IT
