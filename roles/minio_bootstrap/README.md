# minio_bootstrap

Bootstrap MinIO buckets using the `mc` client.

## Requirements

- `mc` available on the controller or target (based on your connection mode).

## Role Variables

See `roles/minio_deploy/defaults/main.yml`.

Key variables:
- `minio_deploy_bootstrap_buckets`
- `minio_deploy_mc_path`
- `minio_deploy_mc_alias`
- `minio_deploy_mc_insecure`

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
