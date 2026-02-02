# minio_validate

Validate MinIO runtime and storage state without changing config.

## Requirements

None.

## Role Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_deploy_validate_mode`: `fail` (default) or `report`.
- `minio_deploy_skip_validate`

## Example Playbook

```yaml
- name: Validate MinIO
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: minio_validate
  tags:
    - validate
```
