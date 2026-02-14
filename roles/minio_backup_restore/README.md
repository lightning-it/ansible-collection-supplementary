# minio_backup_restore

Perform MinIO data backup and restore operations on host storage.

## Requirements

- Target host with access to MinIO data directories.
- Podman and/or systemd runtime available depending on deployment mode.

## Variables

See `roles/minio_backup_restore/defaults/main.yml`.

Key variables:
- `minio_backup_restore_action` (`none`, `backup`, `restore`)
- `minio_backup_restore_backup_dir`
- `minio_backup_restore_retention_keep_last`
- `minio_backup_restore_restore_source`
- `minio_backup_restore_restore_confirm` (`YES_RESTORE` required for restore)
- `minio_backup_restore_stop_service`
- `minio_backup_restore_validate_after_restore`

## Dependencies

- None declared in metadata.
- This role may call `lit.foundational.kubeplay` (non-systemd restart path).
- This role may include `lit.supplementary.minio_validate` after restore.

## Example Playbook

```yaml
- name: Backup MinIO data
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: lit.supplementary.minio_backup_restore
```

## License

GPL-3.0-only

## Author

Lightning IT
