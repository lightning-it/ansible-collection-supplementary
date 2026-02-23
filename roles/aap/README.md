# aap

Shared AAP context role that centralizes common variables and prechecks.

## Requirements

None.

## Variables

See `roles/aap/defaults/main.yml`.

Key variables:
- `aap_enabled`
- `aap_supported_majors`
- `aap_packages_effective`
- `aap_manage_systemd`
- `aap_systemd_unit_name`
- `aap_resolve_admin_passwords`
- `aap_password_active`
- `aap_password_active_slot`
- `aap_password_require_component_inputs`
- `aap_password_disallow_unresolved_references`
- `aap_password_reference_regex`
- `aap_admin_password_input`
- `aap_gateway_admin_password_input`
- `aap_controller_admin_password_input`
- `aap_hub_admin_password_input`
- `aap_eda_admin_password_input`
- `aap_postgresql_admin_password_input`

## Inventory Password Input Contract

This role is inventory-only for secret input.

- The role does not contain backend-specific Vault/1Password logic.
- Inventory values can be:
  - literal password strings
  - lookup-based values (for example HCP Vault/1Password lookups)
  - structured mappings with slots (for example `active`, `next`).
- Active slot switch:
  - `aap_password_active` (alias)
  - `aap_password_active_slot` (canonical)
- `aap_password_active_slot` selects the active key for structured mappings.
- With `aap_password_require_component_inputs=true`, missing per-component inputs fail fast.
- With `aap_password_disallow_unresolved_references=true`, raw path-like strings
  (for example `hc://...`, `op://...`) fail fast.
- The role only consumes resolved effective values and publishes `*_effective` outputs.
- Backend get-or-create behavior must be handled in inventory lookups, not in role code.

Structured mapping format (per password input):

```yaml
<password_input_var>:
  active: "<value-or-lookup>"
  next: "<value-or-lookup>"
  # optional fallback keys when slot key is missing:
  # value: "<value-or-lookup>"
  # password: "<value-or-lookup>"
```

Published effective vars:
- `aap_admin_password_effective`
- `aap_gateway_admin_password_effective`
- `aap_controller_admin_password_effective`
- `aap_hub_admin_password_effective`
- `aap_eda_admin_password_effective`
- `aap_postgresql_admin_password_effective`
- `aap_deploy_*_admin_password_effective` outputs

## Dependencies

None.

## Example Playbook

```yaml
- name: Load shared AAP context
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap
      vars:
        aap_deploy_enabled: true
        aap_password_active: active
        aap_password_active_slot: active
        aap_password_require_component_inputs: true
        aap_gateway_admin_password_input:
          active: "{{ lookup('my_secret_backend_get_or_create', 'aap/gateway/admin') }}"
          next: "{{ lookup('my_secret_backend_get_or_create', 'aap/gateway/admin_next') }}"
        aap_controller_admin_password_input: "{{ lookup('my_secret_backend_get_or_create', 'aap/controller/admin') }}"
        aap_hub_admin_password_input: "{{ lookup('my_secret_backend_get_or_create', 'aap/hub/admin') }}"
        aap_eda_admin_password_input: "{{ lookup('my_secret_backend_get_or_create', 'aap/eda/admin') }}"
        aap_postgresql_admin_password_input: "{{ lookup('my_secret_backend_get_or_create', 'aap/postgresql/admin') }}"
```

## License

GPL-3.0-only

## Author

Lightning IT
