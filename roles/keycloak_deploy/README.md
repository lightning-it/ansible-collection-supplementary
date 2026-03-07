# keycloak_deploy

Deploy Keycloak as a dedicated Podman pod and (optionally) deploy PostgreSQL via
`postgres_deploy`.

## Requirements

None.

## Variables

See `roles/keycloak_deploy/defaults/main.yml`.

Key variables:
- `keycloak_deploy_image`
- `keycloak_deploy_pod_manifest_path`
- `keycloak_deploy_host_data_dir`
- `keycloak_deploy_port`
- `keycloak_deploy_host_ip`
- `keycloak_deploy_manage_postgres`
- `keycloak_deploy_postgres_image`
- `keycloak_deploy_postgres_pod_name`
- `keycloak_deploy_postgres_pod_manifest_path`
- `keycloak_deploy_db_host`
- `keycloak_deploy_db_port`
- `keycloak_deploy_db_name`
- `keycloak_deploy_db_user`
- `keycloak_deploy_db_password`
- `keycloak_deploy_admin_user`
- `keycloak_deploy_admin_password`
- `keycloak_deploy_generate_secrets`
- `keycloak_deploy_manage_systemd`

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy Keycloak
  hosts: wunderboxes
  become: true
  roles:
    - role: lit.supplementary.keycloak_deploy
      vars:
        keycloak_deploy_manage_postgres: true
        keycloak_deploy_admin_user: admin
        keycloak_deploy_generate_secrets: true
```

## License

GPL-3.0-only

## Author

Lightning IT
