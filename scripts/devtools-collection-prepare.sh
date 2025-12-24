#!/usr/bin/env bash
set -euo pipefail

# Build and install the collection inside the wunder-devtools-ee container.
# Installs into /tmp/wunder/collections for use by other helper scripts.

ns="${COLLECTION_NAMESPACE:-lit}"

if [ -f /workspace/galaxy.yml ]; then
  name="$(python3 - <<'PY'
import yaml
with open("/workspace/galaxy.yml", "r") as f:
    data = yaml.safe_load(f)
print(data.get("name", ""))
PY
)"
fi

if [ -z "${name:-}" ]; then
  echo "ERROR: Failed to derive collection name from /workspace/galaxy.yml." >&2
  exit 1
fi

echo "Preparing collection ${ns}.${name} inside wunder-devtools-ee..."

rm -rf /tmp/wunder/.cache/ansible-compat \
       /tmp/wunder/${ns}-${name}-*.tar.gz \
       /tmp/wunder/collections
rm -rf /tmp/wunder/collections/ansible_collections || true
mkdir -p /tmp/wunder/collections

cd /workspace

ansible-galaxy collection build \
  --output-path /tmp/wunder \
  --force

ansible-galaxy collection install \
  /tmp/wunder/${ns}-${name}-*.tar.gz \
  -p /tmp/wunder/collections \
  --force

echo "Collection ${ns}.${name} installed in /tmp/wunder/collections."
