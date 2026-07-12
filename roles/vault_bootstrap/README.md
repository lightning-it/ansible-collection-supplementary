# vault_bootstrap

Initialize and unseal HashiCorp Vault in a controlled way.

## Requirements

None.

## Variables

See `roles/vault_bootstrap/defaults/main.yml`.

Key variables:

- `vault_bootstrap_init_requested` (bool): explicitly allow initialization.
- `vault_bootstrap_auto_init` (bool): initialize an uninitialized instance automatically.
- `vault_bootstrap_init_payload` (mapping): operator-provided or newly generated init payload.
- `vault_bootstrap_unseal_keys` (list): effective keys handed directly to `vault_ops`.
- `vault_bootstrap_token` (string): effective root token handed to follow-on roles without logging it.
- `vault_bootstrap_write_init_file_on_init` (bool): write encrypted init file on init (default true).
- `vault_bootstrap_ansible_vault_password_file`: controller password file; defaults to
  `ANSIBLE_VAULT_PASSWORD_FILE` and is preferred over copying a plaintext password.
- `vault_bootstrap_ansible_vault_password`: compatibility fallback mapped from `vault_ansible_vault_pw`.

New init documents persist the canonical `vault_init` key. Reads remain compatible with the interim
`vault_bootstrap_vault_init` and `vault_ops_vault_init` keys.

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

MIT

## Author

Lightning IT
