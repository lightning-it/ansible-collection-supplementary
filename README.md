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
- Core collection dependencies are declared in `galaxy.yml`.
- Optional dependency overlays are split by distribution target:
  - `collections/requirements-public.yml` for public/GitHub extras
  - `collections/requirements-certified.yml` for certified-flow extras
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

Container-based execution (recommended):

```bash
H="$HOME/.cache/wunder-home"
mkdir -p "$H/.docker"

podman run --rm -it \
  --userns keep-id --user "$(id -u):$(id -g)" \
  --security-opt label=disable \
  -v "$PWD":"$PWD":z \
  -v "$HOME/.cache":"$HOME/.cache":z \
  -v "/run/user/$(id -u)/podman/podman.sock":"/run/user/$(id -u)/podman/podman.sock" \
  -w "$PWD" \
  -e HOME="$H" \
  -e DOCKER_CONFIG="$H/.docker" \
  -e XDG_CACHE_HOME="$HOME/.cache" \
  -e PRE_COMMIT_HOME="$HOME/.cache/pre-commit" \
  -e DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock" \
  -e GIT_CONFIG_COUNT=1 \
  -e GIT_CONFIG_KEY_0=safe.directory \
  -e GIT_CONFIG_VALUE_0="$PWD" \
  quay.io/l-it/ee-wunder-devtools-ubi9:latest \
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
