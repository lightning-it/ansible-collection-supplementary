# vault_deploy

Deploy HashiCorp Vault on RHEL (packages, TLS bootstrap, Podman pod, systemd).

## Requirements

None.

## Variables

See `roles/vault_deploy/defaults/main.yml` for shared variables.

## Dependencies

None.

## Example Playbook

```yaml
- name: Deploy Vault on RHEL
  hosts: vault_hosts
  gather_facts: true
  roles:
    - role: vault_deploy
  tags:
    - vault
```

## License

GPL-3.0-only

## Author

Lightning IT
