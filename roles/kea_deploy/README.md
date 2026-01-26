# kea_deploy

Deploy Kea as a Podman container, similar to the Vault deployment pattern.

## Requirements

None.

## Role Variables

See `roles/kea_deploy/defaults/main.yml`.

Key variables:
- `kea_deploy_image`
- `kea_deploy_pod_manifest_path`
- `kea_deploy_host_config_dir`
- `kea_deploy_host_config_path`
- `kea_deploy_host_data_dir`
- `kea_deploy_dhcp4_port`
- `kea_deploy_manage_systemd`
- `kea_deploy_selinux_relabel`
- `kea_deploy_skip_runtime`

## Example Playbook

```yaml
- name: Deploy Kea
  hosts: dns
  gather_facts: true
  roles:
    - role: kea_deploy
  tags:
    - kea
```
