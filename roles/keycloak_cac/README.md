# keycloak_cac

Configuration-as-Code orchestration role for Keycloak.

This role intentionally separates object/API orchestration concerns from runtime deployment
(`keycloak_deploy`), following the `_cac` role split used across the collection.

## Requirements

None.

## Variables

See `roles/keycloak_cac/defaults/main.yml`.

Key variables:
- `keycloak_cac_skip_apply`
- `keycloak_cac_url`
- `keycloak_cac_realm`
- `keycloak_cac_admin_user`
- `keycloak_cac_admin_password`

## Dependencies

None.

## Example Playbook

```yaml
- name: Validate Keycloak API preflight
  hosts: localhost
  gather_facts: false
  roles:
    - role: lit.supplementary.keycloak_cac
      vars:
        keycloak_cac_skip_apply: false
        keycloak_cac_url: http://127.0.0.1:8080
        keycloak_cac_realm: master
        keycloak_cac_admin_user: admin
        keycloak_cac_admin_password: changeme
```

## License

GPL-3.0-only

## Author

Lightning IT
