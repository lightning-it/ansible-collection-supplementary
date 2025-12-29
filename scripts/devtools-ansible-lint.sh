#!/usr/bin/env bash
set -eo pipefail

COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"

if [ -f galaxy.yml ]; then
  COLLECTION_NAME="$(python3 - <<'PY'
import yaml
with open("galaxy.yml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}
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

COLLECTION_NAMESPACE="$COLLECTION_NAMESPACE" \
COLLECTION_NAME="$COLLECTION_NAME" \
ANSIBLE_CORE_VERSION="${ANSIBLE_CORE_VERSION}" \
ANSIBLE_LINT_VERSION="${ANSIBLE_LINT_VERSION}" \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -euo pipefail

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"

  echo "Building and installing collection ${ns}.${name}..."

  # devtools-collection-prepare.sh prints the per-run collections dir on the last line
  COLLECTIONS_DIR="$(/workspace/scripts/devtools-collection-prepare.sh | tail -n 1)"

  if [ -z "${COLLECTIONS_DIR:-}" ] || [ ! -d "${COLLECTIONS_DIR}" ]; then
    echo "ERROR: COLLECTIONS_DIR not found/invalid: ${COLLECTIONS_DIR:-<empty>}" >&2
    exit 1
  fi

  coll_root="${COLLECTIONS_DIR}/ansible_collections/${ns}/${name}"
  if [ ! -d "$coll_root" ]; then
    echo "Collection root not found at $coll_root" >&2
    echo "DEBUG: content of ${COLLECTIONS_DIR}/ansible_collections/${ns}:" >&2
    ls -la "${COLLECTIONS_DIR}/ansible_collections/${ns}" 2>/dev/null || true
    exit 1
  fi

  cd /workspace

  core_ver="${ANSIBLE_CORE_VERSION}"
  lint_ver="${ANSIBLE_LINT_VERSION}"

  python3 -m pip install --upgrade \
    "ansible-core==${core_ver}" \
    "ansible-lint==${lint_ver}"

  export ANSIBLE_CONFIG="/workspace/ansible.cfg"
  export ANSIBLE_COLLECTIONS_PATHS="${COLLECTIONS_DIR}:/usr/share/ansible/collections"
  export ANSIBLE_COLLECTIONS_PATH="${ANSIBLE_COLLECTIONS_PATHS}"

  export ANSIBLE_LINT_OFFLINE=true
  export ANSIBLE_LINT_SKIP_GALAXY_INSTALL=1
  export ANSIBLE_LINT_CONFIG="/workspace/.ansible-lint"

  echo "Running ansible-lint in /workspace..."
  ansible-lint
'
