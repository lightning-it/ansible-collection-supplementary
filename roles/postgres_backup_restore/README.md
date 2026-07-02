# postgres_backup_restore

Back up and restore PostgreSQL databases with `pg_dump`, `pg_restore`, and
`psql`.

The role is dry-run by default. Set `postgres_backup_restore_execute=true` to
run database commands.

Key variables:

- `postgres_backup_restore_action`: `none`, `backup`, or `restore`
- `postgres_backup_restore_format`: `custom` or `plain`
- `postgres_backup_restore_db_host`
- `postgres_backup_restore_db_port`
- `postgres_backup_restore_db_name`
- `postgres_backup_restore_db_user`
- `postgres_backup_restore_db_password`
- `postgres_backup_restore_file`
- `postgres_backup_restore_restore_source`
- `postgres_backup_restore_restore_confirm`: must be `YES_RESTORE` for restore
