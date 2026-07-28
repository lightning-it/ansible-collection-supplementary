===================================================
Lightning IT Collection Release Notes Release Notes
===================================================

.. contents:: Topics

v1.40.0
=======

Bugfixes
--------

- dependency - Lower the ``ansible.posix`` minimum to 2.1.0 and require ``lit.foundational`` 1.31.0 or newer, restoring a resolvable graph with ``fedora.linux_system_roles`` 1.127.2 and its ``ansible.posix >=2.1.0,<2.2.0`` constraint while leaving the Supplementary maximum uncapped for other consumers.

v1.39.0
=======

Minor Changes
-------------

- Add an opt-in strict ``vault_bootstrap`` controller-authoritative init escrow branch using the immutable ``lit.foundational.ansible_vault_document`` action, in-memory Ansible Vault loading, fail-closed lifecycle state gates, and ciphertext-only drift-protected target synchronization.
- Add inventory-driven Vault listener and advertised address settings, retain file storage as the compatibility default, and support validated single-node integrated Raft storage with explicit cluster address and node ID inputs.
- Add optional digest-pinned execution environment references for Machine A pulls and exports, target-side staging, and execution environment runs.
- Add vault_raft_snapshot for append-only encrypted off-host Raft snapshot escrow with explicit ciphertext checks and a digest-pinned, loopback-only, isolated restore drill that validates cluster identity and exact KV hashes.
- Add vault_scoped_approle for certificate-validated least-privilege batch-token AppRole bootstrap, immutable controller Ansible Vault escrow, exact capability validation, and gated initial-root-token revocation.
- Align the collection dependency contract with community.hashi_vault 7.1.0 and lit.foundational 1.30.0 or newer so collection installation and Modulix execution-environment resolution use one supported version.
- Keep the Vault container VAULT_ADDR aligned with the advertised API address and publish the cluster port only when Raft storage is selected.
- release_model - Route collection publishing through a protected main-branch dispatch with the standard Galaxy environment credential, ignore generated local collection and Python cache trees, and use the managed execution environment's ansible-lint version.
- vault_deploy can now require an immutable OCI digest, separate the advertised API address from the in-container client URL, and explicitly control mlock for loopback-only production topologies.

Bugfixes
--------

- Correct Vault bootstrap init-payload persistence and handoff so first-run unseal and configuration consume the newly generated keys and root token, while retaining read compatibility with interim payload keys.
- Correct the existing-escrow bounded-token policy assertion so resumable validation uses the configured scoped policy name.
- Fail closed every Raft snapshot Vault API request against controller proxies, require the literal localhost TLS identity for restore, and retain 127.0.0.1-only port publishing so credentials, snapshots, and destructive recovery calls cannot reach an unintended endpoint.
- Generate Vault bootstrap private keys only on the managed host, plumb explicit trusted CA paths through lifecycle HTTPS clients, and remove TLS skip-verify from initialization and unseal operations.
- Harden aap_local_execution by refreshing staged automation source without retaining stale artifacts, preserving TLS assets, enforcing verified SSH host keys and CA trust, and using a dedicated Ansible config that avoids unrelated Ansible Vault password files when HashiCorp Vault is selected.
- Make execution environment archives digest-specific and identity-checked, publish them atomically, and honor the documented archive refresh controls so digest rotation cannot reuse a stale Machine A payload.
- Make strict Vault validation require an initialized and unsealed instance, and guarantee cleanup of protected controller temporary files used for init-document encryption and decryption.
- Persist the scoped AppRole schema version as a native integer and immediately prove initial-root-token revocation after the least-privilege AppRole passes its exact policy and capability gates.
- Prevent Vault AppRole credentials, Vault tokens, generated PKI private keys, staged SSH private keys, and AAP execution-environment secret context from appearing in Ansible task output.
- Resolve the actual Podman kube systemd template instance consistently for Vault deploy, operations, and backup.
- Submit only the Vault-reported threshold number of unseal shares in protected HTTPS request bodies instead of exposing shares in process arguments.
- aap_deploy - Preserve valid YAML indentation when hardening the prepared EDA readiness condition.

v1.38.0
=======

Minor Changes
-------------

- docs - Apply the shared enterprise README structure.
- docs - Consolidate generated governance metadata and license policy on shared-assets-lit.
- release_model - Add managed compatibility matrix documentation and structured release evidence fields.

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
