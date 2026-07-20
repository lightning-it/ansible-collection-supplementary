# keycloak_cac

Configuration-as-Code orchestration role for Keycloak.

This role intentionally separates object/API orchestration concerns from runtime deployment
(`keycloak_deploy`), following the `_cac` role split used across the collection.

## Requirements

The target Keycloak service must be available. The canonical Heavy and
Application Acceptance scenarios deploy it with `keycloak_deploy`.

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

`community.general` provides the Keycloak API modules declared in `galaxy.yml`.

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
        keycloak_cac_admin_password: "{{ vault_keycloak_admin_password }}"
```

## License

MIT

## Author

Lightning IT

## Enterprise test disposition

- Classification: configuration-as-code API orchestration.
- Maturity: production-supported through the registry-required Keycloak
  component profiles.
- Supported platform: Ubuntu 24.04. RHEL 9 and RHEL 10 remain candidates until
  their exact-commit matrices pass on approved images.
- Tiny: real realm, client, group, role, user, mapping, token, and idempotency
  reconciliation.
- Heavy: production-like deployment foundation, LDAP provider integration,
  persisted state, authentication, and negative credential checks.
- Application Acceptance: an independently reported apply, query, mutation,
  zero-change reconciliation, and deletion lifecycle, followed by browser and
  protected API behavior driven by reconciled identities and authorization
  state.
- Security: administrator, bind, and client credentials are ephemeral or
  supplied by a protected secret source and must never enter evidence.
- Evidence and commands: see
  [`docs/testing/keycloak.md`](../../docs/testing/keycloak.md).
- Limitations: the current suite does not claim complete deletion reconciliation
  for every supported Keycloak object type.
