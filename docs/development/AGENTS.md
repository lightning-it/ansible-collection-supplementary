# AAP RHEL 10 Incus Development Guide

Scope: files in `docs/development/`.

These notes are for role development workflows, not production runbooks.

## Rules

1. Keep the control-node boundary explicit:
   - workbench runs Ansible and repository-local validation.
   - `ciwkr01` runs Incus, KVM, and RHEL guest VMs.
2. Do not document Incus as local to workbench for this workflow.
3. Do not commit secrets, tokens, private keys, or real passwords.
   Use environment variables such as `CIWKR01_PASS`, `AAP_BUNDLE_FILE`, and `GITHUB_TOKEN`.
4. Prefer copy/paste-ready command blocks, but keep secret values as required environment variables.
5. Use Ansible ad-hoc commands for `ciwkr01` checks where practical.
   Direct SSH is acceptable only for the temporary jump/proxy setup documented here.
6. Keep AAP full-install steps separate from public-safe smoke tests.
   Full install requires a private AAP bundle and may require RHSM access.
7. Incus lifecycle belongs to `lit.ubuntu.incus_instance`; do not add shell
   helper workflows under this collection.

## Secret Storage Rule

- Never commit secret values, tokens, passwords, private keys, activation codes, or decrypted Vault output.
- When HC Vault is configured for a role or runbook, generated credentials must be read from HC Vault first, generated only when missing, written back to HC Vault, and then consumed by the application from the Vault-backed Ansible variables. Do not keep generated plaintext secret files on the managed host unless a role has an explicit break-glass option such as `*_allow_local_secret_files=true`.
- When HC Vault is not configured, required credentials must be supplied from Ansible Vault encrypted inventory variables. Do not add new plaintext generated-secret fallbacks.
- Tasks that read, generate, write, template, or compare secret material must use `no_log: true`.
