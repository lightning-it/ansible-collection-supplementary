# Agent Specification – Lightning IT Ansible Collections (lit.*)

You are an AI coding agent working on Lightning IT's Ansible collections under the `lit.*` namespace.
Your main job is to **create and evolve Ansible roles, Molecule tests, and documentation** in a way that is:

- consistent across all `ansible-collection-*` repositories,
- compatible with ansible-lint, pre-commit, and Molecule,
- and friendly to semantic-release and Ansible Galaxy.

The primary collections are:

- `ansible-collection-foundational` → `lit.foundational`
- `ansible-collection-rhel`         → `lit.rhel`
- `ansible-collection-supplementary`→ `lit.supplementary`
- `ansible-collection-ocp`          → `lit.ocp`

Always assume the repo you are in follows the pattern:

- repo name: `ansible-collection-<name>`
- collection FQCN: `lit.<name>`

---

## 0. Version policy (important)

- The org-wide policy is to keep **ansible-core on 2.18.x** across collections and shared CI templates.
- Do not introduce content that requires a newer ansible-core major version unless explicitly instructed.
- Prefer `ansible.builtin.*` modules; use other collections only when required.

If you update workflow variables like `ANSIBLE_CORE_VERSION`, keep them consistent with the policy.

---

## 1. Repository and collection conventions

### 1.1 Deriving the collection name

Never hardcode the collection name if you can derive it.

- Repository name: `ansible-collection-rhel` → collection name `rhel` → `lit.rhel`
- Repository name: `ansible-collection-supplementary` → `lit.supplementary`

Where helpful in scripts, use the pattern:

- `COLLECTION_NAMESPACE` default `lit`
- `COLLECTION_NAME` derived from `$GITHUB_REPOSITORY` or `basename "$PWD"` by stripping the `ansible-collection-` prefix.

Example bash snippet:

```bash
ns="${COLLECTION_NAMESPACE:-lit}"
repo_basename="${GITHUB_REPOSITORY##*/}"
name="${repo_basename#ansible-collection-}"
```

### 1.2 Collection metadata (`galaxy.yml`)

- `namespace: lit`
- `name: <collection-name>` (e.g. `rhel`, `foundational`, `supplementary`, `ocp`)
- `license`: `GPL-3.0-only`
- `repository`, `bugs`, `homepage` should point to the GitHub repo.

- `build_ignore` must exclude CI/dev artefacts:

```yaml
build_ignore:
  - node_modules
  - vagrant
  - .git
  - .github
  - .gitignore
  - .molecule
  - ansible_collections
  - infra
  - "*.terraform*"
  - "*.tar.gz"
```

- Add collection-specific tags that reflect the domain, and **always include `modulix`**:
  - `lit.foundational`: `modulix`, `platform`, `automation`
  - `lit.rhel`: `modulix`, `rhel`, `linux`, `hardening`, `baseline`
  - `lit.supplementary`: `modulix`, `keycloak`, `terraform`, `security`, `integration`
  - `lit.ocp`: `modulix`, `openshift`, `ocp`, `kubernetes`, `day2`

### 1.3 Collection dependencies

Collections may depend on each other via `galaxy.yml` `dependencies:`.

- `lit.foundational` is the base collection.
- `lit.rhel`, `lit.supplementary`, `lit.ocp` may depend on `lit.foundational`.

When adding a dependency, always use an explicit version range consistent with your org conventions.

### 1.4 Node / semantic-release (`package.json`)

Each collection repo has a `package.json` like:

```json
{
  "name": "ansible-collection-<name>",
  "version": "0.0.0",
  "private": true,
  "description": "...",
  "repository": {
    "type": "git",
    "url": "https://github.com/lightning-it/ansible-collection-<name>.git"
  },
  "bugs": {
    "url": "https://github.com/lightning-it/ansible-collection-<name>/issues"
  },
  "homepage": "https://github.com/lightning-it/ansible-collection-<name>#readme",
  "license": "GPL-3.0-only",
  "devDependencies": {
    "semantic-release": "^25.0.2",
    "@semantic-release/changelog": "^6.0.3",
    "@semantic-release/commit-analyzer": "^13.0.1",
    "@semantic-release/git": "^10.0.1",
    "@semantic-release/github": "^9.2.6",
    "@semantic-release/release-notes-generator": "^14.1.0",
    "conventional-changelog-conventionalcommits": "^7.0.2"
  }
}
```

**Never** change semantic-release configuration unless explicitly asked.

---

## 2. Role layout and style

When the user asks you to create a new role `lit.<collection>.<role_name>`, you must:

1. Create folder structure:

```text
roles/
  <role_name>/
    README.md
    defaults/
      main.yml
    tasks/
      main.yml
    meta/
      main.yml
    # optionally: handlers/, vars/, templates/, files/...
```

> Note: Do **not** place Molecule scenarios under the role directory.  
> All Molecule scenarios live at the collection root under `molecule/`.

2. Use **idempotent** Ansible code and pass ansible-lint by default.

3. Prefer standard modules:

- `ansible.builtin.*` for core,
- collection modules only when needed (e.g. `community.general.*`, `ansible.posix.*`).

4. Naming rules:

- Role directory names are **snake_case** (underscores), e.g. `manage_esxi`, `gitops_bootstrap`.
- Avoid hyphens in role directory names.
- Molecule scenario directories may be kebab-case, but keep them predictable (see section 3).

5. Place configuration variables in `defaults/main.yml` with:

- clear names prefixed by the role:
  - `rhel_selinux_state`, `rhel_selinux_policy` for `lit.rhel.selinux`
  - `keycloak_config_*` for `lit.supplementary.keycloak_config`
- sensible defaults that are safe for labs/dev by default.

6. `meta/main.yml` must include:

```yaml
---
galaxy_info:
  role_name: <role_name>
  namespace: lit
  author: Lightning IT
  description: ...
  company: Lightning IT
  license: GPL-3.0-only
  min_ansible_version: "2.18"

  platforms:
    - name: EL
      versions:
        - "9"

  galaxy_tags:
    - modulix
    - automation
    # add role-specific tags (rhel/ocp/security/...)

dependencies: []
```

7. `roles/<role_name>/README.md` must:

- briefly describe the role,
- document variables (from `defaults/main.yml`),
- include at least one usage example:

```yaml
- name: Example usage
  hosts: rhel
  become: true

  roles:
    - role: lit.rhel.selinux
      vars:
        rhel_selinux_state: enforcing
```

---

## 3. Testing: Molecule, heavy vs. light scenarios

Each role should have Molecule coverage. **All Molecule scenarios live at the collection root** in `molecule/`, not inside `roles/`.

### 3.1 Light scenarios

- Stored under `molecule/<scenario_name>/` at the **collection root**.
- Must be runnable in CI and via:

```bash
bash scripts/devtools-molecule.sh
```

- Naming convention:

  - Prefer: `<role-name>-basic` for light scenarios (kebab-case + `-basic`)
  - Example:
    - role: `manage_esxi` → scenario dir: `molecule/manage-esxi-basic/`
    - role: `gitops_bootstrap` → scenario dir: `molecule/gitops-bootstrap-basic/`

- The scenario should:
  - run the role,
  - verify at least one assertion (even if it’s a stub),
  - avoid requiring real infrastructure.

### 3.2 Heavy scenarios

- For Vagrant/RHEL, real services, etc.
- Scenario names end with `_heavy`, e.g.:
  - `selinux_rhel9_heavy`
  - `firewalld_rhel9_heavy`

- Heavy scenarios are **not** run by default in pre-commit or the light CI job.

When you generate Molecule config for a heavy scenario, prefer:

```yaml
driver:
  name: delegated

provisioner:
  name: ansible
  inventory:
    host_vars:
      rhel9_target:
        ansible_host: "{{ lookup('env', 'RHEL9_SSH_HOST') | default('127.0.0.1') }}"
        ansible_port: "{{ (lookup('env', 'RHEL9_SSH_PORT') | default('22')) | int }}"
        ansible_user: "{{ lookup('env', 'RHEL9_SSH_USER') | default('vagrant') }}"
        ansible_ssh_private_key_file: "{{ lookup('env', 'RHEL9_SSH_KEY') | default('') }}"
```

---

## 4. Execution Environment (EE) policy: use `ee-wunder-ansible-ubi9`

All collection development and playbook runs should default to the **runtime EE**:

- **`quay.io/l-it/ee-wunder-ansible-ubi9:<tag>`** (preferred for distribution)
- or `ee-wunder-ansible-ubi9:local` for local iteration

Do **not** reference the devtools container as the default execution image for collections and ansible-navigator runs.
The devtools container may still exist for specialized CI tooling, but the standard execution environment is:

- `ee-wunder-ansible-ubi9`

### 4.1 ansible-navigator expectations

- The EE should support:
  - `ansible`, `ansible-galaxy`, `ansible-runner`
  - `/runner` layout (AAP-compatible)
  - `linux/amd64` and `linux/arm64` builds (multi-arch)

Example `ansible-navigator.yml` snippet (reference only):

```yaml
ansible-navigator:
  execution-environment:
    enabled: true
    container-engine: docker
    image: quay.io/l-it/ee-wunder-ansible-ubi9:vX.Y.Z
    pull:
      policy: tag
  mode: stdout
  playbook-artifact:
    enable: false
```

---

## 5. Devtools integration

There may still be helper scripts, but tooling should be compatible with running inside the EE.

If scripts wrap a container runner, the default image for running Ansible-related actions should be `ee-wunder-ansible-ubi9` unless the task explicitly needs dev-only tooling.

---

## 6. Secrets & Vault optionality (must-follow pattern)

Many roles will eventually run “Vault-first”, but must also run **100% without Vault** if configured that way.

### 6.1 Goals

- Vault is **optional**: role runs without Vault when disabled/unavailable.
- No hard Vault dependency during variable loading.
- Clear failure messages if secrets are missing in non-Vault mode.

### 6.2 Rules (do this, always)

1. **Never put Vault lookups in `defaults/main.yml` or `vars/main.yml`.**  
   This is critical: Ansible may evaluate these earlier than expected.

2. Add an explicit flag and compute an effective value:

```yaml
# defaults/main.yml
use_vault: false              # safe default: runs without Vault
use_vault_mode: "explicit"    # optional: explicit|auto

vault_addr: ""
vault_token: ""
```

```yaml
# tasks/main.yml (or tasks/preflight.yml)
- name: Determine whether Vault is effectively enabled
  ansible.builtin.set_fact:
    use_vault_effective: >-
      {{
        (use_vault | bool) or
        (
          (use_vault_mode | default('explicit')) == 'auto'
          and (vault_addr | default('') | length > 0)
          and (vault_token | default('') | length > 0)
        )
      }}
```

3. Keep Vault logic in a dedicated task file and include it conditionally:

```yaml
- name: Load secrets from Vault (only if enabled)
  ansible.builtin.include_tasks: vault.yml
  when: use_vault_effective | bool
```

4. Provide a non-Vault fallback that uses vars or environment variables:

```yaml
# defaults/main.yml
myrole_admin_password: "{{ lookup('env', 'MYROLE_ADMIN_PASSWORD') | default('', true) }}"
```

```yaml
# tasks/secrets.yml
- name: Assert required secrets are provided when Vault is disabled
  ansible.builtin.assert:
    that:
      - myrole_admin_password is defined
      - myrole_admin_password | length > 0
    fail_msg: "myrole_admin_password must be provided when use_vault=false"
  when: not (use_vault_effective | bool)
```

### 6.3 Documentation requirement

Every role that supports Vault must document:

- `use_vault` / `use_vault_mode`
- required Vault connection vars (`vault_addr`, auth vars)
- required non-Vault vars (what must be set when Vault is off)

---

## 7. CI and semantic-release

You must write CI-ready Ansible code and tests:

- Linting is done via GitHub Actions and pre-commit with:
  - `yamllint`,
  - `ansible-lint`,
  - Molecule (for light scenarios),
  - `actionlint` for workflows,
  - `renovate-config-validator` for `renovate.json` where present.

- Release is done via `semantic-release`:
  - Do not modify CI workflows or `.releaserc` unless asked.
  - Assume conventional commits (`feat:`, `fix:`, `chore:`, `docs:`).
  - Do not change versions manually in `galaxy.yml` or `package.json` unless explicitly instructed.

---

## 8. How to respond to user requests (expected outputs)

When the user asks you to:

### “Create a new role X in this collection”
You must:

- create `roles/X/` with `defaults`, `tasks`, `meta`, `README`,
- add a Molecule scenario `molecule/<x-kebab>-basic/`,
- wire the scenario to run the role and verify at least one assertion.

### “Add a heavy Molecule scenario to test on RHEL9 via Vagrant”
You must:

- create `molecule/<role>_rhel9_heavy/` using delegated driver,
- read SSH details via env vars,
- create a dedicated helper script for that scenario,
- ensure it is **not** run by the light CI job.

### “Make this role usable in another collection”
You must:

- keep role behavior generic,
- do not hardwire repo-local assumptions,
- keep external dependencies explicit and documented.

Always preserve existing patterns and style in the repo you’re working in.
If something is unclear, infer from existing roles and tests rather than introducing a new pattern.
