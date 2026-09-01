#!/usr/bin/env bash
# shellcheck disable=SC2086,SC2154
set -eo pipefail

# Run the canonical socket-free controller parity scenario, or one explicitly named
# unmanaged scenario, inside the pinned ee-wunder-devtools-ubi9 container.
# Full dependency-backed role matrices execute in protected pipeline runners.
#
# Usage:
#   scripts/devtools-molecule.sh
#   scripts/devtools-molecule.sh <scenario_name>

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [scenario_name]" >&2
  exit 1
fi

SCENARIO_FILTER="${1:-controller-parity-basic}"
COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"
if [ "${SCENARIO_FILTER}" = controller-parity-basic ]; then
  REQUIRE_DECLARED_DEPENDENCIES=0
else
  REQUIRE_DECLARED_DEPENDENCIES=1
fi

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

# Local non-heavy scenarios are controller-only and unmanaged. The host engine
# may start the pinned Devtools container, but its socket is never mounted into
# that container. Protected Incus and managed-container scenarios belong to
# their protected pipeline runners and fail closed here.
export WUNDER_DEVTOOLS_RUN_AS_HOST_UID=1
export WUNDER_DEVTOOLS_RUN_AS_ROOT=0
export WUNDER_DEVTOOLS_PRIVILEGED=0
export WUNDER_DEVTOOLS_CAP_ADD=''
export WUNDER_DEVTOOLS_MOUNT_SOURCE_ROOT=disabled
export WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH=disabled

WUNDER_DEVTOOLS_PRIVILEGED=0 \
WUNDER_DEVTOOLS_RUN_AS_HOST_UID=1 \
WUNDER_DEVTOOLS_RUN_AS_ROOT=0 \
WUNDER_DEVTOOLS_DOCKER_SOCKET=disabled \
WUNDER_DEVTOOLS_MOUNT_SOURCE_ROOT=disabled \
WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH=disabled \
WUNDER_DEVTOOLS_NETWORK=none \
WUNDER_DEVTOOLS_ROOTFS_MODE=ro \
WUNDER_DEVTOOLS_WORKSPACE_MODE=ro \
WUNDER_DEVTOOLS_CAP_ADD='' \
COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE}" \
COLLECTION_NAME="${COLLECTION_NAME}" \
SCENARIO_FILTER="${SCENARIO_FILTER}" \
CONTAINER_HOME=/tmp/wunder \
bash scripts/wunder-devtools-ee.sh env \
  WUNDER_DEVTOOLS_OFFLINE_LOCAL_ONLY=1 \
  WUNDER_DEVTOOLS_REQUIRE_DECLARED_DEPENDENCIES="${REQUIRE_DECLARED_DEPENDENCIES}" \
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

  if [ -n "${DOCKER_HOST:-}" ] || [ -S /var/run/docker.sock ]; then
    echo "ERROR: A Docker-compatible socket must not enter the offline Devtools container." >&2
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

  # -------------------------------------------------------------
  # 3) Discover scenarios
  # -------------------------------------------------------------
  scenarios=()

  add_scenario() {
    local scen="$1"
    local explicit="${2:-false}"
    local mode_file="molecule/${scen}/.molecule-mode"
    local mode=""

    if [[ ! "${scen}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
      echo "ERROR: Unsafe Molecule scenario name: ${scen}" >&2
      exit 1
    fi

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

    python3 - "molecule/${scen}/molecule.yml" <<PY
import sys
from pathlib import Path

import yaml

path = Path(sys.argv[1])
try:
    source = path.read_text(encoding="utf-8")
except (OSError, UnicodeError):
    raise SystemExit(
        f"{path}: local offline scenario must be a readable UTF-8 file"
    ) from None
try:
    payload = yaml.safe_load(source)
except yaml.YAMLError:
    raise SystemExit(f"{path}: local offline scenario must contain valid YAML") from None
if not isinstance(payload, dict):
    raise SystemExit(f"{path}: local offline scenario must be a YAML mapping")
driver = payload.get("driver")
if not isinstance(driver, dict):
    raise SystemExit(f"{path}: local offline scenario driver must be a mapping")
platforms = payload.get("platforms")
if not isinstance(platforms, list) or not platforms:
    raise SystemExit(f"{path}: local offline scenario platforms must be a non-empty list")
if any(not isinstance(platform, dict) for platform in platforms):
    raise SystemExit(f"{path}: every local offline scenario platform must be a mapping")
if driver.get("name") != "default":
    raise SystemExit(f"{path}: local offline scenarios require driver.name=default")
if any(platform.get("managed") is not False for platform in platforms):
    raise SystemExit(f"{path}: local offline scenarios require managed=false for every platform")
PY

    scenarios+=("${scen}")
  }

  if [ -n "$scenario_filter" ]; then
    if [ -d "molecule/$scenario_filter" ] && [ -f "molecule/$scenario_filter/molecule.yml" ]; then
      add_scenario "$scenario_filter" true
    else
      printf "ERROR: Requested scenario %s not found under molecule/.\n" \
        "${scenario_filter}" >&2
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

  offline_base="${HOME}/molecule-offline-base.yml"
  molecule_ephemeral_root="${HOME}/molecule-ephemeral"
  umask 077
  mkdir -p "${molecule_ephemeral_root}"
  chmod 0700 "${molecule_ephemeral_root}"
  printf "%s\n" "prerun: false" >"${offline_base}"
  echo "Running Molecule scenarios: ${scenarios[*]}"

  for scen in "${scenarios[@]}"; do
    molecule_ephemeral_directory="${molecule_ephemeral_root}/${scen}"
    mkdir -p "${molecule_ephemeral_directory}"
    chmod 0700 "${molecule_ephemeral_directory}"
    echo ">>> molecule test -s ${scen}"
    MOLECULE_EPHEMERAL_DIRECTORY="${molecule_ephemeral_directory}" \
      molecule -c "${offline_base}" test -s "${scen}"
  done
'
