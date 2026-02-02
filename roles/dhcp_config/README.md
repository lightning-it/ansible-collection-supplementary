# dhcp_config

Manage DHCP configuration for the host install.

## Requirements

None.

## Role Variables

See `roles/dhcp_config/defaults/main.yml` and `roles/dhcp_deploy/defaults/main.yml`.

Key variables:
- `dhcp_config_content`
- `dhcp_deploy_host_config_path`
- `dhcp_deploy_skip_config`

## Example Playbook

```yaml
- name: Configure DHCP
  hosts: dns
  gather_facts: true
  roles:
    - role: dhcp_config
  tags:
    - dhcp
```
