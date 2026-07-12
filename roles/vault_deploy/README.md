# vault_deploy

Deploy HashiCorp Vault on RHEL (packages, TLS bootstrap, Podman pod, systemd).

## Requirements

None.

## Variables

See `roles/vault_deploy/defaults/main.yml` for shared variables.

`vault_deploy_systemd_unit_name` is an optional override. By default the role resolves the actual
`podman-kube@.service` instance from `vault_deploy_pod_manifest_path` with `systemd-escape` and exposes
`vault_deploy_systemd_unit_name_effective` to follow-on lifecycle roles.

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

MIT

## Author

Lightning IT
