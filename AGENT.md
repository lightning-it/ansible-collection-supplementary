# Lightning IT Ansible Collection Agent Guide (lit.*)

This file is the single source of truth for creating and evolving roles, Molecule scenarios,
and role documentation in `ansible-collection-*` repositories under the `lit.*` namespace.

Scope: role code, defaults, tasks, Molecule tests, role READMEs, and collection packaging hygiene.

## 0. Compatibility Baseline

1. Content MUST be compatible with `ansible-core` 2.18.x.
2. Content MUST NOT require Ansible major versions newer than 2.x.
3. This repository declares `requires_ansible: ">=2.18.0"` in `meta/runtime.yml`.
4. New changes SHOULD remain compatible with `>=2.18.0` unless explicitly told otherwise.
5. Prefer `ansible.builtin.*` modules; use external collections only when required.

## 1. Mandatory Discovery Before Changes

Before writing or changing role code, you MUST inspect repository reality first:

1. `galaxy.yml` for namespace/name/license/tags/dependencies/build_ignore.
2. `meta/runtime.yml` for collection compatibility.
3. Lint config: `.ansible-lint`, `ansible-lint.yml`, `.yamllint`, `.pre-commit-config.yaml`.
4. Existing role patterns under `roles/` (tasks, defaults, assert entrypoints, naming).
5. Molecule and script behavior under `molecule/` and `scripts/devtools-molecule.sh`.

If generic guidance conflicts with repository behavior, you MUST prefer repository behavior.

## 2. Repository Baseline (This Repo)

1. Repository identity values (namespace, name, license, tags, dependencies) MUST be read from `galaxy.yml`.
2. Do not copy identity metadata from another collection repository.
3. Linting uses 120-character YAML line length:
   1. `.yamllint` max line length 120
   2. `ansible-lint.yml` YAML max line length 120
4. Pre-commit runs devtools-based hooks for `yamllint`, `ansible-lint`, and Molecule light scenarios.

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
2. A single scenario is run with:

```bash
scripts/devtools-molecule.sh minio-config-basic
```

3. Keep light scenarios runnable in devtools and pre-commit without external infrastructure.

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
2. `ansible-lint` passes under repo devtools entrypoints.
3. Molecule light scenarios pass (`scripts/devtools-molecule.sh` or scoped equivalent).
4. Documentation is updated for changed role interfaces.
5. No CI, workflow, Renovate, or semantic-release config changes were made unless requested.
6. Role prechecks are action-scoped and role-scoped:
   1. no cross-role raw var assertions in `assert.yml`
   2. no duplicate copy-paste assert blocks
   3. required foreign inputs mapped in `defaults/main.yml` with role prefix
