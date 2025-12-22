#!/usr/bin/env bash
set -euo pipefail

# Build and install the collection inside the wunder-devtools-ee container.
# Installs into /tmp/wunder/collections for use by other helper scripts.
#
# Expected to run INSIDE the container with:
#   - /workspace mounted as the collection repo
#   - COLLECTION_NAMESPACE optionally set

# 1) Namespace with default
ns="${COLLECTION_NAMESPACE:-lit}"

# 2) Derive collection name strictly from galaxy.yml
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

# 1) Clean previous build + install
rm -rf /tmp/wunder/.cache/ansible-compat \
       /tmp/wunder/${ns}-${name}-*.tar.gz \
       /tmp/wunder/collections
rm -rf /tmp/wunder/collections/ansible_collections || true
mkdir -p /tmp/wunder/collections

# 2) Build collection from /workspace (mounted repo)
cd /workspace

ansible-galaxy collection build \
  --output-path /tmp/wunder \
  --force

# 3) Install built collection into /tmp/wunder/collections
ansible-galaxy collection install \
  /tmp/wunder/${ns}-${name}-*.tar.gz \
  -p /tmp/wunder/collections \
  --force

echo "Collection ${ns}.${name} installed in /tmp/wunder/collections."
