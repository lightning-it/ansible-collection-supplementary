# vault_config

Configure HashiCorp Vault (policies, PKI, AppRoles, secrets). This role is
platform-agnostic and assumes Vault is already reachable.

## Requirements

None.

## Role Variables

Required for configuration:
- `vault_deploy_url`
- `vault_deploy_terraform_source`
- `vault_deploy_token` (or `VAULT_TOKEN`)

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
