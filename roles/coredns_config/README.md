# coredns_config

Manage CoreDNS Corefile configuration for the Podman deployment.

## Requirements

None.

## Variables

See `roles/coredns_config/defaults/main.yml` and `roles/coredns_deploy/defaults/main.yml`.

Key variables:
- `coredns_config_corefile`
- `coredns_deploy_host_corefile_path`
- `coredns_deploy_skip_config`

## Dependencies

None.

## Example Playbook

```yaml
- name: Configure CoreDNS
  hosts: dns
  gather_facts: true
  roles:
    - role: coredns_config
  tags:
    - coredns
```

## License

GPL-3.0-only

## Author

Lightning IT
