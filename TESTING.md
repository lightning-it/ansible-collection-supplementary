# Testing

This collection uses three explicit role-quality profiles: Tiny, Heavy, and
Application Acceptance. The authoritative inventory is
[`meta/role-coverage.yml`](meta/role-coverage.yml); generated documentation is
in [`docs/testing/role-coverage.md`](docs/testing/role-coverage.md).

## Truthful support model

A role is production-supported only when every mandatory profile and target is
recorded as `supported` and backed by an executed, meaningful scenario. The
registry also records `experimental`, `not-applicable`, external blockers, and
deprecation. Stub and skip-mode scenarios remain visible as migration debt but
never count as a production pass.

## Profiles

### Tiny

Tiny executes the real role and checks inputs, resources, readiness, basic
authenticated behavior, secure permissions, secret safety, idempotency, and
cleanup. Tiny is the normal pull-request component gate.

### Heavy

Heavy uses the intended production deployment path in an isolated Incus target.
It validates applicable dependencies, TLS, networking, persistence, restart,
reconciliation, backup/restore, upgrades, role interaction, security, and
idempotency.

### Application Acceptance

Application Acceptance proves externally observable consumer behavior through
the correct browser, API, database, log, monitoring, network, agent, runner,
backup, CaC, or infrastructure surface. Positive and negative authorization are
mandatory where access control applies.

`verify` is a Molecule phase in every scenario. It is not a fourth profile, and
converge alone is never a pass.

## Local validation

Run the deterministic policy and unit checks first:

```bash
python3 scripts/validate-role-coverage.py check
python3 scripts/source_dependencies.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q scripts tests
yamllint .
actionlint
```

Run shared collection gates:

```bash
pre-commit run --all-files
bash scripts/devtools-ansible-lint.sh
bash scripts/devtools-molecule.sh
bash scripts/devtools-collection-smoke.sh
bash scripts/devtools-changelog-check.sh
```

Run a supported profile directly on a host with Incus:

```bash
MOLECULE_RUN_PROTECTED=true \
KEYCLOAK_TEST_TARGET=ubuntu-24.04 \
KEYCLOAK_TEST_IMAGE=images:ubuntu/24.04 \
molecule test -s keycloak-tiny
```

Create the mandatory ephemeral `KEYCLOAK_TEST_*` credentials first, using the
complete command block in
[`docs/testing/keycloak.md`](docs/testing/keycloak.md). Never reuse production
credentials in test runs.

## Matrix

Generate the exact supported cells from the registry:

```bash
python3 scripts/validate-role-coverage.py matrix --profile tiny
python3 scripts/validate-role-coverage.py matrix --profile heavy
python3 scripts/validate-role-coverage.py matrix --profile application_acceptance
```

Candidate platforms are not support claims. A platform becomes supported only
after every required cell passes. Matrix jobs use `fail-fast: false`; stable
aggregate jobs enforce the complete result.

## CI triggers

- Pull requests to `develop` run lint/sanity, build/install, registry and schema
  validation, and every supported Tiny, Heavy, and Application Acceptance cell.
- Pushes to `develop` run all internally executable supported cells and assemble
  evidence.
- A default-branch scheduler dispatches the workflow definition from protected
  `develop`; that nightly run exercises the full configured matrix and
  available external integrations.
- `develop` to `main` and release PRs run the complete exact-head release
  candidate matrix.
- A trusted `main` workflow must validate its exact SHA before publishing.

Mandatory jobs never suppress failures or use `continue-on-error`.
Self-hosted matrix jobs receive no repository/release secrets or OIDC write
permission. Same-repository pull-request heads must pass the non-bypassable
`ansible-collection-runtime-tests` environment review before code reaches a
self-hosted runner. Fork pull requests fail closed and require a maintainer to
reproduce the commit on a reviewed same-repository branch. Protected-branch
runs use the separate `ansible-collection-runtime-protected` environment.
Signing, attestations, and archival run only after protected-main validation in
the dedicated release-evidence environment.

## Reports and evidence

Every supported scenario produces meaningful JUnit and Allure results, redacted
logs, environment and tool metadata, commit/run identity, target parameters, and
application versions. Heavy and Application Acceptance add structured evidence.
Browser failures retain sanitized screenshots and traces; non-browser tests
retain redacted operation summaries.

Evidence is assembled and validated with:

```bash
python3 scripts/quality_evidence.py assemble
python3 scripts/quality_evidence.py validate
```

The evidence manifest calculates `release_eligible` from actual results. Missing
or malformed reports, skipped mandatory tests, secret findings, checksum errors,
or a commit mismatch fail closed.

Scheduled protected-`develop` and manually dispatched protected-`main`
candidate-platform runs use manifest mode `candidate`: a successful execution
records `candidate_execution_passed`, while `release_eligible` remains false
until a reviewed registry promotion and a new exact-SHA supported-matrix run.

See [`docs/testing/README.md`](docs/testing/README.md) for Incus, evidence,
external integration, acceptance, and troubleshooting details. Shipped image,
collection, and licensed product coverage is defined in
[`docs/testing/source-dependencies.md`](docs/testing/source-dependencies.md).
