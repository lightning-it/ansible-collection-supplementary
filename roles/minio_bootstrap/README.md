# minio_bootstrap

Bootstrap MinIO buckets using the `mc` client.

## Requirements

- `mc` available on the controller or target (based on your connection mode).
- `minio_deploy` available for endpoint/credential resolution.

## Role Variables

See `lit.supplementary.minio_deploy` defaults for shared MinIO variables.

Key variables:
- `minio_deploy_bootstrap_buckets`
- `minio_deploy_mc_path`
- `minio_deploy_mc_alias`
- `minio_deploy_mc_insecure`
- `minio_bootstrap_tfstate_bucket`
- `minio_bootstrap_tfstate_access_key`
- `minio_bootstrap_tfstate_secret_key`
- `minio_bootstrap_tfstate_endpoint`
- `minio_bootstrap_tfstate_region`
- `minio_bootstrap_tfstate_key_prefix`

Terraform state migration:
- When tfstate credentials are provided, the role publishes backend facts
  (`tfstate_backend_ready`, `tfstate_s3_endpoint`, `tfstate_bucket`, and creds).
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
