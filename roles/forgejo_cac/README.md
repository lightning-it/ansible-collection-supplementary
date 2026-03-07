# forgejo_cac

Configuration-as-Code orchestration role for Forgejo.

This role intentionally separates object/API orchestration concerns from runtime deployment
(`forgejo_deploy`), following the `_cac` role split used across the collection.

## Requirements

None.

## Variables

See `roles/forgejo_cac/defaults/main.yml`.

Key variables:
- `forgejo_cac_skip_apply`
- `forgejo_cac_url`
- `forgejo_cac_token`
- `forgejo_cac_admin_user`
- `forgejo_cac_admin_password`

## Dependencies

None.

## Example Playbook

```yaml
- name: Validate Forgejo API preflight
  hosts: localhost
  gather_facts: false
  roles:
    - role: lit.supplementary.forgejo_cac
      vars:
        forgejo_cac_skip_apply: false
        forgejo_cac_url: http://127.0.0.1:3000
        forgejo_cac_admin_user: admin
        forgejo_cac_admin_password: changeme
```

## License

GPL-3.0-only

## Author

Lightning IT
