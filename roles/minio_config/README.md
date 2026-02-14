# minio_config

Configure MinIO users and policies with `mc`, and optionally manage the Vault tfstate bucket identity.

## Requirements

- Target host with Podman available (default `mc` execution path runs a container).
- MinIO API reachable with valid root credentials.
- Vault token and KV path when `minio_config_manage_vault_bucket` is enabled.

## Variables

See `roles/minio_config/defaults/main.yml`.

Key variables:
- `minio_config_skip_config`
- `minio_config_users`
- `minio_config_manage_vault_bucket`
- `minio_config_vault_bucket_name`
- `minio_config_vault_bucket_policy`
- `minio_config_vault_address`
- `minio_config_vault_kv_mount`
- `minio_config_vault_bucket_vault_path`
- `minio_config_mc_path`
- `minio_config_mc_alias`
- `minio_config_mc_insecure`

## Dependencies

- None declared in metadata.
- In practice, `lit.supplementary.minio_deploy` is typically run earlier in the same play.

## Example Playbook

```yaml
- name: Configure MinIO
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: lit.supplementary.minio_config
```

## License

GPL-3.0-only

## Author

Lightning IT
