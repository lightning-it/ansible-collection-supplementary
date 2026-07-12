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

Encrypted init documents use the canonical `vault_init` key; the two interim role-prefixed keys remain readable.

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
