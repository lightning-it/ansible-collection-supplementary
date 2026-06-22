# Lightning IT Ansible Collection Agent Guide (lit.*)

This file is the single source of truth for creating and evolving roles, Molecule scenarios,
and role documentation in `ansible-collection-*` repositories under the `lit.*` namespace.

Scope: role code, defaults, tasks, Molecule tests, role READMEs, and collection packaging hygiene.

## 0. Compatibility Baseline

1. Content MUST be compatible with the `ansible-core` range declared in `meta/runtime.yml`.
2. Content MUST NOT require Ansible major versions newer than 2.x.
3. `meta/runtime.yml` is the source of truth for `requires_ansible`; do not hardcode a different baseline in code,
   docs, tests, or CI.
4. New changes SHOULD remain compatible with the declared minimum version unless explicitly told otherwise.
5. Prefer `ansible.builtin.*` modules; use external collections only when required and declared in `galaxy.yml`.

## 1. Mandatory Discovery Before Changes

Before writing or changing role code, you MUST inspect repository reality first:

1. `galaxy.yml` for namespace/name/license/tags/dependencies/build_ignore.
2. `meta/runtime.yml` for collection compatibility.
3. Lint config: `.ansible-lint`, `ansible-lint.yml`, `.yamllint`, `.pre-commit-config.yaml`.
4. Existing role patterns under `roles/` (tasks, defaults, assert entrypoints, naming).
5. Molecule and script behavior under `molecule/` and `scripts/devtools-molecule.sh`.

If generic guidance conflicts with repository behavior, you MUST prefer repository behavior.

## 1.1 Shared-Assets Managed Files (Mandatory)

1. This repository receives centrally managed baseline files rendered from `lightning-it/shared-assets-lit`.
2. Do not hand-edit these files in downstream repos unless you also update `shared-assets-lit` and run sync.
3. Managed default files from `shared-assets-lit/default`:
   1. `CODE_OF_CONDUCT.md`
   2. `SECURITY.md`
   3. `scripts/wunder-devtools-ee.sh`
4. Managed collection baseline files from `shared-assets-lit/ansible-collection/base`:
   1. `AGENTS.md`
   2. `CONTRIBUTING.md`
   3. `.ansible-lint`
   4. `ansible.cfg`
   5. `renovate.json` rendered from `renovate.base.json`
   6. `changelogs/config.yaml`
   7. `.yamllint`
   8. `.gitignore`
   9. shared block in `.pre-commit-config.yaml`
   10. `scripts/bump_galaxy_version.py`
   11. `scripts/devtools-ansible-lint.sh`
   12. `scripts/devtools-collection-prepare.sh`
   13. `scripts/devtools-collection-smoke.sh`
   14. `scripts/devtools-galaxy-verify.sh`
   15. `scripts/devtools-galaxy.sh`
   16. `scripts/devtools-molecule.sh`
5. Repo-local exceptions MUST be explicit in the sync workflow and documented in the repository.

## 2. Repository Baseline (This Repo)

1. Repository identity values (namespace, name, license, tags, dependencies) MUST be read from `galaxy.yml`.
2. Do not copy identity metadata from another collection repository.
3. Linting uses 120-character YAML line length:
   1. `.yamllint` max line length 120
   2. `ansible-lint.yml` YAML max line length 120
4. Pre-commit runs devtools-based hooks for `yamllint`, `ansible-lint`, and Molecule light scenarios.

## 2.0.1 Release and Changelog Rules (Mandatory)

1. Ansible collection changelog handling MUST stay repository-based.
2. NEVER replace Ansible collection changelog files with GitHub Release notes only.
3. Ansible collection releases MUST NOT use `semantic-release`.
4. `semantic-release` remains allowed for non-collection repositories only.
5. If a repository has `galaxy.yml` and collection structure such as `roles/`, `plugins/`, or `playbooks/`,
   treat it as an Ansible Collection repository.
6. Shared release workflow logic belongs in `shared-assets-lit` and is rendered into local collection workflows.
7. Use `antsibull-changelog` for collection changelogs:
   1. fragments live under `changelogs/fragments/`,
   2. generated changelog metadata lives in `changelogs/changelog.yaml`,
   3. generated release notes live in `CHANGELOG.rst`.
8. Every user-visible feature, fix, deprecation, removal, security fix, or known issue MUST add a fragment under
   `changelogs/fragments/<meaningful-name>.yml`.
9. Normal feature/fix PRs MUST NOT manually edit generated changelog files:
   1. `changelogs/changelog.yaml`,
   2. `CHANGELOG.rst`,
   3. legacy `CHANGELOG.md` files where they still exist.
10. Generated changelog files and `galaxy.yml` version bumps are release-PR changes only.
11. Release preparation MUST happen on `release/vX.Y.Z` branches and open a PR into `main`.
12. The release preparation workflow MAY automatically create that PR after a push to `main` when unreleased
    changelog fragments exist.
13. Publishing happens only after the release PR is merged into `main`.
14. No workflow or agent may push release commits directly to `main`.
15. After a release is published from `main`, release-generated files MUST be synced back to `develop` with a
    `backsync/release-vX.Y.Z-to-develop` PR before any new `develop` to `main` promotion.
16. A `develop` to `main` promotion MUST only be opened when `main` is an ancestor of `develop`.
17. GitHub Release notes are an additional publishing surface; they MUST be generated from or aligned with the
   repository changelog, not used as the only changelog.
18. GitHub repository settings, branch protection, required checks, workflow permissions, labels, environments,
    secrets, and release-bot permissions MUST be changed only through `github-management-lit`.

## 2.1 Production Review Standard (Community, Red Hat, Efficiency)

Use this standard when reviewing, creating, or changing collection content. Treat it as the baseline audit prompt for
production readiness, Ansible Galaxy readiness, and Red Hat Ansible Automation Platform readiness.

### 2.1.1 Collection Structure and Metadata

1. Verify correct collection layout and naming under the repository root.
2. Keep `galaxy.yml` complete and accurate: namespace, name, version, README, description, repository, authors,
   license, tags, dependencies, and `build_ignore`.
3. Keep `meta/runtime.yml` aligned with the supported Ansible range.
4. Keep README, Ansible collection changelog files, examples, role docs, and licensing suitable for publication.
5. Ensure collection dependencies are declared once in `galaxy.yml` unless this guide documents an overlay exception.

### 2.1.2 Ansible Community Best Practices

1. Roles and playbooks MUST be idempotent.
2. Use FQCNs for modules and plugins.
3. Prefer purpose-built modules over `ansible.builtin.command` or `ansible.builtin.shell`.
4. When command or shell tasks are justified, define precise `changed_when` and `failed_when` behavior.
5. Support check mode and diff mode where the underlying operation can do so safely.
6. Keep task names specific, variables role-prefixed, defaults clear, and handlers explicit.
7. Avoid hardcoded hosts, users, credentials, private URLs, site-specific paths, and environment-specific values.
8. Prefer structured module parameters and filters over ad hoc string parsing.

### 2.1.3 Red Hat and Enterprise Readiness

1. Content SHOULD run predictably in Red Hat Ansible Automation Platform and execution environments.
2. Avoid dependencies that cannot be resolved in the repository's default public CI/runtime path.
3. Keep entitlement-gated dependencies out of collection metadata and document the consumer/workspace overlay instead.
4. Do not require controller credentials, Red Hat credentials, or private infrastructure for public lint and unit gates.
5. Document supported platforms, required privileges, external services, and operational boundaries.
6. Keep examples realistic for controller-based automation and CI/CD use.

### 2.1.4 Testing and Quality Gates

1. `ansible-lint --profile production .` SHOULD pass, or repository-specific devtools lint MUST pass with documented
   equivalent strictness.
2. `ansible-test sanity --docker` SHOULD pass for custom modules/plugins and collection packaging concerns.
3. Unit tests SHOULD cover custom modules, plugins, filters, and module_utils helpers.
4. Integration tests SHOULD cover real behavior, failure cases, idempotency, check mode, and upgrade paths.
5. Molecule scenarios SHOULD cover role behavior with converge, idempotence, and verify.
6. CI SHOULD run lint, sanity, unit, integration, package build, and smoke install where practical.
7. For PR or CI fixes, reproduce the failing gate locally first and do not rely on GitHub Actions as the first
   end-to-end verifier. Run the repository devtools gates from the repo root before finalizing whenever the
   needed runtime is available. Docker or Podman is sufficient for the default public gates; protected or heavy
   Incus scenarios additionally require an accessible Incus daemon and suitable images.

Required local PR gates for collection changes, when the scripts exist:

```bash
bash scripts/devtools-ansible-lint.sh
bash scripts/devtools-molecule.sh
bash scripts/devtools-collection-smoke.sh
```

Recommended commands when applicable:

```bash
ansible-lint --profile production .
ansible-test sanity --docker
ansible-test units --docker
ansible-test integration --docker
ansible-galaxy collection build .
ansible-galaxy collection install ./<built-artifact>.tar.gz --force
```

### 2.1.5 Code Efficiency and Maintainability

1. Avoid repeated expensive lookups, package queries, fact gathering, API calls, and templating loops.
2. Disable or scope fact gathering when facts are not needed.
3. Cache reusable data with registered variables or facts when that is clearer and cheaper.
4. Use efficient loops, filters, pagination, retries, timeouts, and backoff for API-driven roles.
5. Put repeated Python logic in `module_utils` and repeated role logic in focused task files or roles.
6. Keep module argument specs explicit and return values predictable.
7. Keep YAML readable, sorted where the repo already sorts, and free of duplicated blocks that should be shared.

### 2.1.6 Security Review

1. No secrets, tokens, passwords, keys, private URLs, or sensitive inventory values may be committed.
2. Use `no_log: true` for tasks handling sensitive values, while still keeping debuggability where safe.
3. Quote shell inputs and avoid command injection risks.
4. Do not use unsafe `eval`, `exec`, or template expansion patterns.
5. Validate TLS certificates by default. Any opt-out MUST be explicit, documented, and narrowly scoped.
6. Apply least-privilege defaults for users, files, services, API tokens, and controller objects.

### 2.1.7 Review Output Format

When asked for a review, report findings in this order:

1. Executive summary: production-ready, nearly ready, or not ready.
2. Critical findings: deployment breakers, security risks, or publication blockers.
3. Major findings: correctness, idempotency, compatibility, maintainability, or testing gaps.
4. Minor findings: style, naming, documentation, or polish.
5. Efficiency improvements.
6. Security review.
7. Testing gaps.
8. Recommended fix plan.

For each finding, include severity, file and line, why it matters, recommended fix, and example corrected code when useful.

## 2.2 Collection Dependency Management (Mandatory)

1. Collection dependency source of truth is `galaxy.yml` `dependencies`.
2. When role code starts using modules/plugins from another collection, you MUST add that collection to
   `galaxy.yml` immediately.
3. Collection dependency versions MUST be maintained in `galaxy.yml`; do not duplicate version ownership in
   `collections/requirements.yml`.
4. `galaxy.yml` dependencies MUST stay installable in the repository's default public CI/runtime path.
5. Entitlement-gated dependencies (for example Red Hat Automation Hub-only collections) MUST NOT be declared in
   collection `galaxy.yml`; manage them in consumer/workspace overlay requirements instead.
6. If `collections/requirements.yml` exists, it is an overlay input only (workspace/runtime packaging). It MUST
   NOT become the canonical source of versions for dependencies already declared in `galaxy.yml`.
7. Renovate in collection repos SHOULD track `galaxy.yml` dependencies only; requirements-file managers SHOULD be
   limited to documented overlay-only exceptions.
8. If dependency update policy differs per dependency (for example lifecycle-managed collections), encode that as
   targeted Renovate `packageRules` while keeping version ownership in `galaxy.yml`.

## 2.3 Package Version Management (Mandatory)

1. Repository-owned package/tool dependency versions MUST be fixed to explicit versions wherever the repository is
   the source of truth for that version.
2. Do not introduce open-ended or floating version ranges such as `>=`, `<=`, `~=`, `^`, or `latest` unless the
   repository already requires that pattern or the user explicitly asks for it.
3. When a package version is maintained outside `galaxy.yml` (for example in `requirements.txt`,
   `.pre-commit-config.yaml`, `package.json`, or tool-specific config), Renovate SHOULD manage that version.
4. When adding a new repo-managed package version, you SHOULD also add or confirm Renovate coverage for that file
   and dependency.
5. Do not create parallel version ownership for the same dependency across multiple files unless the repository
   explicitly documents that split.

## 2.4 Ansible Collection Renovate and Release Policy

For Lightning IT Ansible collection repositories, follow the shared Renovate and release model.

Do not hand-maintain generic Renovate policy in individual collection repositories. Generic Renovate rules must be
maintained in `lightning-it/shared-assets-lit` and rendered into each repository's local `renovate.json`.

Collection repositories may only define repository-specific Renovate overrides, such as:

- temporary version pins
- compatibility constraints
- collection-specific package rules
- local custom managers that are not reusable

The standard branch and release model is:

- `develop` is the automated integration branch.
- Renovate targets `develop`.
- Safe patch, minor, pin, and digest updates may auto-merge into `develop` after required CI passes.
- Major updates require manual approval.
- `main` is the stable release branch.
- Promotion from `develop` to `main` must happen through a pull request.
- Promotion pull requests must remain a human-visible manual merge checkpoint after required checks pass.
- Do not direct-push from `develop` to `main`.
- Collection release PRs are created automatically from `release/vX.Y.Z` branches after `main` receives unreleased
  changelog fragments.
- Release PRs target `main` and must pass required checks before merge.

Automation safety requirements:

- Protected branches must require pull request review.
- Only trusted Renovate PRs may be auto-approved by collection automation.
- A trusted Renovate PR must have `renovate[bot]` as both trigger actor and PR author, a `renovate/*` source
  branch, `develop` as the base branch, and both `renovate` and `dependencies` labels.
- Human, external contributor, and develop-to-main promotion PRs must not be auto-approved or auto-merged by
  collection automation.
- Do not use `pull_request_target` for Renovate approval or merge automation.

## 3. Role Variable Naming and Mapping Rules

### 3.1 Role-Prefixed Variables (Mandatory)

1. Variables defined and owned by a role MUST use that role prefix in snake_case.
2. Format: `<role>_<name>`.
3. Examples:
   1. `selinux_state`, `selinux_policy`
   2. `keycloak_config_skip_apply`, `keycloak_config_tg_dir`
4. You MUST NOT bypass variable naming rules with lint suppressions (for example `# noqa var-naming`).

### 3.2 Secrets Variable Naming (Mandatory)

Secret and Vault-related variables MUST also be role-prefixed.

Required pattern (adapt per role):

1. `<role>_use_vault`
2. `<role>_vault_addr`
3. `<role>_vault_token`
4. `<role>_vault_role_id`
5. `<role>_vault_secret_id`
6. `<role>_vault_kv_mount`
7. `<role>_vault_kv_path`

Example:

```yaml
myrole_use_vault: true
myrole_vault_addr: "{{ vault_address | default('') }}"
myrole_vault_token: "{{ vault_token | default('', true) }}"
```

### 3.3 Canonical Mapping Rule (No Semantic Renaming)

This rule is about naming and mapping only. It is NOT a mandate to refactor all existing code at once.

1. If a value originates from another role/component, defaults MUST map from the source variable name.
2. You MUST keep one canonical semantic variable name for a setting.
3. You MUST NOT introduce secondary aliases that rebrand the same setting.

Bad:

```yaml
myrole_bootstrap_bucket: "{{ myrole_config_bucket }}"
myrole_config_bucket: "{{ myrole_bootstrap_bucket }}"
```

Good:

```yaml
myrole_bucket: "{{ myrole_bucket | default('vault-bucket', true) }}"
myrole_bucket_effective: "{{ myrole_bucket | default(otherrole_bucket, true) }}"
```

For cross-role inputs, preserve producer naming and avoid translation layers.

```yaml
myrole_api_url_effective: "{{ myrole_api_url | default(minio_deploy_api_url_effective, true) }}"
```

### 3.4 Role Type Naming: `_config` vs `_cac` (Mandatory)

1. Use `<role>_config` for host-local/service-local configuration concerns:
   1. local files/templates
   2. local service/unit/runtime settings
   3. config materialization on managed hosts
2. Use `<role>_cac` for configuration-as-code object orchestration:
   1. API-driven object management (for example AAP objects)
   2. declarative object sync/reconciliation flows
   3. composition of multiple object tasksets
3. If both patterns are needed, they MUST be split into separate roles (`*_config` and `*_cac`).
4. Feature role naming for CaC MUST use the suffix `_cac` (example: `aap_cac`).
5. In `*_cac` roles, taskset entrypoint files MUST use the `cac_` prefix:
   1. valid: `cac_11_gateway_organizations.yml`
   2. invalid for tasksets: `playbook_05_gateway_organizations.yml`
6. Helper/internal tasks in `*_cac` roles MUST NOT use the `cac_` prefix
   (example: `create_authentication_token.yml`, `delete_authentication_token.yml`).

## 4. Role Structure and Prechecks

### 4.0 Role Responsibility Boundaries

1. Keep operating-system preparation in the operating-system collection:
   1. users and groups
   2. sudoers policy
   3. packages and repositories
   4. RHSM registration
   5. Podman installation and rootless storage
   6. generic Ansible remote temporary directories
2. Application roles MUST consume prepared OS state and validate it, not create
   or repair it. For example, AAP roles may validate the `aap` install user and
   required commands, but user creation belongs to `lit.rhel.users`.
3. Artifact discovery, download, checksum verification, and staging belong in a
   dedicated prepare/artifacts role. Deploy roles SHOULD consume final prepared
   paths and avoid parallel fallback discovery logic.
4. Avoid repeated near-identical task branches for source variants such as
   `url`, `local`, and `remote`. Resolve source-specific values once, build one
   normalized item, and pass that normalized item to the generic implementation.
5. Compatibility wrappers for misspelled role names or legacy aliases are
   temporary. Remove them once no maintained playbook, runbook, Molecule
   scenario, or documentation references them.

### 4.1 Required Role Layout

Roles SHOULD follow:

```text
roles/<role_name>/
  README.md
  defaults/main.yml
  tasks/main.yml
  tasks/assert.yml
  meta/main.yml
  handlers/main.yml        # optional
  templates/               # optional
  files/                   # optional
```

Role directory names MUST be snake_case.

### 4.2 Precheck Entrypoint

1. `tasks/assert.yml` MUST exist for new or actively maintained roles.
2. `tasks/main.yml` MUST import `assert.yml` first with `tags: always`.
3. `assert.yml` MUST be side-effect free:
   1. validate input types/required variables/invariants
   2. no system mutation
   3. no Vault/API calls

Required pattern:

```yaml
---
- name: Prechecks
  ansible.builtin.import_tasks: assert.yml
  tags: always
```

### 4.3 Precheck Responsibility Boundaries (Critical)

1. `assert.yml` for a role MUST validate that role's interface, not another role's internals.
2. In `roles/<role>/tasks/assert.yml`, assertions SHOULD target `<role>_*` variables only.
3. Non-deploy roles (`*_ops`, `*_validate`, `*_config`, `*_bootstrap`, `*_backup_restore`) MUST NOT
   assert raw `*_deploy_*` variables directly.
4. If a role needs values originating from another role, map them in `defaults/main.yml` into role-prefixed
   runtime vars, then assert those mapped vars.
5. `assert.yml` in one role MUST NOT import another role's `tasks/assert.yml` unless explicitly required by
   repository design and documented in that role README.
6. Action-based roles MUST use action-scoped assertions:
   1. `*_action == 'none'`: validate only action enum and basic booleans.
   2. `restart/reload`: validate service or pod identifiers.
   3. `status`: validate health/status endpoint vars.
   4. `upgrade`: validate target image/package inputs.

Bad (cross-role coupling in role assert):

```yaml
- name: Ensure nginx_ops variables are valid
  ansible.builtin.assert:
    that:
      - nginx_deploy_systemd_unit_name | length > 0
      - nginx_deploy_pod_name | length > 0
```

Good (mapped in defaults, asserted in role namespace):

```yaml
# defaults/main.yml
nginx_ops_systemd_unit_name: "{{ nginx_deploy_systemd_unit_name | default('', true) }}"
nginx_ops_pod_name: "{{ nginx_deploy_pod_name | default('', true) }}"

# tasks/assert.yml
- name: Ensure restart variables are set for systemd mode
  ansible.builtin.assert:
    that:
      - nginx_ops_systemd_unit_name | default('', true) | trim | length > 0
  when:
    - nginx_ops_action == 'restart'
    - nginx_ops_manage_systemd | bool
```

7. Foundational/helper roles MUST only assert variables required for their own task scope. Do not enforce
   endpoint/runtime vars in foundational prechecks if the role only resolves credentials.

### 4.4 FQCN Modules

1. Tasks MUST use FQCNs (`ansible.builtin.*` or collection FQCNs).
2. Example:

```yaml
- name: Create config directory
  ansible.builtin.file:
    path: /srv/example
    state: directory
    mode: '0750'
```

## 5. Defaults and Derivations

1. Static defaults and pure derivations SHOULD live in `defaults/main.yml`.
2. Use derived variables such as `*_effective`, `*_enabled`, `*_manage_*` where helpful.
3. Do not use `set_fact` for values that can be computed in defaults.
4. Runtime discovery from remote state, commands, APIs, or Vault MUST stay in tasks, not defaults.

## 5.1 Public Reusability and Environment Neutrality

1. Roles MUST be publicly reusable and environment-agnostic by default.
2. Role code (`defaults/`, `tasks/`, `templates/`, `README.md`) MUST NOT hardcode environment-specific values.
3. Environment-specific variables are NOT permitted in role defaults, including:
   1. internal domains
   2. inventory hostnames or FQDNs tied to one environment
   3. environment-only URLs, tokens, or credentials
4. Use neutral defaults and placeholders, then inject real values from inventory/group vars/playbooks.
5. If a role needs an address/domain, expose a generic role variable and keep the default generic or empty.
6. Environment specialization belongs in consumer inventory/playbooks, not reusable role defaults.

Bad:

```yaml
myrole_server_name: "vault.prd.dmz.corp.l-it.io"
myrole_api_url: "https://vault01.prd.dmz.corp.l-it.io:8200"
```

Good:

```yaml
myrole_server_name: "vault.example.com"
myrole_api_url: ""
myrole_api_url_effective: >-
  {{
    myrole_api_url
    if (myrole_api_url | default('', true) | length > 0)
    else ('https://' ~ myrole_server_name)
  }}
```

## 6. Idempotency and Check Mode

1. Prefer idempotent modules over `shell`/`command`.
2. If `shell`/`command` is required, you MUST control idempotency with at least one:
   1. `creates` or `removes`
   2. `changed_when` and `failed_when`
   3. explicit state pre-check + conditional apply
3. Read-only tasks MUST set `changed_when: false`.
4. Check mode behavior MUST be explicit for mutating tasks that cannot run in check mode.

Example:

```yaml
- name: Read current state
  ansible.builtin.command: mytool status
  register: myrole_status
  changed_when: false

- name: Apply state when needed
  ansible.builtin.command: mytool apply
  when:
    - not ansible_check_mode
    - myrole_status.stdout != 'ready'
  changed_when: true
```

## 7. Secrets and Logging Policy

1. Secrets MUST NOT be printed in debug output.
2. Tasks handling secrets MUST set `no_log: true`.
3. Vault responses and secret payloads MUST NOT be logged.
4. Secret values MUST NOT be written to artifacts, generated docs, or committed test output.
5. If failure output can expose secrets, task-level `no_log: true` MUST still be used.

### 7.1 Secret Source of Truth and Password Lifecycle (Mandatory)

1. Each environment MUST have exactly one declared source of truth for runtime passwords:
   1. external secret manager (for example HashiCorp Vault), or
   2. inventory variables (preferably encrypted via Ansible Vault).
2. Password generation is allowed only when the value can be persisted immediately to the selected source of truth.
3. Generating a password without persistence is NOT allowed for deployment flows.
4. If a required password is missing and cannot be persisted, the role/play MUST fail fast.
5. Secret resolution order MUST be deterministic and documented:
   1. explicit role input variable,
   2. secret manager read (when configured),
   3. inventory-provided value,
   4. generate and persist to configured backend,
   5. fail if none of the above is possible.
6. Rotation MUST be explicit (for example action-driven), and MUST update source of truth first, then apply change to the target service.
7. Idempotency requirement: repeated runs with unchanged inputs MUST resolve the same effective secret values.
8. Local file cache may be used only as an explicitly documented lab/offline fallback and MUST NOT replace a declared production source of truth.

Example:

```yaml
- name: Read credentials from Vault
  community.hashi_vault.vault_kv2_get:
    url: "{{ myrole_vault_addr }}"
    token: "{{ myrole_vault_token }}"
    engine_mount_point: "{{ myrole_vault_kv_mount }}"
    path: "{{ myrole_vault_kv_path }}"
  register: myrole_secret
  no_log: true
```

## 8. Molecule Standards

### 8.1 Location

Molecule scenarios MUST live at repository root under `molecule/`.

### 8.2 Naming (Match This Repo)

1. Existing light scenarios use kebab-case with `-basic` suffix:
   1. `minio-deploy-basic`, `nginx-config-basic`, `vault-basic`
2. Do NOT rename existing scenarios.
3. New heavy scenarios MUST end in `_heavy` so `scripts/devtools-molecule.sh` skips them.
4. Recommended new heavy pattern: `<role-kebab>-<purpose>_heavy`.

### 8.3 Execution Behavior

1. `scripts/devtools-molecule.sh` runs all root scenarios except names ending in `_heavy`.
2. Scenarios with `.molecule-mode` set to `protected-incus` are skipped unless
   `MOLECULE_RUN_PROTECTED=true` is set and the devtools container has the `incus` CLI.
3. A single scenario is run with:

```bash
scripts/devtools-molecule.sh minio-config-basic
```

4. Keep light scenarios runnable in devtools and pre-commit without external infrastructure.

### 8.4 Required Basic Scenario Coverage Per Role (Mandatory)

1. Every role under `roles/` MUST have a corresponding light Molecule scenario that validates the role.
2. Required naming for new role scenarios: `<role-name-with-dashes>-basic`.
3. If an existing role uses a legacy scenario name, do not rename it automatically, but you MUST ensure a
   working light scenario exists for that role.
4. Missing scenario coverage for any role is a blocker for completion.
5. Stub scenarios are allowed only when runtime dependencies are unavailable, but the scenario MUST still run
   through Molecule test sequence successfully.

### 8.5 Scenario Quality Gate (Mandatory)

For each new or changed role, and for any newly added scenario:

1. Run the role scenario directly with `scripts/devtools-molecule.sh <scenario>`.
2. The scenario MUST pass converge, idempotence, and verify (no failed tasks).
3. `ansible-lint` MUST pass with zero fatal violations for the repository and changed scenario files.
4. You MUST fix lint issues in scenario files (for example var naming or FQCN issues) instead of suppressing them.

## 9. Collection Packaging and `build_ignore`

1. Keep `build_ignore` minimal and justified by real repository artifacts.
2. This repo already ignores common paths (for example `.git`, `.github`, `.molecule`, `.ansible`, `infra`).
3. Recommended additions, when relevant and not already present:
   1. `molecule/` (root scenarios should not ship in release tarballs)
   2. `.venv/`, `.tox/`
   3. `.cache/`, `.pytest_cache/`
   4. `.ansible/`
   5. `dist/`, `build/`

## 10. Role README Standard

Each role `README.md` MUST use these section headers in this order:

1. `## Requirements`
2. `## Variables`
3. `## Dependencies`
4. `## Example Playbook`
5. `## License`
6. `## Author`

Variables section SHOULD point to `defaults/main.yml` and highlight key inputs.

## 11. Definition of Done

Before finalizing, confirm all items below:

1. `pre-commit run --all-files` passes, or failures are explicitly explained.
2. Local collection PR gates pass before using GitHub Actions as verification, whenever the scripts exist and
   the needed runtime is available:
   1. `bash scripts/devtools-ansible-lint.sh`
   2. `bash scripts/devtools-molecule.sh`
   3. `bash scripts/devtools-collection-smoke.sh`
3. If a local gate is skipped, the final response names the missing runtime or concrete blocker, such as no
   Docker/Podman socket or protected Incus requirements.
4. Documentation is updated for changed role interfaces.
5. No CI, workflow, Renovate, or release-automation config changes were made unless requested.
6. Role prechecks are action-scoped and role-scoped:
   1. no cross-role raw var assertions in `assert.yml`
   2. no duplicate copy-paste assert blocks
   3. required foreign inputs mapped in `defaults/main.yml` with role prefix
