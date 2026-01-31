# dhcp_ops

Operate DHCP host install (restart, reload, status, upgrade via RPMs).

## Requirements

None.

## Role Variables

See `roles/dhcp_ops/defaults/main.yml` and `roles/dhcp_deploy/defaults/main.yml`.

Key variables:
- `dhcp_ops_action`
- `dhcp_ops_package_state`

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
