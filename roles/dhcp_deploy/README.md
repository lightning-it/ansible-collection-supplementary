# dhcp_deploy

Deploy DHCP as a rootful Podman kube-play pod.

This role is the supported DHCP deployment path. It deploys DHCP through
rootful Podman kube-play and does not install DHCP packages or manage a native
`dhcpd` service directly. DHCP broadcast traffic and lease-state correctness
must be validated on the target network before production use.

## Requirements

- Rootful Podman.
- A pinned DHCP container image provided through `dhcp_deploy_image`.
- Host networking or a validated equivalent L2/macvlan design.
- UDP 67/68 allowed on the serving interface.
- A persistent host lease path outside `/tmp`.
- No active host-native DHCP service.

## Production gate

Runtime deployment fails closed until all production evidence is explicit:

```yaml
dhcp_deploy_production_ready: true
dhcp_deploy_production_evidence:
  rhel_first_validated: true
  ubuntu_target_validated: true
  l2_broadcast_validated: true
  lease_persistence_validated: true
  reboot_recovery_validated: true
  renewal_validated: true
  backup_failover_validated: true
  no_rogue_dhcp_validated: true
dhcp_deploy_production_evidence_reference: "change/validation record URL or ID"
```

The role also checks rootful Podman, interface presence/link state, UDP/67
conflicts, inactive native DHCP services, rendered config syntax via the DHCP
container image, persistent lease state, and a running container after deployment.

Set `dhcp_deploy_skip_runtime=true` only for render-only tests; it bypasses
runtime production gates but still renders the kube-play manifest and config.

## Variables

See `roles/dhcp_deploy/defaults/main.yml`.

Key variables:
- `dhcp_deploy_image`
- `dhcp_deploy_pod_manifest_path`
- `dhcp_deploy_host_config_path`
- `dhcp_deploy_host_data_dir`
- `dhcp_deploy_config`
- `dhcp_deploy_interfaces`
- `dhcp_deploy_use_host_network`
- `dhcp_deploy_required_capabilities`
- `dhcp_deploy_manage_systemd`
- `dhcp_deploy_production_ready`
- `dhcp_deploy_production_evidence`
- `dhcp_deploy_production_evidence_reference`

## Dependencies

Runtime kube-play actions use `lit.foundational.kubeplay`.

## Example Playbook

```yaml
- name: Deploy containerized DHCP
  hosts: dhcp
  become: true
  gather_facts: true
  roles:
    - role: lit.supplementary.dhcp_deploy
      vars:
        dhcp_deploy_image: registry.example.com/infra/dhcpd:4.4
        dhcp_deploy_interfaces:
          - ens34
        dhcp_deploy_production_ready: true
        dhcp_deploy_production_evidence_reference: CHG-12345
        dhcp_deploy_production_evidence:
          rhel_first_validated: true
          ubuntu_target_validated: true
          l2_broadcast_validated: true
          lease_persistence_validated: true
          reboot_recovery_validated: true
          renewal_validated: true
          backup_failover_validated: true
          no_rogue_dhcp_validated: true
        dhcp_deploy_config: |
          default-lease-time 600;
          max-lease-time 7200;
          authoritative;
```

## License

MIT

## Author

Lightning IT
