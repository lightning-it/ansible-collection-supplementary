# AAP Development Agent Guide

Scope: AAP development work for `roles/aap`, `roles/aap_prepare`,
`roles/aap_deploy`, `roles/aap_cac`, and `roles/aap_destroy`.

This guide is only for AAP role development. Production runbooks belong in the
automation/inventory/operations repositories.

## Boundaries

1. Do not add Incus lifecycle shell helpers to this collection.
2. Use `lit.ubuntu.incus_instance` for Incus guests.
3. Use `lit.rhel.rhsm`, `lit.rhel.repos`, `lit.rhel.virtual_guest`, and
   `lit.rhel.podman` for RHEL host preparation.
4. Keep RHEL base images unregistered. Cloud-init owns boot identity and SSH
   access only; Ansible owns RHSM registration and unregister.
5. Keep AAP bundle and manifest discovery, validation, download, copy, and
   staging in `lit.supplementary.aap_prepare`.
6. Keep `lit.supplementary.aap_deploy` focused on consuming prepared paths,
   rendering installer inventory, and running the AAP 2.7 installer.

## AAP 2.7 Role Rules

1. `aap_deploy` supports AAP 2.7 containerized setup.
2. Do not add entitlement-gated Red Hat collections to `galaxy.yml`.
3. Keep Automation Hub-only requirements in the consumer runtime overlay.
4. Keep role-owned variables prefixed with the owning role name.
5. Keep `acl` available through RHEL host preparation. The upstream installer can
   fail while becoming the rootless AAP install user (`svc_aap` by default) if
   POSIX ACL tooling is missing.
6. Keep AAP installer temp handling in `aap_deploy`; this is distinct from the
   generic Ansible remote temp role in `lit.foundational`.

## Verification

1. For repository hygiene, run:

```bash
git diff --check
```

2. For changed role logic, run:

```bash
bash scripts/devtools-ansible-lint.sh
bash scripts/devtools-collection-smoke.sh
bash scripts/devtools-galaxy-verify.sh
```

3. For protected full-install validation, use the consumer validation workflow
   that composes `lit.ubuntu.incus_instance`, `lit.rhel.*`, and this collection's
   AAP roles.

## Secret Storage Rule

- Never commit secret values, tokens, passwords, private keys, activation codes, or decrypted Vault output.
- When HC Vault is configured for a role or runbook, generated credentials must be read from HC Vault first, generated only when missing, written back to HC Vault, and then consumed by the application from the Vault-backed Ansible variables. Do not keep generated plaintext secret files on the managed host unless a role has an explicit break-glass option such as `*_allow_local_secret_files=true`.
- When HC Vault is not configured, required credentials must be supplied from Ansible Vault encrypted inventory variables. Do not add new plaintext generated-secret fallbacks.
- Tasks that read, generate, write, template, or compare secret material must use `no_log: true`.