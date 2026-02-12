# coredns_validate

Validate CoreDNS Podman deployment health and configuration.

## Requirements

None.

## Variables

See `roles/coredns_validate/defaults/main.yml` and `roles/coredns_deploy/defaults/main.yml`.

Key variables:
- `coredns_validate_mode`
- `coredns_validate_check_http`

## Dependencies

None.

## Example Playbook

```yaml
- name: Validate CoreDNS
  hosts: dns
  gather_facts: true
  roles:
    - role: coredns_validate
  tags:
    - coredns
```

## License

GPL-3.0-only

## Author

Lightning IT
