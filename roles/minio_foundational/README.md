# minio_foundational

Shared helper tasks for MinIO endpoint and credential normalization.

## Requirements

None.

## Role Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_deploy_api_scheme`
- `minio_deploy_host_ip`
- `minio_deploy_port`
- `minio_deploy_console_port`
- `minio_deploy_root_user`
- `minio_deploy_root_password`

## Example Usage

```yaml
- name: Resolve MinIO endpoints
  ansible.builtin.include_role:
    name: lit.supplementary.minio_foundational
```
