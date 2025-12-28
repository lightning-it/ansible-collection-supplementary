#!/usr/bin/env bash
set -euo pipefail

# Build and install the collection inside the wunder-devtools-ee container.
# Installs into a per-run collections dir to avoid stale state.

ns="${COLLECTION_NAMESPACE:-lit}"

if [ -f /workspace/galaxy.yml ]; then
  name="$(python3 - <<'PY'
import yaml
with open("/workspace/galaxy.yml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}
print(data.get("name", ""))
PY
)"
fi

if [ -z "${name:-}" ]; then
  echo "ERROR: Failed to derive collection name from /workspace/galaxy.yml." >&2
  exit 1
fi

echo "Preparing collection ${ns}.${name} inside wunder-devtools-ee..."

# -------------------------------------------------------------------
# Stable HOME + per-run cache (prevents ansible-compat/ansible-lint races)
# -------------------------------------------------------------------
export HOME=/tmp/wunder
mkdir -p "$HOME/.ansible/tmp"

export XDG_CACHE_HOME="$(mktemp -d /tmp/wunder/xdg-cache.XXXXXX)"
echo "XDG_CACHE_HOME=$XDG_CACHE_HOME"

# -------------------------------------------------------------------
# Per-run install target (avoids 'directory not empty' + stale deps)
# -------------------------------------------------------------------
COLLECTIONS_DIR="$(mktemp -d /tmp/wunder/collections.XXXXXX)"
export ANSIBLE_COLLECTIONS_PATHS="${COLLECTIONS_DIR}:/usr/share/ansible/collections"
export ANSIBLE_COLLECTIONS_PATH="${ANSIBLE_COLLECTIONS_PATHS}"

cd /workspace

# Build collection artifact
ansible-galaxy collection build --output-path /tmp/wunder --force

# Install this collection into per-run dir
ansible-galaxy collection install \
  "/tmp/wunder/${ns}-${name}-"*.tar.gz \
  -p "${COLLECTIONS_DIR}" \
  --force

echo "Collection ${ns}.${name} installed in ${COLLECTIONS_DIR}"

# Print the path so caller scripts can capture it if needed
echo "${COLLECTIONS_DIR}"
