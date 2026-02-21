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
- `aap_admin_password`
- `aap_admin_passwords_source_of_truth`
- `aap_admin_passwords_generate`
- `aap_admin_passwords_read_from_vault`
- `aap_admin_passwords_write_to_vault`
- `aap_admin_passwords_vault_addr`
- `aap_admin_passwords_vault_kv_mount`
- `aap_admin_passwords_vault_kv_path`

Shared admin password behavior:
- Optional foundational flow for gateway/controller/hub/eda/postgresql.
- Resolution is auto-enabled when one of these applies:
  - `aap_deploy_enabled=true`
  - `aap_ops_enabled=true` and `aap_ops_action=rotate_password`
  - `aap_ops_enabled=true` and `aap_ops_action=sync_hub_password`
- `aap_resolve_admin_passwords` can still be overridden explicitly when needed.
- Source of truth can be explicit via `aap_admin_passwords_source_of_truth` (`inventory` or `vault`).
- By default it auto-selects `vault` when Vault configuration/auth is available, otherwise `inventory`.
- Resolution order: explicit value -> Vault KV2 (source=`vault`) -> local cache (lab fallback only) -> generated value.
- Generation is intended for persisted flows; defaults are inventory-first and non-generating.
- With `inventory` source, each component password can be set individually.
- If a component password is not set, it falls back to `aap_admin_password`.
- Local cache fallback is disabled by default and intended for lab/offline usage only.
- Publishes effective vars usable by all AAP roles:
  - `aap_gateway_admin_password_effective`
  - `aap_controller_admin_password_effective`
  - `aap_hub_admin_password_effective`
  - `aap_eda_admin_password_effective`
  - `aap_postgresql_admin_password_effective`
- Also sets `aap_deploy_*_admin_password_effective` compatibility vars.

OS-specific defaults:
- Runtime loads package defaults from:
  - `roles/aap/defaults/rhel9.yml` on RHEL 9
  - `roles/aap/defaults/rhel10.yml` on RHEL 10

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
        aap_admin_passwords_source_of_truth: vault
        aap_admin_passwords_vault_addr: "{{ vault_address }}"
        aap_admin_passwords_vault_kv_mount: "{{ vault_engine_mount_point | default('stage-2c') }}"
        aap_admin_passwords_vault_kv_path: "{{ inventory_hostname }}/aap/deploy/admin_passwords"
```

## License

GPL-3.0-only

## Author

Lightning IT
