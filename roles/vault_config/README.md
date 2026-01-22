# vault_config

Configure HashiCorp Vault (policies, PKI, AppRoles, secrets). This role is
platform-agnostic and assumes Vault is already reachable.

## Requirements

None.

## Role Variables

Required for configuration:
- `vault_url`
- `vault_terraform_source`
- `vault_token` (or `vault_root_token` / `root_token` / `VAULT_TOKEN`)

See `roles/vault_deploy/defaults/main.yml` for shared variables.

## Example Playbook
```yaml
- name: Configure Vault
  hosts: vault_hosts
  gather_facts: false
  roles:
    - role: vault_config
  tags:
    - vault
```
