# aap_ops

Operate AAP host install (restart, status, upgrade, rotate_password).

## Requirements

None.

## Variables

See `roles/aap_ops/defaults/main.yml` and `roles/aap/defaults/main.yml`.

Key variables:
- `aap_ops_action`
- `aap_ops_package_state`
- `aap_ops_systemd_unit_name`
- `aap_ops_rotate_controller_username`
- `aap_ops_rotate_controller_current_password`
- `aap_ops_rotate_controller_new_password`
- `aap_ops_rotate_generate_password`
- `aap_ops_rotate_source_of_truth` (`inventory` or `vault`)
- `aap_ops_rotate_vault_addr`
- `aap_ops_rotate_vault_kv_mount`
- `aap_ops_rotate_vault_kv_path`

## Dependencies

None.

## Example Playbook

```yaml
- name: Restart AAP
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_ops
      vars:
        aap_ops_action: restart
```

Rotate controller admin password:

```yaml
- name: Rotate AAP controller admin password
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_ops
      vars:
        aap_ops_action: rotate_password
        aap_ops_rotate_controller_username: admin
        aap_ops_rotate_controller_current_password: "{{ vault_aap_controller_password_current }}"
        aap_ops_rotate_controller_new_password: "{{ vault_aap_controller_password_next }}"
```

Rotate controller admin password with Vault-backed credential management:

```yaml
- name: Rotate AAP controller admin password (Vault-backed)
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_ops
      vars:
        aap_ops_action: rotate_password
        aap_ops_rotate_source_of_truth: vault
        aap_ops_rotate_generate_password: true
        aap_ops_rotate_require_vault: true
        aap_ops_rotate_vault_addr: "{{ vault_address }}"
        aap_ops_rotate_vault_kv_mount: "{{ vault_engine_mount_point | default('stage-2c') }}"
        aap_ops_rotate_vault_kv_path: "{{ inventory_hostname }}/aap/controller/admin"
        aap_ops_rotate_vault_token: "{{ vault_token }}"
```

Notes:
- Store current/next passwords in Vaulted vars or another secrets backend.
- If `aap_ops_rotate_generate_password=true`, use `aap_ops_rotate_source_of_truth=vault`
  so generated credentials are persisted.
- Vault flow is supported (read current credential + write rotated credential):
  set `aap_ops_rotate_vault_addr`, `aap_ops_rotate_vault_kv_mount`,
  `aap_ops_rotate_vault_kv_path`, and token/AppRole vars
  (`aap_ops_rotate_vault_token` or `aap_ops_rotate_vault_role_id` + `aap_ops_rotate_vault_secret_id`).
- For Vault source of truth, rotated credentials are written to Vault before controller update.
- After successful rotation, runtime fact `aap_ops_rotated_controller_password` is available for follow-up tasks.

## License

GPL-3.0-only

## Author

Lightning IT
