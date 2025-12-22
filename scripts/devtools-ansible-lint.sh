#!/usr/bin/env bash
set -eo pipefail

# 1) Namespace with default
COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"

# 2) Derive COLLECTION_NAME from galaxy.yml (authoritative)
if [ -f galaxy.yml ]; then
  COLLECTION_NAME="$(python3 - <<'PY'
import yaml
with open("galaxy.yml", "r") as f:
    data = yaml.safe_load(f)
print(data.get("name", ""))
PY
)"
fi

if [ -z "${COLLECTION_NAME:-}" ]; then
  echo "ERROR: Failed to derive COLLECTION_NAME from galaxy.yml." >&2
  exit 1
fi

if [ -z "${ANSIBLE_CORE_VERSION:-}" ] || [ -z "${ANSIBLE_LINT_VERSION:-}" ]; then
  echo "ERROR: ANSIBLE_CORE_VERSION and ANSIBLE_LINT_VERSION must be set." >&2
  exit 1
fi

echo "Running ansible-lint for collection: ${COLLECTION_NAMESPACE}.${COLLECTION_NAME}"
echo "Using ansible-core ${ANSIBLE_CORE_VERSION}, ansible-lint ${ANSIBLE_LINT_VERSION}"

# 3) Run inside the wunder-devtools-ee container
COLLECTION_NAMESPACE="$COLLECTION_NAMESPACE" \
COLLECTION_NAME="$COLLECTION_NAME" \
ANSIBLE_CORE_VERSION="${ANSIBLE_CORE_VERSION}" \
ANSIBLE_LINT_VERSION="${ANSIBLE_LINT_VERSION}" \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -e

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"

  echo "Building and installing collection ${ns}.${name}..."
  # 1) Build + install collection into /tmp/wunder/collections
  /workspace/scripts/devtools-collection-prepare.sh

  coll_root="/tmp/wunder/collections/ansible_collections/${ns}/${name}"
  if [ ! -d "$coll_root" ]; then
    echo "Collection root not found at $coll_root" >&2
    exit 1
  fi

  # 2) Run lint from the source tree so we respect repo-level config/excludes
  cd /workspace

  # 3) Use versions passed from CI (with defaults)
  core_ver="${ANSIBLE_CORE_VERSION}"
  lint_ver="${ANSIBLE_LINT_VERSION}"

  python3 -m pip install --upgrade \
    "ansible-core==${core_ver}" \
    "ansible-lint==${lint_ver}"

  export ANSIBLE_CONFIG="/workspace/ansible.cfg"
  export ANSIBLE_COLLECTIONS_PATHS="/tmp/wunder/collections"
  export ANSIBLE_LINT_OFFLINE=true
  export ANSIBLE_LINT_SKIP_GALAXY_INSTALL=1
  export ANSIBLE_LINT_CONFIG="/workspace/.ansible-lint"

  echo "Running ansible-lint in /workspace..."
  ansible-lint
'
