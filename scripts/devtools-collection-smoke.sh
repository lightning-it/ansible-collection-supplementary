#!/usr/bin/env bash
set -eo pipefail

# 1) Namespace with default
COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"

# 2) Derive COLLECTION_NAME from repo name if not set
if [ -z "${COLLECTION_NAME:-}" ]; then
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
    echo "ERROR: COLLECTION_NAME not set and galaxy.yml missing 'name'." >&2
    exit 1
  fi
fi

# 3) Example playbook (relative to repo root)
EXAMPLE_PLAYBOOK="${EXAMPLE_PLAYBOOK:-playbooks/example.yml}"

echo "Running collection smoke test for ${COLLECTION_NAMESPACE}.${COLLECTION_NAME} using ${EXAMPLE_PLAYBOOK}"

# 4) Run inside wunder-devtools-ee
COLLECTION_NAMESPACE="$COLLECTION_NAMESPACE" \
COLLECTION_NAME="$COLLECTION_NAME" \
EXAMPLE_PLAYBOOK="$EXAMPLE_PLAYBOOK" \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -e

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"
  example="${EXAMPLE_PLAYBOOK:-playbooks/example.yml}"

  echo "Running collection smoke test for ${ns}.${name} with example playbook: ${example}"

  # 1) Build + install collection into /tmp/wunder/collections
  /workspace/scripts/devtools-collection-prepare.sh

  # 2) Use installed collection via ANSIBLE_COLLECTIONS_PATHS
  export ANSIBLE_COLLECTIONS_PATHS=/tmp/wunder/collections

  if [ -f /workspace/ansible.cfg ]; then
    export ANSIBLE_CONFIG=/workspace/ansible.cfg
  fi

  # 3) Run the example playbook against localhost
  ansible-playbook \
    -i localhost, \
    "${example}"
'
