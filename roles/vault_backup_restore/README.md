# vault_backup_restore

Backup and restore Vault storage on disk.

## Requirements

None.

## Variables

See `roles/vault_backup_restore/defaults/main.yml`.

Key variables:

- `vault_backup_restore_action`: `backup`, `restore`, or `none`.
- `vault_backup_restore_dir`
- `vault_backup_restore_retention_keep_last`
- `vault_backup_restore_source`
- `vault_backup_restore_confirm` (must be `YES_RESTORE`)
- `vault_backup_restore_pod_manifest_path`: resolves the same actual `podman-kube@` unit used by deploy.

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

MIT

## Author

Lightning IT
