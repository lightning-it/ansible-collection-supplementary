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
7. If the Incus image workaround changes, update this directory and `deploy/incus/README.md`
   together so the image assumptions stay consistent.

