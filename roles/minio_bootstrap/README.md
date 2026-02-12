# minio_bootstrap

Bootstrap MinIO buckets and optionally migrate Terraform state files to S3-compatible storage.

## Requirements

- Target host with Podman available (default `mc` execution path runs a container).
- MinIO API reachable with root credentials.
- Vault credentials when tfstate migration is enabled.

## Variables

See `roles/minio_bootstrap/defaults/main.yml`.

Key variables:
- `minio_bootstrap_skip`
- `minio_bootstrap_buckets`
- `minio_bootstrap_mc_path`
- `minio_bootstrap_mc_alias`
- `minio_bootstrap_mc_insecure`
- `minio_bootstrap_tfstate_auto_detect`
- `minio_bootstrap_tfstate_auto_dirs`
- `minio_bootstrap_tfstate_bucket`
- `minio_bootstrap_tfstate_vault_kv_mount`
- `minio_bootstrap_tfstate_vault_path`

## Dependencies

- None declared in metadata.
- This role imports `lit.supplementary.minio_foundational` when bucket management is enabled.

## Example Playbook

```yaml
- name: Bootstrap MinIO buckets
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: lit.supplementary.minio_bootstrap
```

## License

GPL-3.0-only

## Author

Lightning IT
