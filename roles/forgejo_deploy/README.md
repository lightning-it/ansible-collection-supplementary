# forgejo_deploy

Deploy Forgejo as a dedicated Podman pod and (optionally) deploy PostgreSQL via
`postgres_deploy`.

## Requirements

None.

## Variables

See `roles/forgejo_deploy/defaults/main.yml`.

Key variables:
- `forgejo_deploy_image`
- `forgejo_deploy_pod_manifest_path`
- `forgejo_deploy_host_data_dir`
- `forgejo_deploy_port`
- `forgejo_deploy_host_ip`
- `forgejo_deploy_manage_postgres`
- `forgejo_deploy_postgres_image`
- `forgejo_deploy_postgres_pod_name`
- `forgejo_deploy_postgres_pod_manifest_path`
- `forgejo_deploy_db_host`
- `forgejo_deploy_db_port`
- `forgejo_deploy_db_type`
- `forgejo_deploy_db_name`
- `forgejo_deploy_db_user`
- `forgejo_deploy_db_password`
- `forgejo_deploy_admin_user`
- `forgejo_deploy_admin_password`
- `forgejo_deploy_root_url_effective`
- `forgejo_deploy_generate_secrets`
- `forgejo_deploy_manage_systemd`

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy Forgejo
  hosts: wunderboxes
  become: true
  roles:
    - role: lit.supplementary.forgejo_deploy
      vars:
        forgejo_deploy_manage_postgres: true
        forgejo_deploy_admin_user: admin
        forgejo_deploy_generate_secrets: true
```

## License

GPL-3.0-only

## Author

Lightning IT
