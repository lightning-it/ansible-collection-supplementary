#!/usr/bin/env bash
set -euo pipefail

# Build and install the collection inside the wunder-devtools-ee container.
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

echo "Preparing collection ${ns}.${name} inside wunder-devtools-ee..."

# Stable HOME + stable ansible tmp (ansible-galaxy downloads)
export HOME=/tmp/wunder
mkdir -p "$HOME/.ansible/tmp"
export ANSIBLE_LOCAL_TEMP="$HOME/.ansible/tmp"
export ANSIBLE_REMOTE_TEMP="$HOME/.ansible/tmp"

# Remove any stale copy so Molecule uses the freshly built collection.
stale_collection_dir="$HOME/.ansible/collections/ansible_collections/${ns}/${name}"
if [ -d "$stale_collection_dir" ]; then
  rm -rf "$stale_collection_dir"
fi

# Per-run XDG cache (avoids ansible-compat/ansible-lint races)
export XDG_CACHE_HOME="$(mktemp -d /tmp/wunder/xdg-cache.XXXXXX)"
if [ "${DEBUG:-0}" = "1" ]; then
  echo "XDG_CACHE_HOME=$XDG_CACHE_HOME"
fi

# Per-run install target
COLLECTIONS_DIR="$(mktemp -d /tmp/wunder/collections.XXXXXX)"
export ANSIBLE_COLLECTIONS_PATH="${COLLECTIONS_DIR}:/usr/share/ansible/collections"

cd /workspace

# Build artifact and capture the output path
build_out="$(ansible-galaxy collection build --output-path /tmp/wunder --force)"
artifact="$(printf "%s\n" "$build_out" | awk '/Created collection for/ {print $NF}' | tail -n 1)"

if [ -z "${artifact:-}" ] || [ ! -f "$artifact" ]; then
  echo "ERROR: Collection artifact not found. Build output was:" >&2
  echo "$build_out" >&2
  echo "DEBUG: /tmp/wunder contents:" >&2
  ls -la /tmp/wunder >&2 || true
  exit 1
fi

# Install this collection into per-run dir
ansible-galaxy collection install "$artifact" -p "${COLLECTIONS_DIR}" --force

echo "Collection ${ns}.${name} installed in ${COLLECTIONS_DIR}"

# Print the path so caller scripts can capture it if needed
echo "${COLLECTIONS_DIR}"
