# coredns_validate

Validate CoreDNS Podman deployment health and configuration.

## Requirements

None.

## Role Variables

See `roles/coredns_validate/defaults/main.yml` and `roles/coredns_deploy/defaults/main.yml`.

Key variables:
- `coredns_validate_mode`
- `coredns_validate_check_http`

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
