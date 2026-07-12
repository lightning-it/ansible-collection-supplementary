# vault_ops

Day-2 operational actions for Vault (restart, status, upgrade, unseal).

## Requirements

None.

## Variables

See `roles/vault_ops/defaults/main.yml` and `roles/vault_deploy/defaults/main.yml`.

Key variables:

- `vault_ops_action`: `restart`, `status`, `upgrade`, `unseal`, or `none`.
- `vault_ops_target_image`: image to use for upgrade.
- `vault_ops_init`, `vault_ops_unseal_keys`, and `vault_ops_token`: explicit bootstrap handoff inputs.
- `vault_ops_pod_manifest_path`: used with `systemd-escape` to resolve the actual `podman-kube@` unit.
- `vault_ops_systemd_unit_name`: optional explicit unit override.
- `vault_ops_api_ca_cert_path`: optional trusted CA bundle on `vault_ops_api_delegate_to` for status and unseal API
  calls.
- `vault_ops_target_ca_cert_path`: optional trusted CA bundle on the managed host for post-operation validation.

Encrypted init documents use the canonical `vault_init` key; the two interim role-prefixed keys remain readable.
Unseal keys are never passed in process arguments: the role requires zero partial progress, selects exactly Vault's
reported threshold count, and submits each share in a `no_log` HTTPS request body with certificate validation.

## Dependencies

None.

## Example Playbook

```yaml
- name: Restart Vault
  hosts: vault_hosts
  gather_facts: true
  roles:
    - role: vault_ops
  tags:
    - ops
```

## License

MIT

## Author

Lightning IT
