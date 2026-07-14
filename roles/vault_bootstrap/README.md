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
- `vault_bootstrap_require_controller_escrow` (bool): enable the strict controller-authoritative escrow branch
  (default false, preserving the legacy workflow for other environments).
- `vault_bootstrap_controller_escrow_root_path`: normalized absolute approved controller directory, such as the
  inventory project's protected `.secrets` directory; it must already exist with mode 0700 and controller ownership.
- `vault_bootstrap_controller_init_file_path`: normalized absolute controller path for the authoritative immutable
  encrypted init document; it must be a direct child of the approved escrow root.
- `vault_bootstrap_ansible_vault_password_file`: controller password file; defaults to
  `ANSIBLE_VAULT_PASSWORD_FILE` and is preferred over copying a plaintext password.
- `vault_bootstrap_ansible_vault_password`: compatibility fallback mapped from `vault_ansible_vault_pw`.
- `vault_bootstrap_ca_cert_path`: trusted CA bundle on `vault_bootstrap_api_delegate_to` for HTTPS API checks.
- `vault_bootstrap_cli_api_url` and `vault_bootstrap_cli_ca_cert_path`: the verified in-container API URL and CA
  bundle used by `vault operator init`.

New init documents persist the canonical `vault_init` key. Reads remain compatible with the interim
`vault_bootstrap_vault_init` and `vault_ops_vault_init` keys.

Initialization never disables TLS verification. The in-container CLI receives `VAULT_CACERT`, and follow-on unseal
requests use the protected HTTPS request-body flow from `vault_ops`.

Strict controller escrow rejects the plaintext password compatibility fallback and requires the role password-file
path to be the secure identity already loaded through `ANSIBLE_VAULT_PASSWORD_FILE`. It fails closed when an
uninitialized Vault has an existing controller escrow or an initialized Vault lacks one. Existing ciphertext is
decrypted only through Ansible's in-process loader. New material is passed directly to
`lit.foundational.ansible_vault_document`; only its immutable ciphertext is copied to the target secondary path, and
an existing target copy must match exactly or the role refuses to overwrite it.

Before `vault operator init`, strict mode creates an isolated probe below the approved escrow root and performs a
real `lit.foundational.ansible_vault_document` encrypt/decrypt validation with the already-loaded controller Vault
identity. The harmless probe is always removed. Check mode is intentionally not used because it does not exercise
encryption for an absent path.

Strict mode also requires `vault_bootstrap_auto_init: false`. An uninitialized Vault is changed only when
`vault_bootstrap_init_requested: true` is explicitly supplied. Persisted and newly generated init payloads must report
the configured share count and threshold exactly, contain exactly that many unique nonempty base64 unseal keys, and
contain a nonempty root token.

## Dependencies

`lit.foundational` 1.30.0 or newer for `ansible_vault_document`.

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
