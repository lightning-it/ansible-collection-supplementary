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

  # 0) Remove stale dependency installs so fresh deps can be installed
  dep_paths=()
  dep_fqcns=()
  if [ -f /workspace/galaxy.yml ]; then
    while IFS= read -r line; do
      dep_paths+=("${line%::*}")
      dep_fqcns+=("${line##*::}")
    done < <(
      python3 - <<'PY'
import yaml, sys
try:
    with open("/workspace/galaxy.yml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    for fqcn in (data.get("dependencies") or {}).keys():
        parts = fqcn.split(".")
        if len(parts) == 2:
            ns, coll = parts
            print(f"/tmp/wunder/collections/ansible_collections/{ns}/{coll}::{fqcn}")
except Exception as exc:  # noqa: BLE001
    sys.stderr.write(f"WARN: failed to parse galaxy.yml dependencies: {exc}\n")
PY
    )
  fi

  for dep_path in "${dep_paths[@]}"; do
    if [ -d "$dep_path" ]; then
      echo "Removing stale dependency at $dep_path to allow a clean install..."
      rm -rf "$dep_path" || true
    fi
  done

  # 1) Build + install collection into /tmp/wunder/collections
  /workspace/scripts/devtools-collection-prepare.sh

  # 1b) Install declared dependencies freshly (if any)
  for dep_fqcn in "${dep_fqcns[@]}"; do
    if [ -n "$dep_fqcn" ]; then
      echo "Installing dependency ${dep_fqcn} into /tmp/wunder/collections..."
      ansible-galaxy collection install "$dep_fqcn" -p /tmp/wunder/collections --force
    fi
  done

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
