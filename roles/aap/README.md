# aap

Shared AAP context role that centralizes common variables and prechecks.

## Requirements

None.

## Variables

See `roles/aap/defaults/main.yml`.

Key variables:
- `aap_enabled`
- `aap_supported_majors`
- `aap_packages_effective`
- `aap_manage_systemd`
- `aap_systemd_unit_name`

## Dependencies

None.

## Example Playbook

```yaml
- name: Load shared AAP context
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap
```

## License

GPL-3.0-only

## Author

Lightning IT
