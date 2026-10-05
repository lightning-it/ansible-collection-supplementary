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
- `keycloak_deploy_manage_postgres`
- `keycloak_deploy_postgres_image`
- `keycloak_deploy_postgres_pod_name`
- `keycloak_deploy_postgres_pod_manifest_path`
- `keycloak_deploy_db_host`
- `keycloak_deploy_db_port`
- `keycloak_deploy_db_name`
- `keycloak_deploy_db_user`
- `keycloak_deploy_db_password`
- `keycloak_deploy_admin_user`
- `keycloak_deploy_admin_password`
- `keycloak_deploy_generate_secrets`
- `keycloak_deploy_manage_systemd`
Proxy headers require valid `keycloak_deploy_proxy_trusted_addresses`, rendered
as `KC_PROXY_TRUSTED_ADDRESSES`. Edge TLS keeps Keycloak on host loopback,
attaches NGINX and Keycloak to a pinned private Quadlet network, and trusts only
the NGINX pod address.

Managed bridge PostgreSQL requires a private `keycloak_deploy_db_host` matching
its pinned network IP or the exact managed PostgreSQL pod DNS name; readiness
uses the published host endpoint. Arbitrary external DNS names and Keycloak
loopback are rejected. DNS mode requires network-local Podman name resolution,
an explicit resolver firewall allowance, and positive/negative DNS evidence;
it does not replace static firewall addresses or trusted proxy CIDRs.

`keycloak_deploy_native_network_migration` is a default-off, coupled transition
for two already active, root-owned native Quadlets without drop-ins. Set
`keycloak_deploy_native_previous_networks` to the exact prior `keycloak` and
`postgres` Network lists, including explicit empty lists for default-network
units. The database endpoint must be its declared IPv4 or exact managed pod
DNS name; Keycloak must have its own address on the same database network.
Bind `keycloak_deploy_native_network_runtime_names` explicitly from each Network
entry basename (including a `.network` suffix where used) to its actual Podman
network name. Runtime verification compares names and addresses, not addresses
alone. Before stopping either service, actual images, data mounts and database
endpoint must match the proven original configuration. Rollback verifies the
original network names and database endpoint; explicit prior addresses remain
pinned, while addresses on implicit default networks may legitimately change.
An empty prior Network list is supported only when runtime inspection proves
exactly `podman-default-kube-network`, the Podman non-host kube default. Arbitrary
single attachments or additional manually attached networks fail before either
service stops: an empty restored Quadlet cannot reconstruct them. This implicit
contract is verified against Podman 4.9.3, not a claim of live migration acceptance.

The transition runs before either ordinary deploy role. It snapshots both
manifests and Quadlets in memory under `no_log`, preserves images and data paths,
stops Keycloak before PostgreSQL, and writes only bound configuration through
descriptor-relative `atomic_path`. PostgreSQL readiness precedes Keycloak health
acceptance. A failed cutover restores both original configurations; external
content or parent-identity drift fails closed rather than being overwritten.
The transition does not support inactive, legacy, rootless, administrator-edited
or mixed prior/desired controllers. Controller termination is not a durable
automatic rollback guarantee; recovery requires retained authoritative source
configuration. Do not claim live migration acceptance from preparation tests.

`tests/unit/test_native_network_transaction.py` executes the production Ansible
cutover/rescue/always control flow with isolated, fault-injected I/O. It verifies
the exact failure boundary, paired recovery after stop/write/readiness failures,
external-drift refusal, and snapshot disposal. Its unchanged-plan case proves
the cutover is skipped, not whole-role idempotence. These deterministic tests do
not prove live Podman readiness, DNS resolution or atomic filesystem semantics;
the actual component profiles and live acceptance remain required.

Exactly one lifecycle controller owns the pod: native `.kube` Quadlet through
`lit.foundational.podman_systemd`, or explicit fail-closed direct kubeplay.
Both verify the active database endpoint before health acceptance. Quadlet
takeover disables only the exact legacy unit; its `<pod-name>-pod.service` name
avoids `keycloak.service` collisions. Missing systemd fails prechecks.

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
        keycloak_deploy_manage_systemd: true
        keycloak_deploy_networks:
          - keycloak-access.network:ip=10.89.40.2
        keycloak_deploy_postgres_networks:
          - keycloak-access.network:ip=10.89.40.3
        # Requires verified network-local DNS without external forwarding.
        keycloak_deploy_db_host: keycloak-postgres
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
