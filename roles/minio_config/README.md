# minio_config

Configure MinIO users and policies using the `mc` client.

## Requirements

- `mc` available on the controller or target (based on your connection mode).

## Role Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_deploy_config_users`
- `minio_deploy_mc_path`
- `minio_deploy_mc_alias`
- `minio_deploy_mc_insecure`

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
