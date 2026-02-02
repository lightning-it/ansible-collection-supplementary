# minio_deploy

Deploy MinIO with Podman and optional systemd management.

## Requirements

None.

## Role Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_deploy_root_user`
- `minio_deploy_root_password`
- `minio_deploy_generate_root_credentials`
- `minio_deploy_store_root_credentials`
- `minio_deploy_vault_address`
- `minio_deploy_vault_kv_mount`
- `minio_deploy_vault_kv_path`
- `minio_deploy_image`
- `minio_deploy_host_data_dir`
- `minio_deploy_manage_systemd`
- `minio_deploy_skip_runtime`

If root credentials are missing and `minio_deploy_generate_root_credentials` is true,
the role will generate them and store them in Vault KV2 at
`minio_deploy_vault_kv_mount/minio_deploy_vault_kv_path` (when
`minio_deploy_store_root_credentials` is true).

## Example Playbook

```yaml
- name: Deploy MinIO
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: minio_deploy
  tags:
    - minio
```
