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

ANSIBLE_CORE_VERSION="${ANSIBLE_CORE_VERSION:-$(python3 - <<'PY'
import ansible
try:
    from ansible.release import __version__  # type: ignore
except Exception:
    __version__ = getattr(ansible, "__version__", "")
print(__version__)
PY
)}"

ANSIBLE_LINT_VERSION="${ANSIBLE_LINT_VERSION:-$(python3 - <<'PY'
try:
    import ansiblelint  # type: ignore
    print(getattr(ansiblelint, "__version__", ""))
except Exception:
    print("")
PY
)}"

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

  export ANSIBLE_CONFIG="/workspace/ansible.cfg"
  export ANSIBLE_COLLECTIONS_PATH="${COLLECTIONS_DIR}:/usr/share/ansible/collections"

  export ANSIBLE_LINT_OFFLINE=true
  export ANSIBLE_LINT_SKIP_GALAXY_INSTALL=1
  export ANSIBLE_LINT_CONFIG="/workspace/.ansible-lint"

  echo "Running ansible-lint in /workspace..."
  ansible-lint
'
