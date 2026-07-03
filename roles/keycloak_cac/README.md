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
- `keycloak_cac_samba_ldap_enabled`
- `keycloak_cac_samba_ldap_provider`
- `keycloak_cac_ldap_providers`

## Samba LDAPS user federation

Set `keycloak_cac_samba_ldap_enabled: true` to create a default Samba AD/LDAPS
LDAP provider in the target realm. Override `keycloak_cac_samba_ldap_provider`
for site-specific DNs, bind credentials, and connection URLs. Additional LDAP
providers can be supplied through `keycloak_cac_ldap_providers`.

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

MIT

## Author

Lightning IT
