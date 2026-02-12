# vault_ops

Day-2 operational actions for Vault (restart, status, upgrade, unseal).

## Requirements

None.

## Variables

See `roles/vault_ops/defaults/main.yml` and `roles/vault_deploy/defaults/main.yml`.

Key variables:
- `vault_ops_action`: `restart`, `status`, `upgrade`, `unseal`, or `none`.
- `vault_ops_target_image`: image to use for upgrade.

## Dependencies

None.

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

## License

GPL-3.0-only

## Author

Lightning IT
