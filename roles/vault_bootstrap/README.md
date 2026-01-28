# vault_bootstrap

Initialize and unseal HashiCorp Vault in a controlled way.

## Requirements

None.

## Behavior

- When Vault is uninitialized and bootstrap is enabled (or auto-enabled), the role runs `vault operator init`.
- On that first init run, an encrypted init file is **always** written to disk.
- The init file is encrypted via `ansible-vault` on the controller; this requires `vault_ansible_vault_pw` (mapped to `vault_deploy_ansible_vault_pw`).

On the init run, the role also exposes token facts for downstream roles/playbooks:
- `vault_deploy_root_token` (always captured)
- `vault_admin_token` (only set if not already provided)
- `vault_token` (only set if not already provided)
- `root_token` (only set if not already provided)

## Role Variables

See `roles/vault_deploy/defaults/main.yml`.

Key variables:
- `vault_deploy_bootstrap_init` (bool): allow init (default false).
- `vault_deploy_unseal_keys` (list): provide unseal keys for automated unseal.
- `vault_deploy_bootstrap_auto_init` (bool): auto-enable init for first run (default true).
- `vault_bootstrap_write_init_file_on_init` (bool): write encrypted init file on init (default true).
- `vault_ansible_vault_pw` / `vault_deploy_ansible_vault_pw`: Ansible Vault password used to encrypt init output.

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
