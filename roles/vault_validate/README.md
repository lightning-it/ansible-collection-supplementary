# vault_validate

Validate Vault runtime, storage, and SELinux state without changing config.

## Requirements

None.

## Role Variables

See `roles/vault_deploy/defaults/main.yml`.

Key variables:
- `vault_validate_mode`: `fail` (default) or `report`.

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
