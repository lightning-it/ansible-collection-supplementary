# minio_bootstrap

Bootstrap MinIO buckets using the `mc` client.

## Requirements

- Default: `podman` available on the target host (the role runs `mc` via a container image).
- Alternative: override `minio_deploy_mc_path` to a local `mc` binary.
- `minio_deploy` available for endpoint/credential resolution.

## Role Variables

See `lit.supplementary.minio_deploy` defaults for shared MinIO variables.

Key variables:
- `minio_bootstrap_skip`
- `minio_bootstrap_buckets`
- `minio_deploy_mc_path`
- `minio_deploy_mc_alias`
- `minio_deploy_mc_insecure`
- `minio_bootstrap_tfstate_bucket` (fallback when Vault secret has no bucket field)
- `minio_bootstrap_tfstate_vault_kv_mount`
- `minio_bootstrap_tfstate_vault_path`

Terraform state migration:
- Reads tfstate backend credentials from Vault KV2 (`bucket`, `access_key`, `secret_key`, optional `endpoint`).
- Publishes backend facts (`tfstate_backend_ready`, `tfstate_s3_endpoint`, `tfstate_bucket`, and creds).
- If `tfstate_pending_dirs` is set, it migrates any local tfstate files it finds
  in those directories and removes them only after successful migration.
- Migration tasks are tagged `tfstate` and `tfstate_migrate` so operators can run
  or skip them without changing the playbook.

## Example Playbook

```yaml
- name: Create MinIO buckets
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: minio_bootstrap
  tags:
    - bootstrap
```
