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

## License

MIT

## Author

Lightning IT
