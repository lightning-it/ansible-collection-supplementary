# vault_raft_snapshot

Creates a Vault integrated-Raft snapshot through a scoped AppRole, reads selected KV v2 documents only under
`no_log`, records their canonical SHA-256 identities, and persists the raw snapshot exclusively as immutable
controller-authoritative Ansible Vault ciphertext. The raw controller file exists only inside an owner-only temporary
directory and is removed in an `always` path.

The `restore_drill` action decrypts one selected escrow in Ansible memory, writes the raw snapshot only below an
isolated `/run` directory on the Vault host, starts a digest-pinned loopback-only temporary Vault container, restores
the snapshot, unseals it with the production threshold, validates the production cluster ID, authenticates the scoped
AppRole, and compares every selected KV document identity. It always removes the temporary container and raw data.
The production Vault container, storage directory, listeners, and keyslots are never stopped or altered.
Encrypted controller snapshots are append-only; the role does not delete or rotate prior recovery points.

See `defaults/main.yml` for the complete strict contract.

`vault_raft_snapshot_action: none` is a safe no-op and validates only the action selector. `backup` is idempotent for
an unchanged snapshot and fixed controller document path: the immutable encrypted document is verified rather than
rewritten. Callers should use a new timestamped document path for each intentional recovery point. `restore_drill`
is an explicitly requested operational proof and always creates and removes an isolated temporary runtime.

## Requirements

- An initialized, unsealed HashiCorp Vault using integrated Raft storage and an HTTPS API trusted by the pinned CA.
- A scoped AppRole permitted to read the selected KV v2 documents and create a Raft snapshot.
- A loaded Ansible Vault identity on the controller for encrypted snapshot escrow.
- For `restore_drill`, Podman, the exact digest-pinned Vault image, production TLS material, and the production Shamir
  threshold shares. The production certificate must contain `DNS:localhost`.
- The drill publishes both temporary ports only on `127.0.0.1` and refuses an existing container or work directory.

## Variables

See `defaults/main.yml` for the full interface. Set `vault_raft_snapshot_action` to `backup` or `restore_drill`, and
provide the role-prefixed API, CA, AppRole, controller escrow, image digest, document identity, and KV verification
inputs for active operations. Restore-only inputs are validated only for `restore_drill`.

`vault_raft_snapshot_max_raw_bytes` defaults to, and is hard-capped at, 128 MiB (134217728 bytes). The raw snapshot
must remain within this enforced bound before it is read into protected memory or encrypted for off-host escrow.

The controller document path is immutable. For restore, pin its SHA-256 digest with
`vault_raft_snapshot_expected_ciphertext_sha256` before the role decrypts it.
`vault_raft_snapshot_restore_tls_hostname` and `vault_raft_snapshot_restore_bind_address` are fail-closed to
`localhost` and `127.0.0.1`, matching the operational Vault PKI contract. The role refuses alternate DNS names or
bind addresses, derives every certificate-validated restore URL from those invariants, and disables proxy use for
every production and restore API request. This prevents credentials, snapshots, and the destructive restore
lifecycle from reaching another endpoint through controller proxy configuration or DNS.

## Dependencies

The role uses `lit.foundational.ansible_vault_document` for immutable encrypted controller documents. Collection
dependencies, including the supported `community.hashi_vault` version, are declared in `galaxy.yml`.

## Example Playbook

```yaml
---
- name: Create an encrypted Vault Raft recovery point
  hosts: vault_servers
  gather_facts: false
  roles:
    - role: lit.supplementary.vault_raft_snapshot
      vars:
        vault_raft_snapshot_action: backup
        vault_raft_snapshot_api_url: https://vault.example.com:8200
        vault_raft_snapshot_controller_ca_cert_path: /secure/vault/ca.crt
        vault_raft_snapshot_role_id: "{{ vault_recovery_role_id }}"
        vault_raft_snapshot_secret_id: "{{ vault_recovery_secret_id }}"
        vault_raft_snapshot_controller_escrow_root_path: /secure/vault/snapshots
        vault_raft_snapshot_controller_document_path: /secure/vault/snapshots/vault-20260714.vault.yml
        vault_raft_snapshot_document_subject: vault.example.com
        vault_raft_snapshot_image: >-
          docker.io/hashicorp/vault@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
        vault_raft_snapshot_verification_kv_paths:
          - mount_point: infrastructure
            path: recovery/sentinel
```

## Molecule Coverage

The dedicated `molecule/vault-raft-snapshot-basic` scenario exercises first-run and rerun backup behavior against a
TLS fake Vault API, verifies native integer schema values, exact KV and cluster identities, ciphertext-only escrow,
owner-only modes, and zero retained raw snapshot artifacts. Its fake-Podman executable restore path covers container
startup, initialization, snapshot force-restore, restart, production-threshold unseal, AppRole authentication, exact
KV verification, proxy refusal, and unconditional container/raw-artifact cleanup.

## License

MIT

## Author

Lightning IT
