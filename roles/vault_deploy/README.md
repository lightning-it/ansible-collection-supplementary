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
bootstrap validation and is reconciled without regenerating existing private material. When
`vault_deploy_api_ca_cert_path` is set, the role copies only the public CA certificate to that absolute path on
`vault_deploy_api_delegate_to` and uses the path for all delegated API calls. The delegate path must be writable
without privilege escalation; API tasks always run with `become: false`.

Runtime topology inputs:

- `vault_deploy_image`: OCI image reference. Set `vault_deploy_require_immutable_image: true` to require the exact
  `registry/repository@sha256:<64 lowercase hex>` form used by production deployments.
- `vault_deploy_storage_backend`: `file` (compatibility default) or `raft`.
- `vault_deploy_listener_address`: Vault API listener bind address inside the container.
- `vault_deploy_api_addr`: advertised HTTPS API address.
- `vault_deploy_container_api_url`: certificate-validated client URL used by the Vault CLI inside the container. It
  may intentionally differ from the advertised address for a loopback-only service reached through an SSH tunnel.
- `vault_deploy_cluster_listener_address` and `vault_deploy_cluster_port`: Raft cluster listener and published port.
- `vault_deploy_cluster_addr`: advertised HTTPS cluster address; required for Raft.
- `vault_deploy_raft_node_id`: stable, inventory-owned node ID; required for Raft.
- `vault_deploy_disable_mlock`: renders Vault's `disable_mlock` setting. Production callers can set it to `false`
  together with an appropriate `CAP_IPC_LOCK` runtime policy; the compatibility default remains `true`.

The file backend omits Raft-only HCL and publishes only the API port. Raft renders the integrated-storage node ID,
advertised cluster address, listener cluster address, and cluster host port. Changing an existing service between
storage backends is a data migration and is not performed by this role.

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
