# keycloak_backup_restore

Backup and restore role for Keycloak database state.

The role is dry-run by default. Set `keycloak_backup_restore_execute=true` to run
the `pg_dump` or `psql` command.
