# dhcp_kube_deploy

Deploy DHCP as a rootful Podman kube-play pod.

This role is separate from `dhcp_deploy`, which manages a host-native `dhcpd`
service. DHCP broadcast traffic and lease-state correctness must be validated
on the target network before production use.

## Requirements

- Rootful Podman.
- A DHCP container image provided through `dhcp_kube_deploy_image`.
- Host networking or a validated equivalent L2/macvlan design.
- UDP 67/68 allowed on the serving interface.

## Variables

See `roles/dhcp_kube_deploy/defaults/main.yml`.

Key variables:
- `dhcp_kube_deploy_image`
- `dhcp_kube_deploy_pod_manifest_path`
- `dhcp_kube_deploy_host_config_path`
- `dhcp_kube_deploy_host_data_dir`
- `dhcp_kube_deploy_config`
- `dhcp_kube_deploy_interfaces`
- `dhcp_kube_deploy_use_host_network`
- `dhcp_kube_deploy_required_capabilities`
- `dhcp_kube_deploy_manage_systemd`

## Dependencies

Runtime kube-play actions use `lit.foundational.kubeplay`.

## Example Playbook

```yaml
- name: Deploy containerized DHCP
  hosts: dhcp
  become: true
  gather_facts: true
  roles:
    - role: lit.supplementary.dhcp_kube_deploy
      vars:
        dhcp_kube_deploy_image: registry.example.com/infra/dhcpd:4.4
        dhcp_kube_deploy_interfaces:
          - ens34
        dhcp_kube_deploy_config: |
          default-lease-time 600;
          max-lease-time 7200;
          authoritative;
```

## License

MIT

## Author

Lightning IT
