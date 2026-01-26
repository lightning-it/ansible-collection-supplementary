# kea_config

Manage Kea configuration for the Podman deployment.

## Requirements

None.

## Role Variables

See `roles/kea_config/defaults/main.yml` and `roles/kea_deploy/defaults/main.yml`.

Key variables:
- `kea_config_content`
- `kea_deploy_host_config_path`
- `kea_deploy_skip_config`

## Example Playbook

```yaml
- name: Configure Kea
  hosts: dns
  gather_facts: true
  roles:
    - role: kea_config
  tags:
    - kea
```
