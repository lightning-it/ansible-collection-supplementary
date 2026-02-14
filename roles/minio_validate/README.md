# minio_validate

Validate MinIO runtime, storage ownership, and health endpoint state.

## Requirements

- MinIO runtime already deployed.
- `podman` available for container status inspection.

## Variables

See `roles/minio_validate/defaults/main.yml`.

Key variables:
- `minio_validate_skip`
- `minio_validate_mode` (`fail` or `report`)
- `minio_validate_container_name`
- `minio_validate_host_data_dir`
- `minio_validate_expected_uid`
- `minio_validate_expected_gid`
- `minio_validate_expected_mode`
- `minio_validate_health_url_effective`
- `minio_validate_validate_certs`

## Dependencies

- None declared in metadata.

## Example Playbook

```yaml
- name: Validate MinIO
  hosts: minio_hosts
  gather_facts: true
  roles:
    - role: lit.supplementary.minio_validate
```

## License

GPL-3.0-only

## Author

Lightning IT
