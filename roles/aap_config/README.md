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
- `aap_config_restart_on_change`

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
