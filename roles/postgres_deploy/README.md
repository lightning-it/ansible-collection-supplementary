# postgres_deploy

Deploy PostgreSQL as a dedicated Podman pod on RHEL hosts.

## Requirements

None.

## Variables

See `roles/postgres_deploy/defaults/main.yml`.

With systemd management enabled, an existing effective Podman kube unit is
preserved, including a distribution-provided template shared by other services.
The role installs its fallback template only when systemd reports `not-found`;
it never replaces an existing local template. Masked, erroneous, or unreadable
unit states stop deployment rather than replacing the administrator's policy.
Only the selected PostgreSQL unit is enabled or restarted. Existing overrides
from older deployments are not automatically removed or migrated.

Key variables:
- `postgres_deploy_image`
- `postgres_deploy_pod_manifest_path`
- `postgres_deploy_host_data_dir`
- `postgres_deploy_port`
- `postgres_deploy_host_ip`
- `postgres_deploy_db_name`
- `postgres_deploy_db_user`
- `postgres_deploy_db_password`
- `postgres_deploy_generate_password`
- `postgres_deploy_manage_systemd`
- `postgres_deploy_skip_runtime`

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy PostgreSQL
  hosts: db_hosts
  become: true
  roles:
    - role: lit.supplementary.postgres_deploy
      vars:
        postgres_deploy_db_name: semaphore
        postgres_deploy_db_user: semaphore
```

## License

MIT

## Author

Lightning IT
