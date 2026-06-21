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
- For `wunderbox02.prd.dmz.corp.l-it.io`, the HC Vault KV v2 mount is `stage-2c`. Store the Wunderbox02 generated application secrets at these exact paths, or provide the listed variables from Ansible Vault when HC Vault is not in use:

| Component | HC Vault path under `stage-2c` | Ansible Vault variables / keys |
|---|---|---|
| MinIO root | `wunderbox02.prd.dmz.corp.l-it.io/minio/root` | `minio_deploy_root_user`, `minio_deploy_root_password` / `root_user`, `root_password` |
| MinIO Vault bucket | `wunderbox02.prd.dmz.corp.l-it.io/minio/vault-bucket` | `minio_config_vault_bucket_access_key_effective`, `minio_config_vault_bucket_secret_key_effective` / `access_key`, `secret_key` |
| Forgejo | `wunderbox02.prd.dmz.corp.l-it.io/forgejo/secrets` | `forgejo_deploy_db_password`, `forgejo_deploy_admin_password`, `forgejo_deploy_admin_user` |
| Forgejo PostgreSQL | `wunderbox02.prd.dmz.corp.l-it.io/postgres/forgejo-postgres` | `postgres_deploy_db_password` / `postgres_deploy_db_password` |
| Keycloak | `wunderbox02.prd.dmz.corp.l-it.io/keycloak/secrets` | `keycloak_deploy_db_password`, `keycloak_deploy_admin_password`, `keycloak_deploy_admin_user` |
| Keycloak PostgreSQL | `wunderbox02.prd.dmz.corp.l-it.io/postgres/keycloak-postgres` | `postgres_deploy_db_password` / `postgres_deploy_db_password` |
| Nessus | `wunderbox02.prd.dmz.corp.l-it.io/nessus/admin` | `nessus_deploy_admin_user`, `nessus_deploy_admin_password` |
| Nexus admin | `wunderbox02.prd.dmz.corp.l-it.io/nexus/admin` | `nexus_target_admin_password` / `password` |
| Nexus AppRole KV | `wunderbox02.prd.dmz.corp.l-it.io/nexus/approle-kv` | `nexus_vault_kv_role_id`, `nexus_vault_kv_secret_id` / `role_id`, `secret_id` |
| Nexus AppRole PKI | `wunderbox02.prd.dmz.corp.l-it.io/nexus/approle-pki` | `nexus_vault_pki_role_id`, `nexus_vault_pki_secret_id` / `role_id`, `secret_id` |
| Grafana | `wunderbox02.prd.dmz.corp.l-it.io/grafana/admin` | `grafana_deploy_admin_user`, `grafana_deploy_admin_password` / `password` |
| Checkmk | `wunderbox02.prd.dmz.corp.l-it.io/checkmk/admin` | `checkmk_deploy_admin_user`, `checkmk_deploy_admin_password` / `password` |
