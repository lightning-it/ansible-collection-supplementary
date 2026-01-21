# vault_bootstrap

Initialize and unseal HashiCorp Vault in a controlled way.

## Requirements

None.

## Role Variables

See `roles/vault_deploy/defaults/main.yml`.

Key variables:
- `vault_bootstrap_init` (bool): allow init (default false).
- `vault_unseal_keys` (list): provide unseal keys for automated unseal.
- `vault_bootstrap_write_init_output` (bool): write init output to disk (default true).

## Example Playbook
```yaml
- name: Bootstrap Vault
  hosts: vault_hosts
  gather_facts: true
  roles:
    - role: vault_bootstrap
  tags:
    - bootstrap
```
