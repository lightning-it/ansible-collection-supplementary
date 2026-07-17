# vault_config

Configure HashiCorp Vault (policies, PKI, AppRoles, secrets). This role is
platform-agnostic and assumes Vault is already reachable.

## Requirements

None.

## Variables

Required for configuration:

- `vault_config_url`
- `vault_config_terraform_source`

Token handling:

- `vault_config_token` (required effective token)
- `vault_config_vault_token` (preferred day-2 operational token input)

An explicit operational token is preferred over `vault_config_init.root_token`, so a revoked
initial root token in long-lived escrow cannot override valid day-2 credentials. If no operational
token is available, a newly initialized Vault still hands its root token directly from
`vault_bootstrap_init_payload`/`vault_bootstrap_token` into the first configuration run.

API TLS verification is enabled by default. `vault_config_api_ca_cert_path` is the absolute
CA path on `vault_config_api_delegate_to`; it inherits the controller-accessible path prepared by
`vault_deploy`. The role applies it to URI checks and every `community.hashi_vault` request.

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

## Dependencies

None.

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

## License

MIT

## Author

Lightning IT
