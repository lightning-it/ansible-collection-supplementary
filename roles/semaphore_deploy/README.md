# semaphore_deploy

Deploy Semaphore UI as a dedicated Podman pod and (optionally) deploy PostgreSQL via `postgres_deploy`.

## Requirements

None.

## Variables

See `roles/semaphore_deploy/defaults/main.yml`.

Key variables:
- `semaphore_deploy_image`
- `semaphore_deploy_pod_manifest_path`
- `semaphore_deploy_host_data_dir`
- `semaphore_deploy_port`
- `semaphore_deploy_host_ip`
- `semaphore_deploy_manage_postgres`
- `semaphore_deploy_postgres_image`
- `semaphore_deploy_postgres_pod_name`
- `semaphore_deploy_postgres_pod_manifest_path`
- `semaphore_deploy_db_host`
- `semaphore_deploy_db_port`
- `semaphore_deploy_db_name`
- `semaphore_deploy_db_user`
- `semaphore_deploy_db_password`
- `semaphore_deploy_admin_login`
- `semaphore_deploy_generate_secrets`
- `semaphore_deploy_manage_systemd`

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy Semaphore
  hosts: wunderboxes
  become: true
  roles:
    - role: lit.supplementary.semaphore_deploy
      vars:
        semaphore_deploy_manage_postgres: true
        semaphore_deploy_admin_login: admin
        semaphore_deploy_generate_secrets: true
```

## License

GPL-3.0-only

## Author

Lightning IT
