# vault_config

Configure HashiCorp Vault (policies, PKI, AppRoles, secrets). This role is
platform-agnostic and assumes Vault is already reachable.

## Requirements

None.

## Role Variables

Required for configuration:
- `vault_config_url`
- `vault_config_terraform_source`

Token handling (provide one):
- `vault_config_token` (preferred)
- `vault_admin_token`
- `vault_token`
- `vault_root_token`
- `root_token`
- `VAULT_TOKEN` (environment)

Token resolution order:
`vault_config_token` > `vault_admin_token` > `vault_token` > `vault_config_root_token` > `vault_root_token` > `root_token` > `VAULT_TOKEN`.

See `roles/vault_config/defaults/main.yml` for shared variables.

Terraform state migration:
- Local state is written under `/srv/vault/bootstrap`.
- If MinIO tfstate backend facts are available, the role migrates local state to S3
  and removes the local files; otherwise it appends `/srv/vault/bootstrap` to
  `tfstate_pending_dirs` for later migration by `minio_bootstrap`.

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
