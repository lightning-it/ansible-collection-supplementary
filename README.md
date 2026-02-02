# lit.supplementary

Supplementary Ansible collection for ModuLix / Lightning IT. Currently contains
the `keycloak_config` role to configure existing Keycloak instances (realms,
clients, roles, users, IdPs) via Terraform and the `cloudflared` role to manage
Cloudflare Tunnel connectors.

## Usage

Install directly from the repo/branch:

```bash
ansible-galaxy collection install \
  git+https://github.com/lightning-it/ansible-collection-supplementary.git,ro/role-keycloak
```

Example playbook:

```yaml
- hosts: keycloak
  gather_facts: false
  connection: local

  roles:
    - role: lit.supplementary.keycloak_config
```

## Development

- `galaxy.yml` defines the collection metadata (namespace `lit`, name
  `supplementary`, license `GPL-2.0-only`).
- Canonical role sources live in `roles/`; build with `ansible-galaxy
  collection build`.
- Molecule scenario `keycloak-basic` provisions a local Keycloak container and
  exercises the role with `keycloak_config_skip_apply` set for quick checks.
- Molecule scenario `vault-basic` runs the vault role with a stub terragrunt role
  to validate basics locally.
- Molecule scenario `openvpn-basic` runs the openvpn role without standing up a
  server to validate role wiring and defaults.
- Molecule scenario `cloudflared-basic` runs the cloudflared role with install
  steps disabled to validate role wiring and defaults.
- Molecule scenario `gitlab-runner-basic` runs the gitlab_runner stub role
  (acknowledging experimental status) to keep lint/test coverage green.
  It uses the repo’s roles path to source the role locally.
- Molecule scenario `nexus-basic` runs the nexus stub role (acknowledging
  experimental status) to keep coverage green.
- Molecule scenario `manage-esxi-basic` uses a stub manage_esxi role so tests stay
  green without vCenter/ESXi access.

## Local checks

This repository uses **pre-commit** and a shared devtools container
(`ee-wunder-devtools-ubi9`) to keep linting and runtime tests consistent between
local development and CI.

### 1. Install pre-commit

If you haven’t already:

```bash
pip install pre-commit
pre-commit install
```

This installs the standard `pre-commit` hook for this repo (YAML, Ansible,
Molecule, etc.).

### 2. Run all linters locally

To run all configured linters (YAML, ansible-lint, Molecule keycloak-basic,
openvpn-basic, cloudflared-basic, gitlab-runner-basic, nexus-basic, manage-esxi-basic,
vault-basic, GitHub Actions lint, Renovate config validation):

```bash
pre-commit run --all-files
```

This will:

- run `yamllint` inside the `ee-wunder-devtools-ubi9` container,
- run `ansible-lint` inside the devtools container (after building the collection),
- run the `keycloak-basic`, `openvpn-basic`, `gitlab-runner-basic`,
  `nexus-basic`, `manage-esxi-basic`, and `vault-basic` Molecule scenarios,
- lint `.github/workflows/*.yml` via `actionlint` (Docker),
- validate `renovate.json` via `renovate-config-validator` (Docker), if present.

### 3. Run the collection smoke test

For a full **collection smoke test** (build + install + example playbook via FQCN):

```bash
pre-commit run collection-smoke --all-files --hook-stage manual
```

This will:

1. build the `lit.supplementary` collection inside the devtools container,
2. install the built tarball into `/tmp/wunder/collections`,
3. run the example playbook:

   ```bash
   ansible-playbook -i localhost, playbooks/example.yml
   ```

   using the installed collection via `ANSIBLE_COLLECTIONS_PATH=/tmp/wunder/collections`.

Use this smoke test whenever you want to verify that the collection is:

- buildable,
- installable,
- and usable via FQCN (`lit.supplementary.keycloak_config`) before pushing or tagging a release.
