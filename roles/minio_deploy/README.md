# minio_deploy

Deploy MinIO with Podman and optional systemd management.

## Requirements

- Target host with Podman available.
- `gather_facts: true` (defaults depend on host networking facts).

## Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_deploy_image`
- `minio_deploy_host_data_dir`
- `minio_deploy_port`
- `minio_deploy_console_port`
- `minio_deploy_manage_systemd`
- `minio_deploy_root_user`
- `minio_deploy_root_password`
- `minio_deploy_generate_root_credentials`
- `minio_deploy_store_root_credentials`
- `minio_deploy_vault_address`
- `minio_deploy_vault_kv_mount`
- `minio_deploy_vault_kv_path`

## Dependencies

- None declared in metadata.
- This role imports `lit.supplementary.minio_foundational` internally for credential resolution.

## Example Playbook

```yaml
- name: Deploy MinIO
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: lit.supplementary.minio_deploy
```

## License

GPL-3.0-only

## Author

Lightning IT
