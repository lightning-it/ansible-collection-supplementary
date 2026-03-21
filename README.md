# lit.supplementary

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

printf '%s\n' 'DirectoryManagerPassw0rd!' \
  | sudo tee "$IDENTITY_ROOT/secrets/ds_dm_password" >/dev/null
printf '%s\n' 'PostgresPassw0rd!' \
  | sudo tee "$IDENTITY_ROOT/secrets/postgres_password" >/dev/null
printf '%s\n' 'KeycloakAdminPassw0rd!' \
  | sudo tee "$IDENTITY_ROOT/secrets/keycloak_admin_password" >/dev/null

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
    -d password='AlicePassw0rd!' \
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
`postgres_deploy`, `cloudflared`, and `cloudflare_warp`.

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
  `supplementary`, license `GPL-2.0-only`).
- Core collection dependencies are declared in `galaxy.yml`.
- Optional dependency overlays:
  - `collections/requirements.yml`
- Red Hat/AAP extension collections (for example `ansible.platform`,
  `infra.*`) are intentionally not pinned in this collection `galaxy.yml`;
  install them via consumer runtime overlays (for example
  `modulix-automation/ansible/collections/requirements-rh.yml`).
- Canonical role sources live in `roles/`; build with `ansible-galaxy
  collection build`.
- Molecule scenario `keycloak-deploy-basic` validates role wiring for Keycloak
  deployment including PostgreSQL role integration.
- Molecule scenario `keycloak-cac-basic` validates the Keycloak CaC role in
  skip mode.
- Molecule scenario `keycloak-basic` is kept as a legacy compatibility
  scenario and also validates `keycloak_cac` in skip mode.
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
  quay.io/l-it/ee-wunder-devtools-ubi9:v1.8.3 \
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
