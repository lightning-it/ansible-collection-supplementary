# Agent Specification – Lightning IT Ansible Collections

You are an AI coding agent working on Lightning IT's Ansible collections under
the `lit.*` namespace. Your main job is to **create and evolve Ansible roles,
Molecule tests, and documentation** in a way that is:

- consistent across all `ansible-collection-*` repositories,
- compatible with ansible-lint, pre-commit, and Molecule,
- and friendly to semantic-release and Galaxy.

The primary collections are:

- `ansible-collection-foundational` → `lit.foundational`
- `ansible-collection-rhel`         → `lit.rhel`
- `ansible-collection-supplementary`→ `lit.supplementary`
- `ansible-collection-ocp`          → `lit.ocp`

Always assume the repo you are in follows the pattern:

- repo name: `ansible-collection-<name>`
- collection FQCN: `lit.<name>`

---

## 1. Repository and collection conventions

### 1.1 Deriving the collection name

Never hardcode the collection name if you can derive it.

- Repository name: `ansible-collection-rhel` → collection name `rhel` → `lit.rhel`
- Repository name: `ansible-collection-supplementary` → `lit.supplementary`

Where helpful in scripts, use the pattern:

- `COLLECTION_NAMESPACE` default `lit`
- `COLLECTION_NAME` derived from `$GITHUB_REPOSITORY` or `basename "$PWD"` by
  stripping the `ansible-collection-` prefix.

### 1.2 Collection metadata (`galaxy.yml`)

- `namespace: lit`
- `name: <collection-name>` (e.g. `rhel`, `foundational`, `supplementary`, `ocp`)
- `license`: `GPL-2.0-only`
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

- Add collection-specific tags that reflect the domain, e.g.
  - `rhel`, `linux`, `hardening`, `baseline` for `lit.rhel`
  - `keycloak`, `terraform`, `platform`, `security` for `lit.supplementary`
  - `openshift`, `ocp`, `kubernetes`, `platform`, `day2` for `lit.ocp`

### 1.3 Node / semantic-release (`package.json`)

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
  "license": "GPL-2.0-only",
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

When the user asks you to create a new role `lit.<collection>.<role_name>`, you
must:

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
   - `ansible.posix.selinux` etc. when needed.

4. Place configuration variables in `defaults/main.yml` with:

   - clear names prefixed by the role:
     - `rhel_selinux_state`, `rhel_selinux_policy` for `lit.rhel.selinux`
     - `keycloak_config_*` for `lit.supplementary.keycloak_config`
   - sensible defaults that are safe for labs/dev by default.

5. `meta/main.yml` must include:

   ```yaml
   ---
   galaxy_info:
     role_name: <role_name>
     namespace: lit
     author: Lightning IT
     description: ...
     company: Lightning IT
     license: GPL-2.0-only
     min_ansible_version: "2.15"

     platforms:
       - name: EL
         versions:
           - "9"

     galaxy_tags:
       - rhel
       - selinux
       - security
       # etc. per role

   dependencies: []
   ```

6. `roles/<role_name>/README.md` must:

   - briefly describe the role,
   - document variables (pulled from `defaults/main.yml`),
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

Each role should have Molecule coverage. **All Molecule scenarios live at the
collection root** in `molecule/`, not inside `roles/`.

### 3.1 Light scenarios

- Stored under `molecule/<scenario_name>/` at the **collection root**.
- Use `driver: default` or `driver: delegated` + localhost/docker/docker-compose,
  depending on the repo conventions.
- Should be runnable in CI and via:

  ```bash
  bash scripts/devtools-molecule.sh
  ```

- Scenario names: `tf_runner_basic`, `keycloak_config_local`, etc.

### 3.2 Heavy scenarios

- For Vagrant/RHEL, etc. (e.g. RHEL9 VM via Vagrant/QEMU/VirtualBox).
- Scenario names end with `_heavy`, e.g.:
  - `selinux_rhel9_heavy`
  - `rdp_rhel9_heavy`
- Use `driver: delegated` and expect:

  - Vagrant to bring up the VM outside the container,
  - SSH connection details are provided via environment variables that are
    passed into the container (`RHEL9_SSH_HOST`, `RHEL9_SSH_PORT`, etc.).

- Must be runnable via dedicated scripts like:

  ```bash
  scripts/devtools-molecule-selinux-rhel9-heavy.sh
  ```

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

## 4. Devtools integration

There is a shared devtools container: **`wunder-devtools-ee`**.

Wrapper script: `scripts/wunder-devtools-ee.sh`

- It:
  - mounts the repo into `/workspace`,
  - runs tools inside the container,
  - optionally maps the host UID/GID unless `WUNDER_DEVTOOLS_RUN_AS_HOST_UID=0`.

Other helper scripts you may assume exist (or that you may extend):

- `scripts/devtools-collection-prepare.sh`
  - builds and installs the collection into `/tmp/wunder/collections`.
- `scripts/devtools-ansible-lint.sh`
  - builds + installs collection, then runs `ansible-lint`.
- `scripts/devtools-molecule.sh`
  - builds the collection, installs it into `/tmp/wunder/collections`, then
  - runs all non-`*_heavy` Molecule scenarios at the collection root.
- Heavy scripts like:
  - `scripts/devtools-molecule-selinux-rhel9-heavy.sh`
    - start Vagrant VM,
    - export SSH env vars,
    - run `molecule test -s selinux_rhel9_heavy` inside devtools container.

When adding or modifying scripts:

- Respect the pattern:
  - derive `COLLECTION_NAME` from repo name,
  - pass relevant env vars into the container,
  - do **not** hardcode collection names.

---

## 5. CI and semantic-release

You must write CI-ready Ansible code and tests:

- Linting is done via GitHub Actions (Collection CI) and pre-commit with:
  - `ansible-lint`,
  - `yamllint`,
  - Molecule (for light scenarios),
  - `actionlint` for workflows,
  - `renovate-config-validator` for `renovate.json` where present.

- Release is done via `semantic-release`:
  - Do not modify CI workflows or `.releaserc` unless asked.
  - Assume conventional commits (`feat:`, `fix:`, `chore:`, `docs:`).
  - Do not change version numbers manually in `galaxy.yml` or `package.json`
    unless explicitly instructed.

---

## 6. Safety and quality rules

When generating or modifying roles:

1. **Idempotency**: tasks must be idempotent; no unnecessary changes on second run.
2. **No secrets**: do not hardcode passwords, tokens, or secrets.
   - refer to environment variables or vaults where appropriate.
3. **Explicit modules**: avoid `shell`/`command` unless there is no module for it.
   - If you must use `shell`/command, set `changed_when` and `failed_when`.
4. **Pass ansible-lint**:
   - Use proper var naming with role prefix.
   - Provide meta and README.
   - Avoid including roles/tasks from relative paths outside the collection.
5. **Documentation-first**:
   - Any new role must come with:
     - defaults and their doc,
     - at least one example in the role README,
     - optionally a line in the collection `README.md` under “Roles”.

---

## 7. How to respond to user requests

When the user asks you to:

- “create a new role X in this collection”:
  - create `roles/x/` with defaults, tasks, meta, README,
  - add a Molecule scenario (light) under `molecule/` named with `_basic` suffix,
  - optionally suggest a heavy scenario if relevant (e.g. RHEL/VM or OCP cluster).

- “add a Molecule scenario to test this role on RHEL9 via Vagrant”:
  - create `molecule/<role>_rhel9_heavy/` with `driver: default`,
  - assume `vagrant/rhel9/Vagrantfile` exists or propose one,
  - wire it to environment-based SSH host/port/user/key.
  - For roles expected to run on real RHEL (e.g. SELinux, firewalld), add such a
    heavy scenario and a helper script to start the Vagrant VM and pass SSH env
    vars into `wunder-devtools-ee`.

- “update CI to run the example playbook”:
  - integrate `EXAMPLE_PLAYBOOK=playbooks/example.yml` into the existing
    Collection CI GitHub Action,
  - do not create new workflows unless explicitly requested.

- “make this role usable in another collection”:
  - keep role logic generic and avoid hardwired collection-specific assumptions,
  - rely on FQCN `lit.<collection>.<role>` but keep behaviour independent.

Always preserve existing patterns and style in the repo you’re working in.
If something is unclear, infer from existing roles and tests rather than
introducing a new pattern.
