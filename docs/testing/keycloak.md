# Keycloak Test Architecture

Keycloak has exactly three canonical Molecule scenarios. Each uses the standard
Molecule lifecycle, deploys through this collection's roles, and has an
independent verify phase that checks externally observable state.

| Profile | Purpose | Normal trigger |
|---|---|---|
| Tiny | Fast deployment, health, database, realm, client, roles, token, permissions, and idempotency | Pull request |
| Heavy | Production-like PostgreSQL, LDAP, persistence, restart, backup/restore, TLS, authorization, and secret checks | Main, nightly, release |
| Application Acceptance | Browser login/logout plus positive and negative OIDC authorization journeys | Main, nightly, release |

Run the profiles directly from the collection root:

```bash
MOLECULE_RUN_PROTECTED=true molecule test -s keycloak-tiny
MOLECULE_RUN_PROTECTED=true molecule test -s keycloak-heavy
MOLECULE_RUN_PROTECTED=true molecule test -s keycloak-application-acceptance
```

Set `KEYCLOAK_TEST_IMAGE` and `KEYCLOAK_TEST_TARGET` for the documented matrix.
The supported targets are Ubuntu 24.04, RHEL 9, and RHEL 10. An unsupported
target fails during prepare; it is never silently skipped. `KEYCLOAK_TEST_OWNER`
and `KEYCLOAK_TEST_INSTANCE` may be set for local isolation. CI derives unique
names from repository, run ID, attempt, target, and scenario.

The acceptance test is application-scoped. It proves Keycloak identity and
authorization against a minimal test-only relying party. It does not claim that
OpenShift, AAP, Forgejo, or another downstream architecture consumes Keycloak.

Legacy Keycloak Basic/lifecycle scenarios are replaced by these executable
profiles because their skip-mode marker assertions did not prove deployment.

## Troubleshooting and cleanup

Inspect Molecule and JUnit failures first. For an interrupted run, remove only
an instance whose owner matches yours:

```bash
incus config get INSTANCE user.keycloak-test-owner
incus delete --force INSTANCE
```

Never bulk-delete Incus instances on a shared runner.
