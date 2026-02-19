# aap_ops

Operate AAP host install (restart, status, upgrade).

## Requirements

None.

## Variables

See `roles/aap_ops/defaults/main.yml` and `roles/aap/defaults/main.yml`.

Key variables:
- `aap_ops_action`
- `aap_ops_package_state`
- `aap_ops_systemd_unit_name`

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

## License

GPL-3.0-only

## Author

Lightning IT
