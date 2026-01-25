# minio_ops

Day-2 operational actions for MinIO (restart, status, upgrade).

## Requirements

None.

## Role Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_ops_action`: `restart`, `status`, `upgrade`, or `none`.
- `minio_ops_target_image`: image to use for upgrade.

## Example Playbook

```yaml
- name: Restart MinIO
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: minio_ops
  tags:
    - ops
```
