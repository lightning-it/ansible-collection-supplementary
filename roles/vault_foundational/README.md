# vault_foundational

Shared helpers for Vault bootstrap metadata files.

## Requirements

- `ansible-vault` available on the controller when re-encryption is needed.

## Role Variables

Key variables:
- `vault_foundational_init_file_path` (string): override init file path.
- `vault_init_file_path` (string): fallback init file path.
- `vault_ansible_vault_pw` (string): vault password used for re-encrypting raw JSON.

## Example Usage

```yaml
- name: Normalize Vault init file format
  ansible.builtin.include_role:
    name: lit.supplementary.vault_foundational
    tasks_from: normalize_init_file
```
