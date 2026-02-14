# vault_backup_restore

Backup and restore Vault storage on disk.

## Requirements

None.

## Variables

See `roles/vault_deploy/defaults/main.yml`.

Key variables:
- `vault_deploy_backup_action`: `backup`, `restore`, or `none`.
- `vault_deploy_backup_dir`
- `vault_deploy_backup_retention_keep_last`
- `vault_deploy_restore_source`
- `vault_deploy_restore_confirm` (must be `YES_RESTORE`)

## Dependencies

None.

## Example Playbook

```yaml
- name: Backup Vault
  hosts: vault_hosts
  gather_facts: true
  roles:
    - role: vault_backup_restore
  tags:
    - backup
```

## License

GPL-3.0-only

## Author

Lightning IT
