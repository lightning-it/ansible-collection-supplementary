#!/usr/bin/env bash
# shellcheck disable=SC2086,SC2154
set -eo pipefail

# Run all non-*heavy Molecule scenarios for the current collection
# inside the ee-wunder-devtools-ubi9 container.
#
# Usage:
#   scripts/devtools-molecule.sh
#   scripts/devtools-molecule.sh <scenario_name>

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [scenario_name]" >&2
  exit 1
fi

SCENARIO_FILTER="${1:-}"
COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"

# Prefer authoritative name from galaxy.yml
if [ -z "${COLLECTION_NAME:-}" ] && [ -f galaxy.yml ]; then
  COLLECTION_NAME="$(scripts/devtools-galaxy.sh value name galaxy.yml)"
fi

# Fallback: derive COLLECTION_NAME from repo name (ansible-collection-<name>)
if [ -z "${COLLECTION_NAME:-}" ]; then
  if [ -n "${GITHUB_REPOSITORY:-}" ]; then
    repo_basename="${GITHUB_REPOSITORY##*/}"
  else
    repo_basename="$(basename "$PWD")"
  fi

  case "$repo_basename" in
    ansible-collection-*)
      COLLECTION_NAME="${repo_basename#ansible-collection-}"
      ;;
    *)
      echo "WARN: Could not infer COLLECTION_NAME from repo name '${repo_basename}', falling back to 'collection'" >&2
      COLLECTION_NAME="collection"
      ;;
  esac
fi

echo "Preparing Molecule tests for collection: ${COLLECTION_NAMESPACE}.${COLLECTION_NAME}"
if [ -n "${SCENARIO_FILTER}" ]; then
  echo "Scenario filter: ${SCENARIO_FILTER}"
fi

# Molecule exercises ownership transitions that require container UID 0.
# Rootless Podman maps that UID back to the invoking host user; hosted Docker
# keeps the checkout read-only so the controller cannot leave root-owned files.
export WUNDER_DEVTOOLS_RUN_AS_HOST_UID=0
export WUNDER_DEVTOOLS_PRIVILEGED=0

WUNDER_DEVTOOLS_PRIVILEGED=0 \
WUNDER_DEVTOOLS_RUN_AS_HOST_UID=0 \
WUNDER_DEVTOOLS_DOCKER_SOCKET=required \
WUNDER_DEVTOOLS_NETWORK=bridge \
WUNDER_DEVTOOLS_WORKSPACE_MODE=ro \
WUNDER_DEVTOOLS_CAP_ADD=CHOWN,DAC_OVERRIDE,FOWNER \
COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE}" \
COLLECTION_NAME="${COLLECTION_NAME}" \
SCENARIO_FILTER="${SCENARIO_FILTER}" \
CONTAINER_HOME=/tmp/wunder \
bash scripts/wunder-devtools-ee.sh env \
  MOLECULE_RUN_PROTECTED="${MOLECULE_RUN_PROTECTED:-false}" \
  INCUS_MODE="${INCUS_MODE:-}" \
  bash -c '
  set -euo pipefail

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"
  scenario_filter="${SCENARIO_FILTER:-}"
  molecule_run_protected="${MOLECULE_RUN_PROTECTED:-false}"

  protected_enabled=false
  case "${molecule_run_protected}" in
    true|TRUE|1|yes|YES)
      protected_enabled=true
      ;;
  esac

  echo "Preparing collection ${ns}.${name} for Molecule tests..."
  if [ -n "${scenario_filter}" ]; then
    echo "Limiting to scenario: ${scenario_filter}"
  fi

  echo "DEBUG: docker info inside ee-wunder-devtools-ubi9..."
  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker is required for Molecule tests but is unavailable inside the devtools container." >&2
    exit 1
  fi

  # -------------------------------------------------------------
  # 1) Build + install this collection into a per-run collections dir
  # -------------------------------------------------------------
  COLLECTIONS_DIR="$(bash /workspace/scripts/devtools-collection-prepare.sh | tail -n 1)"

  if [ -z "${COLLECTIONS_DIR:-}" ] || [ ! -d "${COLLECTIONS_DIR}" ]; then
    echo "ERROR: COLLECTIONS_DIR not found/invalid: ${COLLECTIONS_DIR:-<empty>}" >&2
    exit 1
  fi

  export ANSIBLE_COLLECTIONS_PATH="${COLLECTIONS_DIR}:/usr/share/ansible/collections"

  # -------------------------------------------------------------
  # 2) Configure Ansible env for Molecule
  # -------------------------------------------------------------
  if [ -f /workspace/ansible.cfg ]; then
    export ANSIBLE_CONFIG=/workspace/ansible.cfg
  fi

  export MOLECULE_NO_LOG="${MOLECULE_NO_LOG:-false}"
  export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"

  # -------------------------------------------------------------
  # 3) Discover scenarios
  # -------------------------------------------------------------
  scenarios=()

  add_scenario() {
    local scen="$1"
    local explicit="${2:-false}"
    local mode_file="molecule/${scen}/.molecule-mode"
    local mode=""

    if [ -f "${mode_file}" ]; then
      mode="$(tr -d "[:space:]" < "${mode_file}")"
    fi

    if [ ! -f "molecule/${scen}/molecule.yml" ]; then
      echo "Skipping Molecule helper directory '${scen}' (no molecule.yml)."
      return
    fi

    case "${mode}" in
      protected-incus)
        if [ "${protected_enabled}" != "true" ]; then
          if [ "${explicit}" = "true" ]; then
            echo "ERROR: Scenario '\''${scen}'\'' is protected; set MOLECULE_RUN_PROTECTED=true to run it." >&2
            exit 1
          fi
          echo "Skipping protected Incus scenario '\''${scen}'\'' (set MOLECULE_RUN_PROTECTED=true to run)."
          return
        fi

        if ! command -v incus >/dev/null 2>&1; then
          echo "ERROR: Scenario '\''${scen}'\'' requires the incus CLI inside the devtools container." >&2
          exit 1
        fi
        ;;
    esac

    scenarios+=("${scen}")
  }

  if [ -n "$scenario_filter" ]; then
    if [ -d "molecule/$scenario_filter" ] && [ -f "molecule/$scenario_filter/molecule.yml" ]; then
      add_scenario "$scenario_filter" true
    else
      echo "ERROR: Requested scenario '${scenario_filter}' not found under molecule/." >&2
      exit 1
    fi
  else
    if [ -d molecule ]; then
      while IFS= read -r dir; do
        scen="${dir##*/}"
        case "$scen" in
          *_heavy)
            echo "Skipping heavy scenario '\''${scen}'\'' in devtools-molecule.sh (run manually via dedicated script)."
            ;;
          *)
            add_scenario "$scen"
            ;;
        esac
      done < <(find molecule -maxdepth 1 -mindepth 1 -type d)
    fi
  fi

  if [ "${#scenarios[@]}" -eq 0 ]; then
    echo "No Molecule scenarios found (non-heavy)."
    exit 0
  fi

  echo "Running Molecule scenarios: ${scenarios[*]}"

  for scen in "${scenarios[@]}"; do
    echo ">>> molecule test -s ${scen}"
    molecule test -s "${scen}"
  done
'
