# lit.supplementary

<!-- BEGIN LIT_SHARED_RELEASE_MODEL -->

## Release and Quality Model

This repository follows the Lightning IT shared release and quality model.

See [RELEASE.md](./RELEASE.md) for:

- branch and release flow
- required quality checks
- test matrix
- release evidence
- artifact publishing
- supported repository-specific release behavior

Repository classification: **Ansible Collection**.
Required test profiles: `pre-commit, lint, light, molecule-light, molecule-heavy-incus, release-validation`.
Publishing targets: `github-release, ansible-galaxy`.

## Supported and Tested Platforms

| Platform / Product | Status | Validation |
|---|---:|---|
| ubuntu-latest | Supported | Molecule / Incus |
| rhel-9 | Supported | Molecule / Incus |
| rhel-10 | Supported | Molecule / Incus |
| ansible-core | Tested where applicable | Molecule / Incus |
| keycloak-rhbk | Tested where applicable | Molecule / Incus |
| aap-2.6 | Tested where applicable | Molecule / Incus |
| aap-2.7 | Tested where applicable | Molecule / Incus |
| incus | Tested where applicable | Molecule / Incus |

<!-- END LIT_SHARED_RELEASE_MODEL -->

<!-- BEGIN LIT_QUALITY_BADGES -->

[![CI](https://github.com/lightning-it/ansible-collection-supplementary/actions/workflows/collection-ci.yml/badge.svg?branch=develop)](https://github.com/lightning-it/ansible-collection-supplementary/actions/workflows/collection-ci.yml)
[![Latest Release](https://img.shields.io/github/v/release/lightning-it/ansible-collection-supplementary?sort=semver)](https://github.com/lightning-it/ansible-collection-supplementary/releases/latest)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/lightning-it/ansible-collection-supplementary/badge)](https://scorecard.dev/viewer/?uri=github.com/lightning-it/ansible-collection-supplementary)
[![Ansible Galaxy](https://img.shields.io/ansible/collection/v/lit/supplementary?label=Ansible%20Galaxy)](https://galaxy.ansible.com/ui/repo/published/lit/supplementary/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

<!-- END LIT_QUALITY_BADGES -->

## Wunderbox Identity Stack PoC

This repository now includes production-like PoC artifacts for a single-node
identity stack on a Wunderbox host:

- 389 Directory Server in a container
- Keycloak in a container with PostgreSQL backend
- LDAP federation from Keycloak to 389ds
- Nested group resolution via 389ds MemberOf plugin fixup
- OIDC `groups` claim emitted from Keycloak tokens

### Requirements

- Podman with `podman kube play`
- `envsubst` (from `gettext`) for rendering manifest variables
- local access to image artifacts (runtime is offline-capable)

Pinned images:

- `389ds/dirsrv:3.1` (via custom wrapper image build)
- `quay.io/keycloak/keycloak:26.5.4`
- `docker.io/library/postgres:16`

### Files

- Manifest: `manifests/identity-stack.pod.yaml`
- LDAP image: `containerfiles/ldap/Containerfile`
- LDAP bootstrap entrypoint: `containerfiles/ldap/entrypoint-wrapper.sh`
- LDAP seed: `bootstrap/seed.ldif`
- Keycloak bootstrap: `bootstrap/keycloak-bootstrap.sh`

### Quickstart

1. Create host directories and secrets.

```bash
export IDENTITY_ROOT=/srv/wunderbox/identity

sudo mkdir -p \
  "$IDENTITY_ROOT"/{ldap,ldap-tls,pg,keycloak,bootstrap,secrets}

sudo cp -f bootstrap/seed.ldif "$IDENTITY_ROOT/bootstrap/seed.ldif"
sudo cp -f bootstrap/keycloak-bootstrap.sh "$IDENTITY_ROOT/bootstrap/keycloak-bootstrap.sh"
sudo chmod 0755 "$IDENTITY_ROOT/bootstrap/keycloak-bootstrap.sh"

printf '%s\n' '<set-a-local-directory-manager-password>' \
  | sudo install -m 0600 /dev/stdin "$IDENTITY_ROOT/secrets/ds_dm_password"
printf '%s\n' '<set-a-local-postgres-password>' \
  | sudo install -m 0600 /dev/stdin "$IDENTITY_ROOT/secrets/postgres_password"
printf '%s\n' '<set-a-local-keycloak-admin-password>' \
  | sudo install -m 0600 /dev/stdin "$IDENTITY_ROOT/secrets/keycloak_admin_password"

sudo chmod 0600 "$IDENTITY_ROOT/secrets/"*
```

2. Build the local LDAP wrapper image.

```bash
podman build \
  -t localhost/wunderbox-ldap:3.1-bootstrap \
  -f containerfiles/ldap/Containerfile \
  .
```

3. Render and start the pod.

```bash
: "${IDENTITY_ROOT:=/srv/wunderbox/identity}"
: "${BASE_DN:=dc=wunderbox,dc=local}"
: "${LDAP_HOSTNAME:=ldap.wunderbox.local}"
: "${LDAP_HOST_PORT:=3389}"
: "${LDAPS_HOST_PORT:=3636}"
: "${KEYCLOAK_HOSTNAME:=keycloak.wunderbox.local}"
: "${KEYCLOAK_HOST_PORT:=8080}"
: "${KEYCLOAK_HTTP_PORT:=8080}"
: "${KEYCLOAK_DB_NAME:=keycloak}"
: "${KEYCLOAK_DB_USER:=keycloak}"
: "${KEYCLOAK_ADMIN:=admin}"

envsubst < manifests/identity-stack.pod.yaml > /tmp/identity-stack.rendered.yaml
podman kube play /tmp/identity-stack.rendered.yaml
```

4. Verify LDAP nested `memberOf` transitivity (acceptance test #1).

```bash
LDAP_DM_PASSWORD="$(sudo cat "$IDENTITY_ROOT/secrets/ds_dm_password")"

podman exec -i identity-stack-ldap ldapsearch -LLL -x \
  -H ldap://127.0.0.1:3389 \
  -D "cn=Directory Manager" \
  -w "$LDAP_DM_PASSWORD" \
  -b "uid=alice,ou=people,dc=wunderbox,dc=local" \
  memberOf
```

Expected: `memberOf` contains both:

- `cn=aio-wbx-ops,ou=groups,dc=wunderbox,dc=local`
- `cn=aio-wbx-admins,ou=groups,dc=wunderbox,dc=local`

5. Bootstrap Keycloak federation and OIDC mappers.

```bash
./bootstrap/keycloak-bootstrap.sh
```

6. Verify login + token groups claim (acceptance tests #2 and #3).

```bash
TOKEN="$(
  curl -fsS \
    -d grant_type=password \
    -d client_id=demo \
    -d username=alice \
    -d password='<alice-demo-password>' \
    "http://127.0.0.1:8080/realms/wunderbox/protocol/openid-connect/token" \
  | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p'
)"

python3 - "$TOKEN" <<'PY'
import base64
import json
import sys

tok = sys.argv[1]
payload = tok.split(".")[1]
payload += "=" * (-len(payload) % 4)
data = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
print("groups =", data.get("groups"))
PY
```

Expected groups include `aio-wbx-ops` and `aio-wbx-admins` (path or plain group names depending on mapper behavior).

7. Rerun bootstrap for idempotency check (acceptance test #4).

```bash
./bootstrap/keycloak-bootstrap.sh
```

### Troubleshooting

- 389ds plugin and status checks:

```bash
podman exec -it identity-stack-ldap dsconf localhost plugin memberof show
podman exec -it identity-stack-ldap dsconf localhost plugin memberof fixup dc=wunderbox,dc=local
podman exec -it identity-stack-ldap dsctl localhost status
```

- Keycloak logs and bootstrap rerun:

```bash
podman logs -f identity-stack-keycloak
./bootstrap/keycloak-bootstrap.sh
```

- Full reset:

```bash
podman kube down /tmp/identity-stack.rendered.yaml || true
sudo rm -rf /srv/wunderbox/identity/*
```

Supplementary Ansible collection for ModuLix / Lightning IT.
It includes service deployment and Configuration-as-Code roles such as
`keycloak_deploy`, `keycloak_cac`, `forgejo_deploy`, `forgejo_cac`,
`semaphore_deploy`, `semaphore_cac`, `nessus_deploy`, `nessus_cac`,
`postgres_deploy`, `checkmk_deploy`, `loki_deploy`,
`alloy_deploy`, `grafana_deploy`, `cloudflared`, and
`cloudflare_warp`.

## Wunderbox Monitoring and Logging PoC

The Wunderbox PoC monitoring/logging stack is intentionally small and
single-host:

- Checkmk is the primary monitoring system.
- Loki, Alloy, and Grafana provide the technical logging stack.
- Loki is internal by default on `127.0.0.1:3100`.
- Grafana and Checkmk are the only public reverse-proxy vhosts added by
  `playbooks/wunderbox_monitoring_logging.yml`.
- Prometheus and Alertmanager are intentionally not included in this PoC scope.
- Forgejo Runner is intentionally excluded from the Wunderbox playbook and may be
  deployed later on a separate VM if customer CI/CD is required.

Example invocation:

```bash
ansible-playbook -i inventory.yml \
  playbooks/wunderbox_monitoring_logging.yml
```

Example inventory snippet:

```yaml
all:
  hosts:
    wunderbox02.prd.dmz.corp.l-it.io:
      grafana_deploy_public_fqdn: grafana.wunderbox02.prd.dmz.corp.l-it.io
      checkmk_deploy_public_fqdn: checkmk.wunderbox02.prd.dmz.corp.l-it.io
      grafana_deploy_admin_password: "{{ vault_wunderbox02_grafana_admin_password }}"
      checkmk_deploy_admin_password: "{{ vault_wunderbox02_checkmk_admin_password }}"
```

Service catalog:

| Service | Exposure | Login |
|---|---|---|
| Checkmk | `https://checkmk.<wunderbox-domain>` | `cmkadmin`, password from HC Vault or Ansible Vault |
| Grafana | `https://grafana.<wunderbox-domain>` | `admin`, password from HC Vault or Ansible Vault |
| Loki | Internal only, `http://127.0.0.1:3100` | No public login |
| Alloy | Agent only | No user login |

Persistent data defaults:

| Role | Data path |
|---|---|
| `checkmk_deploy` | `/srv/checkmk/data` |
| `loki_deploy` | `/srv/loki/data` |
| `alloy_deploy` | `/srv/alloy/data` |
| `grafana_deploy` | `/srv/grafana/data` |

Secrets:

- Grafana admin: HC Vault path `{{ inventory_hostname }}/grafana/admin`, or
  `grafana_deploy_admin_password` from Ansible Vault.
- Checkmk admin: HC Vault path `{{ inventory_hostname }}/checkmk/admin`, or
  `checkmk_deploy_admin_password` from Ansible Vault.
- No plaintext generated secret files are written unless the explicit
  `*_allow_local_secret_files=true` break-glass variable is set.

Alloy default log collection:

- journald/systemd
- Podman container log files when present
- NGINX, Vault operational, Keycloak, Nexus, and Forgejo log paths under `/srv`
- Vault audit logs are disabled by default with
  `alloy_deploy_collect_vault_audit_logs: false`

Checkmk object registration is represented by
`checkmk_deploy_monitoring_targets` and rendered as hook data for a future
Checkmk CaC role. The first implementation deploys Checkmk but does not yet
create Checkmk hosts/services through its API.

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
    - role: lit.supplementary.keycloak_cac
```

## Development

- `galaxy.yml` defines the collection metadata (namespace `lit`, name
  `supplementary`, license `MIT`).
- Core collection dependencies are declared in `galaxy.yml`.
- Red Hat/AAP extension collections (for example `ansible.platform`,
  `infra.*`) are intentionally not pinned in this collection `galaxy.yml`;
  install them via consumer runtime overlays (for example
  `modulix-automation/ansible/collections/requirements-rh.yml`).
- AAP development and testing uses Ansible-managed Incus VMs. Incus instance
  lifecycle is owned by `lit.ubuntu.incus_instance`; this collection only owns
  AAP role behavior:
  - [docs/testing/README.md](docs/testing/README.md)
  - [docs/testing/aap.md](docs/testing/aap.md)
- Canonical role sources live in `roles/`; build with `ansible-galaxy
  collection build`.
- Molecule scenario `keycloak-tiny` performs fast, real deployment and
  technical verification suitable for pull requests.
- Molecule scenario `keycloak-heavy` validates production-like PostgreSQL,
  LDAP, persistence, restart, backup/restore, TLS, and authorization behavior.
- Molecule scenario `keycloak-application-acceptance` validates browser login,
  sessions, OIDC claims, and positive and negative authorization. See
  [Keycloak testing](docs/testing/keycloak.md) for commands and evidence.
- Molecule scenario `forgejo-deploy-basic` validates role wiring for Forgejo
  deployment including PostgreSQL role integration.
- Molecule scenario `forgejo-cac-basic` validates the Forgejo CaC role in
  skip mode.
- Molecule scenario `postgres-deploy-basic` validates role wiring for the
  dedicated PostgreSQL deployment role.
- Molecule scenario `semaphore-deploy-basic` validates role wiring for
  Semaphore deployment including PostgreSQL role integration.
- Molecule scenario `semaphore-cac-basic` validates the Semaphore CaC role in
  skip mode.
- Molecule scenario `nessus-deploy-basic` validates role wiring for Nessus
  deployment.
- Molecule scenario `nessus-cac-basic` validates the Nessus CaC role in skip
  mode.
- Molecule scenario `wunderbox-monitoring-logging-basic` validates syntax
  wiring for the generic Checkmk, Loki, Alloy, and Grafana deploy roles. Runtime
  container startup is intentionally skipped in CI because Checkmk and Grafana
  are heavyweight service containers.
- Molecule scenario `vault-basic` runs the vault role with a stub terragrunt role
  to validate basics locally.
- Molecule scenario `openvpn-basic` runs the openvpn role without standing up a
  server to validate role wiring and defaults.
- Molecule scenario `cloudflared-basic` runs the cloudflared role with install
  steps disabled to validate role wiring and defaults.
- Molecule scenario `cloudflare-warp-basic` renders a headless WARP `mdm.xml`
  profile with install/service steps disabled to validate role wiring and
  defaults.
- Molecule scenario `gitlab-runner-basic` runs the gitlab_runner stub role
  (acknowledging experimental status) to keep lint/test coverage green.
  It uses the repo's roles path to source the role locally.
- Molecule scenario `nexus-basic` runs the nexus stub role (acknowledging
  experimental status) to keep coverage green.
- Molecule scenario `manage-esxi-basic` uses a stub manage_esxi role so tests stay
  green without vCenter/ESXi access.
- Protected AAP Incus scenarios are intentionally not implemented in this
  collection right now. Recreate them through `lit.ubuntu.incus_instance`
  instead of shell helpers.

## Local checks

This repository uses **pre-commit** and a shared devtools container
(`ee-wunder-devtools-ubi9`) to keep linting and runtime tests consistent between
local development and CI.

### 1. Install pre-commit

If you haven't already:

```bash
pip install pre-commit
pre-commit install
```

This installs the standard `pre-commit` hook for this repo (YAML, Ansible,
Molecule, etc.).

### 2. Run all linters locally

To run all configured linters (YAML, ansible-lint, Molecule keycloak-deploy-basic,
keycloak-cac-basic, keycloak-basic, forgejo-deploy-basic, forgejo-cac-basic,
postgres-deploy-basic, semaphore-deploy-basic, semaphore-cac-basic,
nessus-deploy-basic, nessus-cac-basic, openvpn-basic, cloudflared-basic,
gitlab-runner-basic, nexus-basic, manage-esxi-basic, vault-basic, GitHub Actions
lint, Renovate config validation):

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
  quay.io/l-it/ee-wunder-devtools-ubi9:v1.8.7 \
  pre-commit run --all-files
```

This will:

- run `yamllint` inside the `ee-wunder-devtools-ubi9` container,
- run `ansible-lint` inside the devtools container (after building the collection),
- run the `keycloak-deploy-basic`, `keycloak-cac-basic`, `keycloak-basic`,
  `forgejo-deploy-basic`, `forgejo-cac-basic`, `postgres-deploy-basic`,
  `semaphore-deploy-basic`, `semaphore-cac-basic`, `nessus-deploy-basic`,
  `nessus-cac-basic`, `openvpn-basic`, `gitlab-runner-basic`, `nexus-basic`,
  `manage-esxi-basic`, and `vault-basic` Molecule scenarios,
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
- and usable via FQCN (`lit.supplementary.keycloak_cac`) before pushing or tagging a release.

## Security

See [SECURITY.md](./SECURITY.md) for supported versions and vulnerability reporting.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for contribution and review expectations.

## License

See [LICENSE](./LICENSE).

<!-- BEGIN LIT_RELEASE_QUALITY_MODEL -->

## Release and Quality Model

This repository follows the Lightning IT shared release and quality model.
The README shows the current supported and tested matrix.
Exact per-version validation proof is stored with each GitHub Release as `release-evidence.md` and `release-evidence.json`.
Releases are created from the protected `main` branch after a reviewed `develop -> main` release promotion.
Collection releases validate collection sanity, Molecule scenarios, build integrity, and Ansible Galaxy publishing where enabled.

See:

- [RELEASE.md](./RELEASE.md)
- [TESTING.md](./TESTING.md)
- [GitHub Releases](../../releases)

Repository classification: **Ansible Collection**.
Required test profiles: `pre-commit, lint, light, molecule-light, molecule-heavy-incus, release-validation`.
Publishing targets: `github-release, ansible-galaxy`.

<!-- END LIT_RELEASE_QUALITY_MODEL -->

<!-- BEGIN LIT_COMPATIBILITY_MATRIX -->

## Compatibility Matrix

| Collection Version | Platform | Product | Validation |
|---|---|---|---|
| Latest release | ubuntu-latest | ansible-core, keycloak-rhbk, aap-2.6, aap-2.7, incus | See release evidence |
| Latest release | rhel-9 | ansible-core, keycloak-rhbk, aap-2.6, aap-2.7, incus | See release evidence |
| Latest release | rhel-10 | ansible-core, keycloak-rhbk, aap-2.6, aap-2.7, incus | See release evidence |

| Scenario | Test Type | Validation |
|---|---|---|
| collection-sanity | Collection sanity | See release evidence |
| molecule-light | Molecule light | See release evidence |
| molecule-heavy-incus | Heavy Incus | See release evidence |
| galaxy-build | Galaxy build/publish | See release evidence |

Validation proof for each released version is stored in the corresponding GitHub Release evidence.

<!-- END LIT_COMPATIBILITY_MATRIX -->

## Release Evidence

Every released version includes immutable release evidence attached to the corresponding GitHub Release.
The evidence records:

- tested matrix combinations
- GitHub Actions run links
- artifact references
- publish status
- security scan status

See [GitHub Releases](../../releases), [RELEASE.md](./RELEASE.md), and [TESTING.md](./TESTING.md) for the release process and validation model.
