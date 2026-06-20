#!/usr/bin/env bash
set -euo pipefail

# Build and install the collection inside the ee-wunder-devtools-ubi9 container.
# Installs into a per-run collections dir to avoid stale state.
# Prints COLLECTIONS_DIR as the last line for callers.

# Derive namespace+name from galaxy.yml (authoritative)
if [ ! -f /workspace/galaxy.yml ]; then
  echo "ERROR: /workspace/galaxy.yml not found." >&2
  exit 1
fi

read -r ns name <<<"$(python3 - <<'PY'
import yaml
with open("/workspace/galaxy.yml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}
print(data.get("namespace",""), data.get("name",""))
PY
)"

ns="${COLLECTION_NAMESPACE:-$ns}"
if [ -z "${ns:-}" ] || [ -z "${name:-}" ]; then
  echo "ERROR: Failed to derive namespace/name (namespace='${ns:-}', name='${name:-}')" >&2
  exit 1
fi

echo "Preparing collection ${ns}.${name} inside ee-wunder-devtools-ubi9..."

# Stable HOME + stable ansible tmp (ansible-galaxy downloads)
export HOME="${HOME:-/tmp/wunder}"
mkdir -p "$HOME"
mkdir -p "$HOME/.ansible/tmp"
export ANSIBLE_LOCAL_TEMP="$HOME/.ansible/tmp"
export ANSIBLE_REMOTE_TEMP="$HOME/.ansible/tmp"

# Remove any stale copy so Molecule uses the freshly built collection.
stale_collection_dir="$HOME/.ansible/collections/ansible_collections/${ns}/${name}"
if [ -d "$stale_collection_dir" ]; then
  rm -rf "$stale_collection_dir"
fi

# Per-run XDG cache (avoids ansible-compat/ansible-lint races)
XDG_CACHE_HOME="$(mktemp -d "${HOME}/xdg-cache.XXXXXX")"
export XDG_CACHE_HOME
if [ "${DEBUG:-0}" = "1" ]; then
  echo "XDG_CACHE_HOME=$XDG_CACHE_HOME"
fi

# Per-run install target
COLLECTIONS_DIR="$(mktemp -d "${HOME}/collections.XXXXXX")"
ROLES_DIR="${HOME}/roles"
mkdir -p "${ROLES_DIR}"
export ANSIBLE_COLLECTIONS_PATH="${COLLECTIONS_DIR}:/usr/share/ansible/collections"
export ANSIBLE_ROLES_PATH="${ROLES_DIR}:/workspace/roles:/usr/share/ansible/roles"
BUILD_OUTPUT_DIR="$(mktemp -d "${HOME}/build.XXXXXX")"

cd /workspace

install_collection_dependency() {
  local dep_spec="$1"
  local dep_fqcn="${dep_spec%%:*}"
  local dep_name="${dep_fqcn#lit.}"
  local source_root="${WUNDER_DEVTOOLS_SOURCE_ROOT:-}"
  local local_source=""

  if [[ "$dep_fqcn" == lit.* ]] && [ -n "$source_root" ]; then
    local_source="${source_root}/ansible-collection-${dep_name}"
    if [ -f "${local_source}/galaxy.yml" ]; then
      echo "Installing local dependency ${dep_fqcn} from ${local_source}..." >&2
      dep_build_out="$(
        cd "$local_source"
        ansible-galaxy collection build --output-path "${BUILD_OUTPUT_DIR}" --force
      )"
      dep_artifact="$(printf "%s\n" "$dep_build_out" | awk '/Created collection for/ {print $NF}' | tail -n 1)"
      if [ -z "${dep_artifact:-}" ] || [ ! -f "$dep_artifact" ]; then
        echo "ERROR: Local dependency artifact not found. Build output was:" >&2
        echo "$dep_build_out" >&2
        exit 1
      fi
      ansible-galaxy collection install "$dep_artifact" -p "${COLLECTIONS_DIR}" --force --no-deps >&2
      return
    fi
  fi

  echo "Installing dependency ${dep_spec} into ${COLLECTIONS_DIR}..." >&2
  ansible-galaxy collection install "$dep_spec" -p "${COLLECTIONS_DIR}" --force >&2
}

dep_specs=()
if [ -f /workspace/galaxy.yml ]; then
  while IFS= read -r dep_spec; do
    dep_specs+=("$dep_spec")
  done < <(bash /workspace/scripts/devtools-galaxy.sh dependencies /workspace/galaxy.yml || true)
fi

for dep_spec in "${dep_specs[@]}"; do
  if [ -n "$dep_spec" ]; then
    install_collection_dependency "$dep_spec"
  fi
done

if [ -f /workspace/requirements.yml ] && python3 - <<'PY'
import sys
import yaml

with open("/workspace/requirements.yml", "r", encoding="utf-8") as req_file:
    data = yaml.safe_load(req_file) or {}

sys.exit(0 if data.get("roles") else 1)
PY
then
  echo "Installing role requirements from /workspace/requirements.yml into ${ROLES_DIR}..." >&2
  ansible-galaxy role install -r /workspace/requirements.yml -p "${ROLES_DIR}" --force >&2
fi

# Build artifact and capture the output path
build_out="$(ansible-galaxy collection build --output-path "${BUILD_OUTPUT_DIR}" --force)"
artifact="$(printf "%s\n" "$build_out" | awk '/Created collection for/ {print $NF}' | tail -n 1)"

if [ -z "${artifact:-}" ] || [ ! -f "$artifact" ]; then
  echo "ERROR: Collection artifact not found. Build output was:" >&2
  echo "$build_out" >&2
  echo "DEBUG: ${HOME} contents:" >&2
  ls -la "${HOME}" >&2 || true
  exit 1
fi

# Install this collection into per-run dir
ansible-galaxy collection install "$artifact" -p "${COLLECTIONS_DIR}" --force --no-deps

echo "Collection ${ns}.${name} installed in ${COLLECTIONS_DIR}"

# Print the path so caller scripts can capture it if needed
echo "${COLLECTIONS_DIR}"
