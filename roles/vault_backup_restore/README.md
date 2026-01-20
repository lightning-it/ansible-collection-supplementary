# vault_backup_restore

Backup and restore Vault storage on disk.

## Requirements

None.

## Role Variables

See `roles/vault_deploy/defaults/main.yml`.

Key variables:
- `vault_backup_action`: `backup`, `restore`, or `none`.
- `vault_backup_dir`
- `vault_backup_retention_keep_last`
- `vault_restore_source`
- `vault_restore_confirm` (must be `YES_RESTORE`)

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
