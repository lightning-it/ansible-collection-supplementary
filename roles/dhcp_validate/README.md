# dhcp_validate

Validate DHCP host install health and configuration.

## Requirements

None.

## Variables

See `roles/dhcp_validate/defaults/main.yml` and `roles/dhcp_deploy/defaults/main.yml`.

Key variables:
- `dhcp_validate_mode`
- `dhcp_validate_check_config`
- `dhcp_validate_check_http`

## Dependencies

None.

## Example Playbook

```yaml
- name: Validate DHCP
  hosts: dns
  gather_facts: true
  roles:
    - role: dhcp_validate
  tags:
    - dhcp
```

## License

GPL-3.0-only

## Author

Lightning IT
