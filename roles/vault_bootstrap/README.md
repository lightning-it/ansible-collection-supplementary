# vault_bootstrap

Initialize and unseal HashiCorp Vault in a controlled way.

## Requirements

None.

## Variables

See `roles/vault_deploy/defaults/main.yml`.

Key variables:
- When Vault is uninitialized and bootstrap is enabled (or auto-enabled), the role runs `vault operator init`.
- On the first init run, an encrypted init file is always written to disk.
- The init file encryption uses `vault_ansible_vault_pw` (mapped to `vault_deploy_ansible_vault_pw`).
- `vault_bootstrap_token` is exposed for follow-on roles/playbooks on init runs.
- `vault_deploy_bootstrap_init` (bool): allow init (default false).
- `vault_deploy_unseal_keys` (list): provide unseal keys for automated unseal.
- `vault_deploy_bootstrap_auto_init` (bool): auto-enable init for first run (default true).
- `vault_bootstrap_write_init_file_on_init` (bool): write encrypted init file on init (default true).
- `vault_ansible_vault_pw` / `vault_deploy_ansible_vault_pw`: Ansible Vault password used to encrypt init output.

## Dependencies

None.

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

## License

GPL-3.0-only

## Author

Lightning IT
