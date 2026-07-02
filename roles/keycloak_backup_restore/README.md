# keycloak_backup_restore

Backup and restore role for Keycloak realm state.

This role intentionally does not run PostgreSQL backup or restore commands.
Database state is maintained separately by `postgres_backup_restore`.

The role is dry-run by default. Set `keycloak_backup_restore_execute=true` to
export a realm through the Keycloak Admin API or restore realm objects with
`partialImport`.

Key variables:

- `keycloak_backup_restore_action`: `none`, `backup`, or `restore`
- `keycloak_backup_restore_realm`
- `keycloak_backup_restore_file`
- `keycloak_backup_restore_admin_user`
- `keycloak_backup_restore_admin_password`
- `keycloak_backup_restore_restore_confirm`: must be `YES_RESTORE` for restore
