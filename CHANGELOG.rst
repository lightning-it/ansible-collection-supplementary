===================================================
Lightning IT Collection Release Notes Release Notes
===================================================

.. contents:: Topics

v2.1.0
======

Minor Changes
-------------

- Add an opt-in AAP self-signed TLS setting that installs the generated CA into the RHEL system trust store for certificate-validating API clients.
- Add explicit initial and full AAP preflight phases so the read-only customer-baseline gate does not require AAP-owned paths before preparation.
- Route candidate-platform Heavy and Application Acceptance execution through the pinned ``modulix-validation`` reusable workflow while retaining local Tiny execution, exact-candidate evidence, and fail-closed promotion gates.
- aap_tls now validates that generated deployment certificate, key, and CA files are readable, and aap_deploy validates controller-side customer TLS source files before attempting to stage them.

Bugfixes
--------

- Accept required AAP host directories that the file module reports as planned creations during check mode while retaining strict apply checks.
- Allow customer TLS source files to be staged directly from the managed AAP host, keeping owner-only private keys off the automation controller.
- Allow temporary AAP TLS assets to be generated on a persistent delegated host instead of requiring controller-local storage.
- Allow trusted non-breaking Renovate pull requests to pass collection CI without an unrelated changelog fragment.
- Avoid the upstream AAP setup preparation role's undefined extraction result in check mode while retaining input validation and deterministic setup-path prediction.
- Configure gateway organizations idempotently through the Gateway REST API and the short-lived gateway token, avoiding connection failures in the ``ansible.platform.organization`` manager process.
- Create the controller-local AAP artifact directory before discovering locally supplied setup bundles and manifests.
- Defer AAP prepared-destination assertions until apply mode so a fresh check-mode run can report the planned staging operation without failing.
- Derive the AAP Hub upload readiness, Hub container registry, and EDA API URLs from aap_fqdn and their standard HTTPS ports. This prevents the upstream installer from probing the Pulp status path through the Gateway endpoint.
- Keep managed-host artifact staging check-mode safe when the destination directory does not exist yet, while validating the source checksum first.
- Keep read-only AAP preflight commands active in Ansible check mode so their registered results remain available to subsequent assertions.
- Keep the nested host-prepare preflight path assertion in apply mode so it does not reject directories that are deliberately only planned in check mode.
- Keep the read-only AAP install-user lookup active in check mode so account validation uses the real passwd entry.
- Let aap_prepare use aap_fqdn as the gateway DNS precheck hostname when neither aap_deploy_gateway_main_url nor aap_cac_gateway_hostname is set.
- Make AAP deployment preflight check-mode safe when the install user's systemd manager does not exist until the real rollout starts.
- Make Hub registry CA trust check-mode safe while the staged CA is a planned TLS asset, retaining real trust-store updates during apply.
- Make customer TLS staging check-mode safe when the target directory is a planned creation while preserving strict apply-time certificate staging.
- Make temporary self-signed AAP TLS generation check-mode safe by reporting the complete planned certificate chain without creating private keys.
- Make the AAP preflight DNS gate validate the configured platform FQDN instead of a potentially transport-only ansible_host value.
- Persist and apply SELinux file contexts for the AAP application mount, temporary directories, alternate user homes, and Podman storage during AAP host preparation.
- Prepare the AAP installer workspace and archive utilities during host preparation so a later deployment check can validate the vendor setup role without depending on check-mode-only filesystem or package changes.
- Preserve the upstream AAP 2.7 Gateway administrator credentials for Hub registry image uploads instead of replacing them with component-local Hub administrator credentials, which the platform registry rejects.
- Skip effective installer admin-password validation when ``aap_deploy_run_installer`` is disabled, allowing prepare-only deployment runs without loading unused installer secrets.
- Store private Hub CA trust under Podman's canonical host-only certs.d key when the HTTPS registry URL uses the implicit default port.

v2.0.3
======

Bugfixes
--------

- Limit the public release candidate checksum manifest to the collection archive when the CI candidate artifact also contains a runtime bundle.

v2.0.2
======

Bugfixes
--------

- Keep repository release-state validation independent of a specific release version so subsequent patch releases remain eligible.

v2.0.1
======

Bugfixes
--------

- Restrict release publication to the lit.supplementary collection archive when runtime evidence bundles are present beside the candidate.

v2.0.0
======

Major Changes
-------------

- Add three canonical Keycloak Molecule profiles for fast technical validation, production-like integration, and browser-based application acceptance, with auditable evidence and fail-closed release governance.

Minor Changes
-------------

- Add a ``aap-preflight-basic`` Molecule light scenario for the ``aap_preflight`` role to provide syntax coverage and prevent regressions in the prepared-host and execution-environment gate paths.
- Allow the AAP execution-environment preflight to validate either a fixed non-``latest`` image version or the existing immutable SHA-256 digest reference while preserving trusted registry TLS enforcement.
- CI - Select the protected Keycloak Tiny, Heavy, and Application Acceptance matrix only when the Keycloak quality family or one of its registered PostgreSQL, Samba, workflow, registry, or shared Incus dependencies changes.
- Delegate protected Heavy and Application Acceptance execution to the pinned reusable workflow owned by ``modulix-validation`` while retaining the exact-candidate, evidence, and fail-closed collection release gates.
- Extend AAP preflight with optional customer-prepared RHEL and immutable registry execution-environment gates.
- Harden the shared development container wrappers and keep the immutable Renovate validation image inventory synchronized with pre-commit tooling.
- Raise the enforced Vault Raft raw snapshot ceiling from 64 MiB to 128 MiB for production recovery points that have grown beyond the former bound.
- Support digest-required target-side EE pulls, encrypted Ansible Vault inventory generation, and separate AAP Container Registry credential plus EE configuration in local-execution flows.
- collection - Add a registry-driven Tiny, Heavy, Application Acceptance, evidence, CI, governance, and fail-closed release architecture for every role.

Breaking Changes / Porting Guide
--------------------------------

- Rename the AAP local-execution action from ``base_preflight`` to ``host_prepare_preflight`` and reference the canonical ``06-aap-host-prepare.yml`` playbook so application-owned host preparation is not presented as customer base-OS management.
- Rename the implementation role from ``aap_base_os`` to ``aap_host_prepare`` together with its internal variables and tags.
- Rename the successful combined preflight marker from ``AAP_BASE_OS_AND_PREFLIGHT_OK`` to ``AAP_HOST_PREPARE_AND_PREFLIGHT_OK``.

Deprecated Features
-------------------

- gitlab_runner - Deprecate the non-operational placeholder and make every invocation fail closed instead of allowing an acknowledged debug-only path.

Security Fixes
--------------

- Exclude project collection payloads, preserve registry TLS verification, and keep target Podman authentication separate from AAP credentials.
- Suppress controller credential-dispatch output so registry inputs remain protected even when the underlying configuration role changes verbosity.

Bugfixes
--------

- Bind Keycloak to the Samba-created LDAP identity and attach exact role and commit metadata to independently generated application-acceptance evidence.
- Capture Podman image records rather than container process records for immutable runtime dependency evidence in Keycloak quality profiles.
- Give large isolated Vault Raft snapshot restores a separately bounded client/server timeout and a tightly derived listener request-size allowance and temporary staging filesystem instead of reusing short or undersized defaults that reject valid approved snapshots, and report failures through secret-safe status classification.
- Harden the trusted Renovate and Copilot gates against transient API failures, unsafe major updates, shell word-splitting, outdated review findings, and best-effort Incus cleanup races.
- Install pinned Ansible and Molecule entry points in protected quality jobs instead of relying on runner-global packages, consume one immutable collection candidate with its runtime dependencies, and make concurrent Incus cleanup ownership-aware.
- Isolate UID and GID maps for nested Incus test containers so concurrent Podman workloads do not share and exhaust host per-user kernel key quotas.
- Refresh the pinned Keycloak acceptance security stack, execute the patched stable Chrome channel with exact version and executable-digest evidence, scan the exact shipped candidate independently while generated evidence remains covered by the fail-closed evidence scanner, and keep only runtime dependencies in the immutable bundle.
- Report only the non-secret raw Raft snapshot size and approved limit when the encrypted snapshot workflow reaches its bounded-size gate.
- Route the Heavy Keycloak LDAP provider through the loopback endpoint used by its host-networked container so LDAPS authentication reaches Samba.
- Trust the Heavy profile's ephemeral LDAP certificate authority inside Keycloak so the end-to-end LDAPS authentication proof validates TLS.
- Validate the configured AAP service FQDN during preflight instead of the execution environment's SSH transport address.

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
