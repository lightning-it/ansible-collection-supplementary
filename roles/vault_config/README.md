# vault_config

Configure HashiCorp Vault (policies, PKI, AppRoles, secrets). This role is
platform-agnostic and assumes Vault is already reachable.

## Requirements

None.

## Role Variables

Required for configuration:
- `vault_config_url`
- `vault_config_terraform_source`

Token handling:
- `vault_config_token` (required)

If `vault_config_token` is not set and `vault_config_init.root_token` is provided,
the role will set `vault_config_token` from that init payload. When `vault_token`
is provided, it is mapped into `vault_config_token` for this role.

See `roles/vault_config/defaults/main.yml` for shared variables.

Terraform state migration:
- Terragrunt writes local state on the controller under `vault_config_terraform_state_dir_local`
  (default `/tmp/vault/bootstrap`) and the tfstate files are copied to
  `/srv/vault/bootstrap` on the target.
- If MinIO tfstate backend facts are available, the role migrates local state to S3
  and removes the local files; otherwise it appends the controller-local state
  directory to `tfstate_pending_dirs` for later migration by `minio_bootstrap`.
- Migration tasks are tagged `tfstate` and `tfstate_migrate` so operators can run
  or skip them without changing the playbook.

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
