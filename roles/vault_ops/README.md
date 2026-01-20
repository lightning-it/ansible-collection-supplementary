# vault_ops

Day-2 operational actions for Vault (restart, status, upgrade).

## Requirements

None.

## Role Variables

See `roles/vault_deploy/defaults/main.yml`.

Key variables:
- `vault_ops_action`: `restart`, `status`, `upgrade`, or `none`.
- `vault_ops_target_image`: image to use for upgrade.

## Example Playbook
```yaml
- name: Restart Vault
  hosts: vault_hosts
  gather_facts: true
  roles:
    - role: vault_ops
  tags:
    - ops
```
