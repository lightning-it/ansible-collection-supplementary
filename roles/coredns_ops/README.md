# coredns_ops

Operate CoreDNS Podman deployment (restart, reload, status, upgrade).

## Requirements

None.

## Role Variables

See `roles/coredns_ops/defaults/main.yml` and `roles/coredns_deploy/defaults/main.yml`.

Key variables:
- `coredns_ops_action`
- `coredns_ops_target_image`

## Example Playbook

```yaml
- name: Restart CoreDNS
  hosts: dns
  gather_facts: true
  roles:
    - role: coredns_ops
      coredns_ops_action: restart
  tags:
    - coredns
```
