# vault_deploy

Deploy HashiCorp Vault on RHEL (packages, TLS bootstrap, Podman pod, systemd).

## Requirements

None.

## Variables

See `roles/vault_deploy/defaults/main.yml` for shared variables.

`vault_deploy_systemd_unit_name` is an optional override. By default the role resolves the actual
`podman-kube@.service` instance from `vault_deploy_pod_manifest_path` with `systemd-escape` and exposes
`vault_deploy_systemd_unit_name_effective` to follow-on lifecycle roles.

TLS verification is enabled by default. `vault_deploy_api_ca_cert_path` names an optional CA bundle on the API
delegate, `vault_deploy_target_ca_cert_path` names the trusted bundle on the managed host, and
`vault_deploy_container_ca_cert_path` names that bundle inside the Vault container. The temporary self-signed
bootstrap key is generated only on the managed host; its self-signed leaf is pinned locally as `ca.crt` for strict
bootstrap validation and is reconciled without regenerating existing private material.

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
