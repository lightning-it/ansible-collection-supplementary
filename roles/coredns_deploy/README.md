# coredns_deploy

Deploy CoreDNS as a Podman container, similar to the Vault deployment pattern.

## Requirements

None.

## Role Variables

See `roles/coredns_deploy/defaults/main.yml`.

Key variables:
- `coredns_deploy_image`
- `coredns_deploy_pod_manifest_path`
- `coredns_deploy_host_config_dir`
- `coredns_deploy_dns_port`
- `coredns_deploy_manage_systemd`
- `coredns_deploy_selinux_relabel`
- `coredns_deploy_skip_runtime`

## Example Playbook

```yaml
- name: Deploy CoreDNS
  hosts: dns
  gather_facts: true
  roles:
    - role: coredns_deploy
  tags:
    - coredns
```
