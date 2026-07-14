# vault_scoped_approle

Bootstraps one least-privilege HashiCorp Vault KV v2 policy and batch-token AppRole, persists its Role ID and first
Secret ID as immutable controller-authoritative Ansible Vault ciphertext, proves exact token capabilities, and only
then revokes the supplied initial root token.

The role is intentionally strict:

- HTTPS certificate validation cannot be disabled.
- `VAULT_ADDR`, `VAULT_TOKEN`, and `VAULT_SKIP_VERIFY` must be absent from the environment.
- First configuration requires an in-memory initial root-token handoff.
- Existing controller ciphertext is immutable and must authenticate successfully.
- A rerun validates the stored AppRole, policy, role settings, and exact capability probes without needing root.
- All credential-bearing tasks use `no_log`.

See `defaults/main.yml` for the complete variable contract. The caller owns the policy text, KV mount, role name,
controller escrow path, TTLs, and exact capability probes.

## Requirements

- An initialized and unsealed HashiCorp Vault HTTPS API with a pinned controller CA.
- A loaded Ansible Vault identity for immutable controller escrow.
- An initial root token in protected memory for first configuration, or an existing exact AppRole escrow for
  read-only validation.

## Variables

See `defaults/main.yml` for the complete contract. Required caller-owned inputs include the Vault API and CA paths,
KV and AppRole mount/name settings, exact policy and capability probes, bounded token settings, controller escrow
root and document paths, and document subject. `vault_scoped_approle_revoke_admin_token` controls whether a supplied
initial root token must be revoked and immediately proven invalid after scoped validation.

## Dependencies

The role uses `lit.foundational.ansible_vault_document` to create or verify the immutable encrypted controller
document. Collection dependencies are declared in `galaxy.yml`.

## Example Playbook

```yaml
---
- name: Bootstrap a scoped Vault AppRole
  hosts: vault_servers
  gather_facts: false
  roles:
    - role: lit.supplementary.vault_scoped_approle
      vars:
        vault_scoped_approle_api_url: https://127.0.0.1:18200
        vault_scoped_approle_ca_cert_path: /secure/vault/ca.crt
        vault_scoped_approle_admin_token: "{{ vault_bootstrap_token }}"
        vault_scoped_approle_kv_mount_point: infrastructure
        vault_scoped_approle_role_name: controller-automation
        vault_scoped_approle_policy_name: controller-automation
        vault_scoped_approle_policy: |
          path "infrastructure/data/example/*" {
            capabilities = ["create", "read", "update", "patch"]
          }
        vault_scoped_approle_controller_escrow_root_path: /secure/vault
        vault_scoped_approle_controller_document_path: /secure/vault/controller-approle.vault.yml
        vault_scoped_approle_document_subject: controller-automation
        vault_scoped_approle_capability_probes:
          - path: infrastructure/data/example/item
            capabilities: [create, read, update, patch]
```

## License

MIT

## Author

Lightning IT
