# minio_ops

Execute Day-2 MinIO operations (`restart`, `status`, `upgrade`).

## Requirements

- MinIO must already be deployed and reachable.
- `minio_ops_target_image` is required when `minio_ops_action=upgrade`.

## Variables

See `roles/minio_ops/defaults/main.yml`.

Key variables:
- `minio_ops_action`
- `minio_ops_target_image`
- `minio_ops_manage_systemd`
- `minio_ops_systemd_unit_name`
- `minio_ops_pod_name`
- `minio_ops_health_url_effective`
- `minio_ops_validate_certs`

## Dependencies

- None declared in metadata.
- This role may include:
  - `lit.foundational.kubeplay` for non-systemd restart.
  - `lit.supplementary.minio_validate` after restart.
  - `lit.supplementary.minio_deploy` for upgrade rollout.

## Example Playbook

```yaml
- name: Restart MinIO
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: lit.supplementary.minio_ops
  vars:
    minio_ops_action: restart
```

## License

GPL-3.0-only

## Author

Lightning IT
