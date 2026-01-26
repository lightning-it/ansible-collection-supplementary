# kea_validate

Validate Kea Podman deployment health and configuration.

## Requirements

None.

## Role Variables

See `roles/kea_validate/defaults/main.yml` and `roles/kea_deploy/defaults/main.yml`.

Key variables:
- `kea_validate_mode`
- `kea_validate_check_config`
- `kea_validate_check_http`

## Example Playbook

```yaml
- name: Validate Kea
  hosts: dns
  gather_facts: true
  roles:
    - role: kea_validate
  tags:
    - kea
```
