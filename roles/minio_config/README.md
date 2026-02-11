# minio_config

Configure MinIO users and policies using the `mc` client.

This role also creates a dedicated tfstate bucket (`vault-bucket`) and generates access/secret keys,
storing them in Vault KV2 for later use by state migrations and Terraform backends.

## Requirements

- Default: `podman` available on the target host (the role runs `mc` via a container image).
- Alternative: override `minio_config_mc_path` to a local `mc` binary.

## Role Variables

See `roles/minio_config/defaults/main.yml`.

Key variables:
- `minio_config_users`
- `minio_config_skip_config`
- `minio_config_mc_path`
- `minio_config_mc_alias`
- `minio_config_mc_insecure`
- `minio_config_manage_vault_bucket`
- `minio_config_vault_bucket_name`
- `minio_config_vault_kv_mount`
- `minio_config_vault_bucket_vault_path`

## Example Playbook

```yaml
- name: Configure MinIO users
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: minio_config
  tags:
    - config
```
