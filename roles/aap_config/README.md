# aap_config

Manage AAP configuration file content for host-based deployments.

## Requirements

None.

## Variables

See `roles/aap_config/defaults/main.yml` and `roles/aap/defaults/main.yml`.

Key variables:
- `aap_config_manage`
- `aap_config_file_path`
- `aap_config_content`
- `aap_config_values`
- `aap_config_use_shared_admin_passwords`
- `aap_config_restart_on_change`

Default behavior:
- `aap_config_enabled` is independent from `aap_deploy_enabled` and defaults to `aap_enabled`.
- `aap_config_values` defaults to `automationhub_admin_password` sourced from shared AAP password resolution.
- Shared resolution can be disabled with `aap_config_use_shared_admin_passwords=false`.
- Shared password source of truth is controlled in role `aap` via `aap_admin_passwords_source_of_truth`.
- When shared resolution is disabled, provide `aap_config_content` or `aap_config_values` explicitly.

## Dependencies

None.

## Example Playbook

```yaml
- name: Configure AAP
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_config
      vars:
        aap_config_values:
          automationhub_admin_password: changeme
```

## License

GPL-3.0-only

## Author

Lightning IT
