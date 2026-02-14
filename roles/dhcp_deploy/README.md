# dhcp_deploy

Deploy ISC DHCP (dhcpd) on the host using RPMs and systemd (RHEL default repos).

## Requirements

None.

## Variables

See `roles/dhcp_deploy/defaults/main.yml`.

Key variables:
- `dhcp_deploy_service_name`
- `dhcp_deploy_host_config_dir`
- `dhcp_deploy_host_config_path`
- `dhcp_deploy_host_data_dir`
- `dhcp_deploy_manage_systemd`
- `dhcp_deploy_manage_service`
- `dhcp_deploy_manage_config`

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy DHCP
  hosts: dns
  gather_facts: true
  roles:
    - role: dhcp_deploy
  tags:
    - dhcp
```

## License

GPL-3.0-only

## Author

Lightning IT
