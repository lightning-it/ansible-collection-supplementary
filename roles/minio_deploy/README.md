# minio_deploy

Deploy MinIO with Podman and optional systemd management.

## Requirements

None.

## Role Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_root_user`
- `minio_root_password`
- `minio_image`
- `minio_host_data_dir`
- `minio_manage_systemd`
- `minio_skip_runtime`

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
