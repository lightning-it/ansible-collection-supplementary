# nessus_cac

Configuration-as-Code orchestration role for Nessus.

This role intentionally separates object/API orchestration concerns from runtime deployment
(`nessus_deploy`), following the `_cac` role split used across the collection.

## Requirements

None.

## Variables

See `roles/nessus_cac/defaults/main.yml`.

Key variables:
- `nessus_cac_skip_apply`
- `nessus_cac_url`
- `nessus_cac_username`
- `nessus_cac_password`

## Dependencies

None.

## Example Playbook

```yaml
- name: Validate Nessus API preflight
  hosts: localhost
  gather_facts: false
  roles:
    - role: lit.supplementary.nessus_cac
      vars:
        nessus_cac_skip_apply: false
        nessus_cac_url: https://127.0.0.1:8834
        nessus_cac_username: admin
        nessus_cac_password: changeme
```

## License

GPL-3.0-only

## Author

Lightning IT
