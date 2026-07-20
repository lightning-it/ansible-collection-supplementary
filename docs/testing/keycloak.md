# Keycloak Test Architecture

Keycloak has exactly three canonical Molecule scenarios. Each uses the standard
Molecule lifecycle, deploys through this collection's roles, and has an
independent verify phase that checks externally observable state.

| Profile | Purpose | Normal trigger |
|---|---|---|
| Tiny | Fast deployment, health, database, realm, client, roles, token, permissions, and idempotency | Approved same-repository PR, protected branch, nightly, manual |
| Heavy | PostgreSQL, LDAP, persistence, restart, backup and restore, authorization, and secret checks | Approved same-repository PR, protected branch, nightly, manual |
| Application Acceptance | CaC lifecycle plus browser login/logout and positive and negative OIDC authorization journeys | Approved same-repository PR, protected branch, nightly, manual |

Create a unique local identity and ephemeral credentials before running a
profile. The values remain in the current shell only; never reuse production
credentials:

```bash
export MOLECULE_RUN_PROTECTED=true
export MOLECULE_TEST_REPOSITORY=local/ansible-collection-supplementary
export MOLECULE_TEST_RUN_ID="local-$(id -u)-$(date +%s)"
export MOLECULE_TEST_RUN_ATTEMPT=1
export MOLECULE_TEST_TARGET=ubuntu-24.04
export KEYCLOAK_TEST_TARGET=ubuntu-24.04
export KEYCLOAK_TEST_IMAGE=images:ubuntu/24.04

for name in \
  DB ADMIN VIEWER LDAP LDAP_BIND LDAP_USER CAC_OPERATOR CAC_DENIED \
  CLIENT SESSION UNAUTHORIZED INVALID
do
  value="$(openssl rand -hex 32)"
  export "KEYCLOAK_TEST_${name}_PASSWORD=$value"
done
export KEYCLOAK_TEST_CLIENT_SECRET="$KEYCLOAK_TEST_CLIENT_PASSWORD"
export KEYCLOAK_TEST_SESSION_SECRET="$KEYCLOAK_TEST_SESSION_PASSWORD"
export KEYCLOAK_TEST_CLIENT_ID=keycloak-test-client
export KEYCLOAK_TEST_ISSUER=http://127.0.0.1:28080/realms/keycloak-test
export KEYCLOAK_TEST_ADMIN_USERNAME=keycloak_test_admin
export KEYCLOAK_TEST_VIEWER_USERNAME=keycloak_test_viewer
export KEYCLOAK_TEST_UNAUTHORIZED_USERNAME=keycloak_test_unauthorized
export KEYCLOAK_TEST_INVALID_USERNAME=keycloak_test_invalid

run_keycloak_profile() {
  scenario="$1"
  export KEYCLOAK_TEST_INSTANCE="${scenario}-${MOLECULE_TEST_RUN_ID}"
  export KEYCLOAK_TEST_ARTIFACTS="$PWD/artifacts/local/${MOLECULE_TEST_RUN_ID}/${scenario}"
  molecule test -s "$scenario"
}

run_keycloak_profile keycloak-tiny
run_keycloak_profile keycloak-heavy
run_keycloak_profile keycloak-application-acceptance
```

Set `KEYCLOAK_TEST_IMAGE` and `KEYCLOAK_TEST_TARGET` for the registry-generated
matrix. Ubuntu 24.04 is the current supported target. RHEL 9 and RHEL 10 are
candidate targets and must not be claimed as supported until every profile
passes for the exact commit on approved images. An unavailable target is never
silently substituted or reported as a pass. `KEYCLOAK_TEST_OWNER` may override
the derived owner for an isolated local run. CI derives unique names from
repository, run ID, attempt, target, and scenario.

`.github/workflows/candidate-platform-validation.yml` exercises the RHEL 9 and
RHEL 10 candidate matrices on the protected `develop` schedule or by manual
dispatch from protected `main`. Its candidate-labelled evidence is always
non-release evidence. A passing run is only input to a reviewed registry change
from `candidate_targets` to `supported_targets`; the supported release matrix
must then pass again for the exact promoted protected-main commit.

The acceptance test is application-scoped. It proves Keycloak identity and
authorization against a minimal test-only relying party. It does not claim that
OpenShift, AAP, Forgejo, or another downstream architecture consumes Keycloak.
Before the browser suite, the scenario independently applies, queries, mutates,
reapplies without change, and deletes a uniquely named object through
`keycloak_cac`; those observations are written to a dedicated JUnit report in
the same preserved archive.
The relying party stores OIDC tokens and claims in its bounded process-local
session store, rotates the opaque browser session identifier after login, and
deletes the server-side state at logout. Failure evidence is produced in a
fresh cookie-free browser context from sanitized event metadata. The real
journey contributes action-only Playwright trace metadata; its private raw trace
is rewritten to remove network/resources, input values, headers, bodies,
cookies, storage, tokens, secrets, and URL queries before it can become
evidence.
The Acceptance target also inventories the exact Playwright package, stable
Chrome channel/version/executable digest, and installed operating-system packages;
release evidence rejects a missing or differently bound browser inventory and
adds these runtime components to the CycloneDX SBOM.

Legacy Keycloak Basic/lifecycle scenarios are replaced by these executable
profiles because their skip-mode marker assertions did not prove deployment.

The Heavy scenario seeds an isolated PostgreSQL probe table before backup,
destructively replaces only that table, restores it from the custom-format
backup, and compares the exact pre-backup and post-restore rows. This is a safe
application-data restore drill, not a claim of whole-cluster disaster recovery
or supported-version upgrade. Its LDAP client requires the scenario-owned CA
and verifies the `keycloak.test` certificate hostname for both the TLS probe and
authenticated search; permissive certificate verification is forbidden.

## Troubleshooting and cleanup

Inspect Molecule and JUnit failures first. For an interrupted run, remove only
an instance whose owner matches yours:

```bash
incus config get INSTANCE user.keycloak-test-owner
incus delete --force INSTANCE
```

Never bulk-delete Incus instances on a shared runner.
