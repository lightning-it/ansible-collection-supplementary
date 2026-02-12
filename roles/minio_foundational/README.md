# minio_foundational

Shared helper tasks for MinIO credential resolution (Vault read/generate/write).

## Requirements

- Vault variables are required only when Vault-backed credential flow is enabled.

## Variables

This role consumes the canonical MinIO deploy variables from
`roles/minio_deploy/defaults/main.yml`.

Key inputs:
- `minio_deploy_root_user`
- `minio_deploy_root_password`
- `minio_deploy_generate_root_credentials`
- `minio_deploy_store_root_credentials`
- `minio_deploy_vault_address`
- `minio_deploy_vault_kv_mount`
- `minio_deploy_vault_kv_path`
- `minio_deploy_vault_token` or AppRole credentials

## Dependencies

- None declared in metadata.

## Example Playbook

```yaml
- name: Resolve MinIO credentials
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: lit.supplementary.minio_foundational
```

## License

GPL-3.0-only

## Author

Lightning IT
