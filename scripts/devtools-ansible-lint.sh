#!/usr/bin/env bash
set -eo pipefail

galaxy_top_level_value() {
  local key="$1"
  local file="${2:-galaxy.yml}"
  awk -v key="$key" '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    {
      line=$0
      sub(/^[[:space:]]+/, "", line)
      if (line ~ ("^" key ":[[:space:]]*")) {
        val=line
        sub(("^" key ":[[:space:]]*"), "", val)
        sub(/[[:space:]]+#.*$/, "", val)
        gsub(/^["'\'']|["'\'']$/, "", val)
        print val
        exit
      }
    }
  ' "$file"
}

COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"

if [ -f galaxy.yml ]; then
  COLLECTION_NAME="$(galaxy_top_level_value "name" "galaxy.yml")"
fi

if [ -z "${COLLECTION_NAME:-}" ]; then
  echo "ERROR: Failed to derive COLLECTION_NAME from galaxy.yml." >&2
  exit 1
fi

REQUIRES_ANSIBLE=""
if [ -f meta/runtime.yml ]; then
  REQUIRES_ANSIBLE="$(galaxy_top_level_value "requires_ansible" "meta/runtime.yml" || true)"
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

ANSIBLE_LINT_SKIP_META_RUNTIME=0
if [ -n "${REQUIRES_ANSIBLE:-}" ] && [ -n "${ANSIBLE_LINT_VERSION:-}" ]; then
  req_minor=0
  lint_major=0
  req_minor_parsed="$(printf '%s' "$REQUIRES_ANSIBLE" | sed -nE 's/^>=2\.([0-9]+).*/\1/p')"
  if [ -n "${req_minor_parsed:-}" ]; then
    req_minor="$req_minor_parsed"
  fi
  if [[ "$ANSIBLE_LINT_VERSION" =~ ^([0-9]+) ]]; then
    lint_major="${BASH_REMATCH[1]}"
  fi
  # ansible-lint 6.x does not recognize >=2.18 in meta/runtime.yml.
  if [ "$req_minor" -ge 18 ] && [ "$lint_major" -lt 24 ]; then
    ANSIBLE_LINT_SKIP_META_RUNTIME=1
  fi
fi

echo "Running ansible-lint for collection: ${COLLECTION_NAMESPACE}.${COLLECTION_NAME}"
echo "Using ansible-core ${ANSIBLE_CORE_VERSION}, ansible-lint ${ANSIBLE_LINT_VERSION}"
if [ "${ANSIBLE_LINT_SKIP_META_RUNTIME}" = "1" ]; then
  echo "WARN: ansible-lint ${ANSIBLE_LINT_VERSION} cannot validate requires_ansible >=2.18.0; skipping meta-runtime checks."
fi

COLLECTION_NAMESPACE="$COLLECTION_NAMESPACE" \
COLLECTION_NAME="$COLLECTION_NAME" \
ANSIBLE_CORE_VERSION="${ANSIBLE_CORE_VERSION}" \
ANSIBLE_LINT_VERSION="${ANSIBLE_LINT_VERSION}" \
ANSIBLE_LINT_SKIP_META_RUNTIME="${ANSIBLE_LINT_SKIP_META_RUNTIME}" \
CONTAINER_HOME=/tmp/wunder \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -euo pipefail

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"

  # Keep Ansible cache/install state stable and outside /workspace.
  export HOME="/tmp/wunder"
  mkdir -p "${HOME}/.ansible/tmp" "${HOME}/.ansible/collections"
  export ANSIBLE_LOCAL_TEMP="${HOME}/.ansible/tmp"
  export ANSIBLE_REMOTE_TEMP="${HOME}/.ansible/tmp"

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

  # Avoid stale duplicate collection resolution from ~/.ansible.
  stale_collection_dir="${HOME}/.ansible/collections/ansible_collections/${ns}/${name}"
  if [ -d "$stale_collection_dir" ]; then
    rm -rf "$stale_collection_dir"
  fi

  export ANSIBLE_CONFIG="/workspace/ansible.cfg"
  export ANSIBLE_COLLECTIONS_PATH="${COLLECTIONS_DIR}:/workspace/collections:/usr/share/ansible/collections"

  export ANSIBLE_LINT_OFFLINE=true
  export ANSIBLE_LINT_SKIP_GALAXY_INSTALL=1
  export ANSIBLE_LINT_CONFIG="/workspace/.ansible-lint"

  echo "Running ansible-lint in /workspace..."
  ansible_lint_args=()
  if [ "${ANSIBLE_LINT_SKIP_META_RUNTIME:-0}" = "1" ]; then
    ansible_lint_args+=("-x" "meta-runtime,meta-runtime[unsupported-version]")
    ansible_lint_args+=("--exclude" "meta/runtime.yml")
  fi
  ansible-lint "${ansible_lint_args[@]}"
'
