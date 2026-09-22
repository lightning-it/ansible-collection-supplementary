# guacamole_deploy

Deploys digest-pinned Guacamole, guacd, and PostgreSQL containers in one private
Podman pod. Only the web application is bound to the host (loopback by default);
guacd and PostgreSQL remain pod-internal.

## Requirements

- Ansible Core compatible with the collection's `meta/runtime.yml` contract.
- Podman on the managed host, or `guacamole_deploy_install_packages: true`.
- Vault-custodied database and local break-glass secrets.
- An OpenID Connect provider when OIDC is enabled.

## Variables

All defaults are defined in `defaults/main.yml`.

- `guacamole_deploy_connections` declares credential-free RDP, SSH, or VNC
  connections.
- `guacamole_deploy_network_name` and `guacamole_deploy_network_ipv4` optionally
  bind the pod to one pre-existing Podman network and one exact IPv4 address.
  They must be set together; the role does not create or modify the network.
- `guacamole_deploy_no_proxy` optionally replaces the inherited container proxy
  bypass list with exact direct destinations. This permits server-side OIDC/JWKS
  requests to traverse the site forward proxy even when a broader host bypass
  suffix exists. The empty default leaves inherited behavior unchanged.
- `guacamole_deploy_oidc_enabled` enables the OpenID Connect extension and
  requires issuer, authorization, JWKS, client, and redirect settings.
- `guacamole_deploy_oidc_groups_claim_type` explicitly selects the token claim
  that carries group names and defaults to `groups`.
- `guacamole_deploy_oidc_username_claim_type` selects the username claim and
  preserves the upstream default `email`. New installations can select `sub`
  with one fixed, verified issuer to avoid email-based identity collisions.
  Changing this claim or the issuer on an existing deployment is an identity
  migration: inventory existing database identities and permissions first.
  This setting does not assign connection access or administrative privileges,
  and does not by itself prove cross-tier isolation or session revocation.
- `guacamole_deploy_oidc_group_connections` maps an exact OIDC group name to a
  non-empty list of declared connection names. The role exclusively owns groups
  it creates for this contract and refuses to adopt a pre-existing same-name
  group. It removes undeclared role-owned groups and reconciles each retained
  group to only the requested connection `READ` permissions: group nesting,
  membership, system privileges, and permissions on users, groups, connection
  groups, or sharing profiles are removed.
- `guacamole_deploy_api_session_timeout_minutes` bounds web/API inactivity to
  between 1 and 1440 minutes and defaults to 60.

Credentials must not be placed in connection or group contracts. The local
break-glass hash changes only when its Vault-custodied password or salt changes.

## Dependencies

Runtime images are digest-pinned in `defaults/main.yml`. The role uses the
PostgreSQL and OpenID Connect extensions shipped by the pinned Guacamole image.

## Example Playbook

```yaml
---
- name: Deploy Guacamole with OIDC connection authorization
  hosts: guacamole
  become: true
  roles:
    - role: lit.supplementary.guacamole_deploy
      vars:
        guacamole_deploy_oidc_enabled: true
        guacamole_deploy_oidc_authorization_endpoint: https://idp.example.com/authorize
        guacamole_deploy_oidc_jwks_endpoint: https://idp.example.com/certs
        guacamole_deploy_oidc_issuer: https://idp.example.com
        guacamole_deploy_oidc_redirect_uri: https://guacamole.example.com/guacamole/
        guacamole_deploy_network_name: podman-default-kube-network
        guacamole_deploy_network_ipv4: 10.89.0.20
        guacamole_deploy_no_proxy: [localhost, 127.0.0.1]
        guacamole_deploy_connections:
          - name: Workbench
            protocol: rdp
            parameters:
              hostname: 192.0.2.10
              port: "3389"
        guacamole_deploy_oidc_group_connections:
          - name: workbench-users
            connection_names: [Workbench]
```

## License

MIT

## Author

Lightning IT
