# minio_foundational

Shared helper tasks for MinIO endpoint and credential normalization.

## Requirements

None.

## Role Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_api_scheme`
- `minio_host_ip`
- `minio_port`
- `minio_console_port`
- `minio_root_user`
- `minio_root_password`

## Example Usage

```yaml
- name: Resolve MinIO endpoints
  ansible.builtin.include_role:
    name: lit.supplementary.minio_foundational
```
