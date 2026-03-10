# aap_ops

Operate AAP host install (restart, status, upgrade, sync_hub_password, rotate_password, backup, restore, certs).

## Requirements

None.

## Variables

See `roles/aap_ops/defaults/main.yml` and `roles/aap/defaults/main.yml`.

Key variables:
- `aap_ops_action`
- `aap_ops_package_state`
- `aap_ops_systemd_unit_name`
- `aap_ops_sync_hub_password_file_path`
- `aap_ops_sync_hub_password_value`
- `aap_ops_rotate_controller_username`
- `aap_ops_rotate_controller_current_password`
- `aap_ops_rotate_controller_new_password`
- `aap_ops_rotate_generate_password`

Password input behavior:
- Inventory is the source of truth.
- Inventory may provide plain values, Ansible Vault values, or lookup-based values (for example HCP Vault).
- This role does not read or write Vault directly.

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

Sync `automationhub_admin_password` into `aap-config.yml`:

```yaml
- name: Sync automation hub password in aap-config.yml
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_ops
      vars:
        aap_ops_action: sync_hub_password
        aap_ops_sync_hub_password_file_path: /etc/ansible-automation-platform/aap-config.yml
        aap_ops_sync_hub_password_value: "{{ aap_hub_admin_password_effective }}"
```

Run vendor AAP backup:

```yaml
- name: Backup AAP
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_ops
      vars:
        aap_ops_action: backup
```

Run vendor AAP restore:

```yaml
- name: Restore AAP
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_ops
      vars:
        aap_ops_action: restore
```

Install/rotate AAP TLS certificates via vendor role:

```yaml
- name: Apply AAP certs
  hosts: aap_nodes
  gather_facts: true
  roles:
    - role: lit.supplementary.aap_ops
      vars:
        aap_ops_action: certs
        aap_certs_controller_ssl_cert: /path/to/tower.cert
        aap_certs_controller_ssl_key: /path/to/tower.key
```

## License

GPL-3.0-only

## Author

Lightning IT
