#!/usr/bin/env bash
set -eo pipefail

COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"

if [ -z "${COLLECTION_NAME:-}" ]; then
  if [ -f galaxy.yml ]; then
    COLLECTION_NAME="$(scripts/devtools-galaxy.sh value name galaxy.yml || true)"
  fi
  if [ -z "${COLLECTION_NAME:-}" ]; then
    echo "ERROR: COLLECTION_NAME not set and galaxy.yml missing 'name'." >&2
    exit 1
  fi
fi

EXAMPLE_PLAYBOOK="${EXAMPLE_PLAYBOOK:-playbooks/example.yml}"

echo "Running collection smoke test for ${COLLECTION_NAMESPACE}.${COLLECTION_NAME} using ${EXAMPLE_PLAYBOOK}"

COLLECTION_NAMESPACE="$COLLECTION_NAMESPACE" \
COLLECTION_NAME="$COLLECTION_NAME" \
EXAMPLE_PLAYBOOK="$EXAMPLE_PLAYBOOK" \
CONTAINER_HOME=/tmp/wunder \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -euo pipefail

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"
  example="${EXAMPLE_PLAYBOOK:-playbooks/example.yml}"

  echo "Running collection smoke test for ${ns}.${name} with example playbook: ${example}"

  # -------------------------------------------------------------------
  # 1) Build + install this collection into a per-run collections dir
  # -------------------------------------------------------------------
  COLLECTIONS_DIR="$(/workspace/scripts/devtools-collection-prepare.sh | tail -n 1)"

  if [ -z "${COLLECTIONS_DIR:-}" ] || [ ! -d "${COLLECTIONS_DIR}" ]; then
    echo "ERROR: COLLECTIONS_DIR not found/invalid: ${COLLECTIONS_DIR:-<empty>}" >&2
    exit 1
  fi

  export ANSIBLE_COLLECTIONS_PATH="${COLLECTIONS_DIR}:/usr/share/ansible/collections"

  # -------------------------------------------------------------------
  # 2) Install declared dependencies into the SAME per-run dir
  # -------------------------------------------------------------------
  dep_specs=()
  if [ -f /workspace/galaxy.yml ]; then
    while IFS= read -r dep_spec; do
      dep_specs+=("$dep_spec")
    done < <(/workspace/scripts/devtools-galaxy.sh dependencies /workspace/galaxy.yml || true)
  fi

  for dep_spec in "${dep_specs[@]}"; do
    if [ -n "$dep_spec" ]; then
      echo "Installing dependency ${dep_spec} into ${COLLECTIONS_DIR}..."
      ansible-galaxy collection install "$dep_spec" -p "${COLLECTIONS_DIR}" --force
    fi
  done

  # -------------------------------------------------------------------
  # 3) Configure Ansible (optional)
  # -------------------------------------------------------------------
  if [ -f /workspace/ansible.cfg ]; then
    export ANSIBLE_CONFIG=/workspace/ansible.cfg
  fi

  # -------------------------------------------------------------------
  # 4) Run example playbook
  # -------------------------------------------------------------------
  ansible-playbook -i localhost, "${example}"
'
