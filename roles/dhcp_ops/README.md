# dhcp_ops

Operate DHCP host install (restart, reload, status, upgrade via RPMs).

## Requirements

None.

## Variables

See `roles/dhcp_ops/defaults/main.yml` and `roles/dhcp_deploy/defaults/main.yml`.

Key variables:
- `dhcp_ops_action`
- `dhcp_ops_package_state`

## Dependencies

None.

## Example Playbook

```yaml
- name: Restart DHCP
  hosts: dns
  gather_facts: true
  roles:
    - role: dhcp_ops
      dhcp_ops_action: restart
  tags:
    - dhcp
```

## License

GPL-3.0-only

## Author

Lightning IT
