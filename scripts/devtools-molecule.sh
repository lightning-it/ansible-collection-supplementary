#!/usr/bin/env bash
set -eo pipefail

# 1) Namespace with default
COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"

# 2) Derive COLLECTION_NAME from repo name if not set
if [ -z "${COLLECTION_NAME:-}" ]; then
  # Prefer GITHUB_REPOSITORY in CI (org/repo)
  if [ -n "${GITHUB_REPOSITORY:-}" ]; then
    repo_basename="${GITHUB_REPOSITORY##*/}"
  else
    # Fallback: current directory name
    repo_basename="$(basename "$PWD")"
  fi

  case "$repo_basename" in
    ansible-collection-*)
      COLLECTION_NAME="${repo_basename#ansible-collection-}"
      ;;
    *)
      echo "WARN: Could not infer COLLECTION_NAME from repo name '${repo_basename}', falling back to 'foundational'" >&2
      COLLECTION_NAME="foundational"
      ;;
  esac
fi

echo "Preparing Molecule tests for collection: ${COLLECTION_NAMESPACE}.${COLLECTION_NAME}"

# 3) Run inside wunder-devtools-ee
COLLECTION_NAMESPACE="$COLLECTION_NAMESPACE" \
COLLECTION_NAME="$COLLECTION_NAME" \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -e

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"

  echo "Preparing collection ${ns}.${name} for Molecule tests..."

  # 1) Build + install collection into /tmp/wunder/collections
  /workspace/scripts/devtools-collection-prepare.sh

  # 2) Configure Ansible environment for Molecule
  export ANSIBLE_COLLECTIONS_PATHS=/tmp/wunder/collections

  if [ -f /workspace/ansible.cfg ]; then
    export ANSIBLE_CONFIG=/workspace/ansible.cfg
  fi

  export MOLECULE_NO_LOG="${MOLECULE_NO_LOG:-false}"

  # 3) Discover non-heavy scenarios and run molecule test -s ...
  scenarios=()
  if [ -d molecule ]; then
    for d in molecule/*; do
      if [ -d "$d" ] && [ -f "$d/molecule.yml" ]; then
        scen="$(basename "$d")"
        case "$scen" in
          *_heavy)
            echo "Skipping heavy scenario '${scen}' in devtools-molecule.sh (run manually via dedicated script)."
            continue
            ;;
        esac
        scenarios+=("$scen")
      fi
    done
  fi

  if [ "${#scenarios[@]}" -eq 0 ]; then
    echo "No non-heavy Molecule scenarios found - skipping Molecule tests."
    exit 0
  fi

  echo "Running Molecule scenarios: ${scenarios[*]}"

  for scen in "${scenarios[@]}"; do
    echo ">>> molecule test -s ${scen}"
    molecule test -s "${scen}"
  done
'
