# postgres_deploy

Deploy PostgreSQL as a dedicated Podman pod on RHEL hosts.

## Requirements

None.

## Variables

See `roles/postgres_deploy/defaults/main.yml`.

Key variables:
- `postgres_deploy_image`
- `postgres_deploy_pod_manifest_path`
- `postgres_deploy_host_data_dir`
- `postgres_deploy_port`
- `postgres_deploy_host_ip`
- `postgres_deploy_db_name`
- `postgres_deploy_db_user`
- `postgres_deploy_db_password`
- `postgres_deploy_generate_password`
- `postgres_deploy_manage_systemd`
- `postgres_deploy_skip_runtime`

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy PostgreSQL
  hosts: db_hosts
  become: true
  roles:
    - role: lit.supplementary.postgres_deploy
      vars:
        postgres_deploy_db_name: semaphore
        postgres_deploy_db_user: semaphore
```

## License

GPL-3.0-only

## Author

Lightning IT
