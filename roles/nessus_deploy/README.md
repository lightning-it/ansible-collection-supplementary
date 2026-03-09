# nessus_deploy

Deploy Nessus as a Podman pod.

## Requirements

None.

## Variables

See `roles/nessus_deploy/defaults/main.yml`.

Key variables:
- `nessus_deploy_image`
- `nessus_deploy_pod_manifest_path`
- `nessus_deploy_host_data_dir`
- `nessus_deploy_port`
- `nessus_deploy_host_ip`
- `nessus_deploy_admin_user`
- `nessus_deploy_admin_password`
- `nessus_deploy_activation_code`
- `nessus_deploy_generate_admin_password`
- `nessus_deploy_manage_systemd`

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy Nessus
  hosts: wunderboxes
  become: true
  roles:
    - role: lit.supplementary.nessus_deploy
      vars:
        nessus_deploy_admin_user: admin
        nessus_deploy_generate_admin_password: true
```

## License

GPL-3.0-only

## Author

Lightning IT
