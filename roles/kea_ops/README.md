# kea_ops

Operate Kea Podman deployment (restart, reload, status, upgrade).

## Requirements

None.

## Role Variables

See `roles/kea_ops/defaults/main.yml` and `roles/kea_deploy/defaults/main.yml`.

Key variables:
- `kea_ops_action`
- `kea_ops_target_image`

## Example Playbook

```yaml
- name: Restart Kea
  hosts: dns
  gather_facts: true
  roles:
    - role: kea_ops
      kea_ops_action: restart
  tags:
    - kea
```
