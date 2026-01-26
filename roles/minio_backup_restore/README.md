# minio_backup_restore

Backup and restore MinIO storage on disk.

## Requirements

None.

## Role Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_deploy_backup_action`
- `minio_deploy_backup_dir`
- `minio_deploy_backup_retention_keep_last`
- `minio_deploy_restore_source`
- `minio_deploy_restore_confirm` (must be `YES_RESTORE`)

## Example Playbook

```yaml
- name: Backup MinIO
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: minio_backup_restore
  tags:
    - backup
```
