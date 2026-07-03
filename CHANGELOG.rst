===================================================
Lightning IT Collection Release Notes Release Notes
===================================================

.. contents:: Topics

v1.37.0
=======

Bugfixes
--------

- Update the CI collection preparation requirements to use ansible.posix 2.2.1.

v1.36.0
=======

Minor Changes
-------------

- Added Keycloak CaC support for LDAP user federation providers, including default Samba LDAPS provider values.
- Added PostgreSQL lifecycle roles for orchestration, preflight, config, validation, operations, upgrade, and protected destroy.
- Added Samba AD/LDAPS mode with default application groups/users and wired the Keycloak heavy Molecule scenario to use Samba as a live LDAPS auth source.
- Added container-based Samba lifecycle roles and a protected heavy Incus scenario that validates a real SMB share through Podman.
- Added container-based rsyslog lifecycle roles using podman_systemd for persistent Quadlet/systemd startup.
- Convert Grafana, Loki, Alloy, and Checkmk deploy roles to the shared Podman/Quadlet systemd management path and add an Incus heavy scenario covering the complete Atlas observability stack.
- Delegated AAP TLS asset staging to the foundational tls_assets helper role.
- Hardened AAP local execution by templating the generated local environment, improving idempotent change detection for source mirroring, Podman image handling, and remote artifact staging.
- Introduce LIT Atlas observability support with new Prometheus and Alertmanager deploy roles for Podman/Quadlet-managed container services.
- Kept prepared Hub collection seeding independent from execution environment image seeding for deployments that already provide container images from a registry.
- Simplified shared AAP admin password validation and added Molecule coverage for shared fallback plus per-component password overrides.

Bugfixes
--------

- Install the foundational collection from the v1.26.0 release artifact during collection preparation so CI can satisfy the declared ``lit.foundational`` dependency before the matching Galaxy version is available.

v1.35.0
=======

Minor Changes
-------------

- lit.supplementary - Verify automated collection release workflow cycle 2.

v1.34.0
=======

Minor Changes
-------------

- lit.supplementary - Verify automated collection release workflow cycle 1.

v1.33.0
=======

Minor Changes
-------------

- Require lit.foundational 1.21.0 or newer.

Bugfixes
--------

- dhcp_deploy - Use a valid Ubuntu platform version in role metadata.

v1.32.0
=======

Minor Changes
-------------

- Require lit.foundational 1.21.0 or newer.

Bugfixes
--------

- dhcp_deploy - Use a valid Ubuntu platform version in role metadata.
