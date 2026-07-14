# vault_backup_restore

Backup and restore Vault file storage on disk with runtime recovery and transactional restore rollback.

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
- `vault_backup_restore_stop_service`: stops a running Vault for file-storage consistency and restarts only a runtime
  that was running before the operation.
- `vault_backup_restore_unseal_after_start`: invokes the protected `vault_ops` unseal flow whenever maintenance
  restarts a Shamir deployment. It defaults to `true` when auto-unseal is disabled.
- `vault_backup_restore_expected_lifecycle`: lifecycle required by post-restore validation; defaults to `ready`.
- `vault_backup_restore_pod_manifest_path`: resolves the same actual `podman-kube@` unit used by deploy.

The role validates the tar archive layout before stopping Vault. Backup startup runs from an `always` path, so an
archive or retention failure does not strand a previously running Vault. Restore moves the current data directory to
a timestamped rollback path, removes an incomplete extraction on failure, restores the previous directory, and only
restarts Vault when storage is safe. A successful restore keeps the rollback directory for explicit operator cleanup.
An intentionally online file-storage restore is rejected.

After restarting a restored Shamir Vault, the role uses the same TLS-validated, `no_log` unseal contract as
`vault_ops` before enforcing the explicit lifecycle expectation. GNU `tar` is required to validate a remote archive
before maintenance begins.

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
