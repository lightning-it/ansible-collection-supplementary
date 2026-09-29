# keycloak_deploy

Deploy Keycloak as a dedicated Podman pod and (optionally) deploy PostgreSQL via
`postgres_deploy`.

## Requirements

`postgres_deploy` when `keycloak_deploy_manage_postgres` is enabled. Podman and
the operating-system preparation declared by the caller are required.

## Variables

See `roles/keycloak_deploy/defaults/main.yml`.

Key variables:
- `keycloak_deploy_image`
- `keycloak_deploy_pod_manifest_path`
- `keycloak_deploy_host_data_dir`
- `keycloak_deploy_port`
- `keycloak_deploy_host_ip`
- `keycloak_deploy_networks`
- `keycloak_deploy_postgres_networks`
- `keycloak_deploy_manage_postgres`
- `keycloak_deploy_postgres_image`
- `keycloak_deploy_postgres_pod_name`
- `keycloak_deploy_postgres_pod_manifest_path`
- `keycloak_deploy_db_host`
- `keycloak_deploy_db_port`
- `keycloak_deploy_postgres_port`
- `keycloak_deploy_postgres_container_port`
- `keycloak_deploy_db_name`
- `keycloak_deploy_db_user`
- `keycloak_deploy_db_password`
- `keycloak_deploy_admin_user`
- `keycloak_deploy_admin_password`
- `keycloak_deploy_generate_secrets`
- `keycloak_deploy_manage_systemd`
- `keycloak_deploy_proxy_headers`
- `keycloak_deploy_proxy_trusted_addresses`

When proxy headers are enabled, `keycloak_deploy_proxy_trusted_addresses` is
mandatory, every entry must be a valid IPv4/IPv6 address or CIDR, and the list
is rendered as `KC_PROXY_TRUSTED_ADDRESSES`. This prevents a
non-proxy peer from forging client, scheme, host, or port identity. Edge TLS
deployments should publish Keycloak only on loopback, attach NGINX and Keycloak
to an explicitly pinned private Quadlet network, and list only the NGINX pod
address as trusted.

When this role manages PostgreSQL and both pods use the Podman bridge network,
`keycloak_deploy_db_host` defaults to Podman's stable `<postgres-pod-name>` DNS
alias; the runtime container name is not a cross-pod discovery contract.
The private endpoint uses `keycloak_deploy_postgres_container_port`; readiness
uses the published `keycloak_deploy_postgres_port`.
`keycloak_deploy_postgres_networks` defaults to the same named networks after
removing Keycloak-specific options such as its fixed IP, so both pods share the
private DNS domain without reusing an address. An explicit override can pin a
separate PostgreSQL address on those same networks.
The controller-side readiness probe remains bound to
`keycloak_deploy_postgres_host_ip`. A bridge-networked Keycloak container must
never use its own loopback address as the database endpoint.

Exactly one lifecycle controller owns a Keycloak pod. The container
configuration is rendered as Kubernetes YAML. With systemd management enabled,
the role hands that manifest to a native `.kube` Quadlet managed through
`lit.foundational.podman_systemd`; it never starts the active pod directly.
Without systemd management, the role uses one fail-closed kubeplay recreation.
Both paths read back the non-secret database-host entry from the active
container and reject a stale pod before health acceptance. An exact legacy
`podman-kube@<escaped-manifest>.service` instance is stopped and disabled once
before native Quadlet takeover.
The default native unit is named `<pod-name>-pod.service` so it cannot collide
with an administrator-managed `keycloak.service`. Enabling systemd management
without a detected systemd service manager fails during prechecks.

## Dependencies

Runtime composition uses `lit.supplementary.postgres_deploy` when PostgreSQL is
managed by this role and `lit.foundational` Podman lifecycle roles declared by
the collection.

## Example Playbook

```yaml
- name: Deploy Keycloak
  hosts: wunderboxes
  become: true
  roles:
    - role: lit.supplementary.keycloak_deploy
      vars:
        keycloak_deploy_manage_postgres: true
        keycloak_deploy_admin_user: admin
        keycloak_deploy_generate_secrets: false
        keycloak_deploy_admin_password: "{{ vault_keycloak_admin_password }}"
        keycloak_deploy_db_password: "{{ vault_keycloak_db_password }}"
```

## License

MIT

## Author

Lightning IT

## Enterprise test disposition

- Classification: web application deployment.
- Maturity: production-supported through the registry-required Keycloak
  component profiles.
- Supported platform: Ubuntu 24.04. RHEL 9 and RHEL 10 remain candidates until
  their exact-commit matrices pass on approved images.
- Tiny: real deployment, PostgreSQL, readiness, OIDC, version, permissions, and
  idempotency.
- Heavy: PostgreSQL, LDAP integration, persistence, restart, an isolated
  destructive table restore drill, authentication, and authorization. An
  independent LDAP client verifies the ephemeral CA and service hostname.
- Application Acceptance: browser/OIDC login, protected endpoints, positive and
  negative authorization, invalid credentials, logout, and session invalidation.
- Evidence: meaningful JUnit/Allure, redacted logs, environment metadata, and
  the collection evidence manifest.
- Limitations: the restore drill is intentionally scoped to an isolated probe
  table and is not a whole-database disaster-recovery claim. No supported
  upgrade path or separate Keycloak JVM truststore-enforcement claim is made.

Run the three scenarios documented in
[`docs/testing/keycloak.md`](../../docs/testing/keycloak.md). No external service
credential is required; use ephemeral test credentials only.
