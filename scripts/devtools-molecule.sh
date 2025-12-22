#!/usr/bin/env bash
set -euo pipefail

# devtools-molecule.sh
#
# Run all non-*heavy Molecule scenarios for the current collection
# INSIDE the wunder-devtools-ee container.
#
# Usage:
#   scripts/devtools-molecule.sh
#   scripts/devtools-molecule.sh chrony_rhel9_basic

# ---------------------------------------------------------------------------
# 1) Parse arguments
# ---------------------------------------------------------------------------

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [scenario_name]" >&2
  exit 1
fi

SCENARIO_FILTER="${1:-}"

# ---------------------------------------------------------------------------
# 2) Namespace + Collection name
# ---------------------------------------------------------------------------

COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"

# Try galaxy.yml first
if [ -z "${COLLECTION_NAME:-}" ] && [ -f galaxy.yml ]; then
  COLLECTION_NAME="$(python3 - <<'PY'
import yaml
try:
    with open("galaxy.yml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    name = data.get("name", "")
    if name:
        print(name)
except Exception:
    pass
PY
  )"
fi

# Fallback: derive from repo name
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
      echo "WARN: Could not infer COLLECTION_NAME from repo name '${repo_basename}', falling back to 'foundational'" >&2
      COLLECTION_NAME="foundational"
      ;;
  esac
fi

echo "Preparing Molecule tests for collection: ${COLLECTION_NAMESPACE}.${COLLECTION_NAME}"
[ -n "$SCENARIO_FILTER" ] && echo "Scenario filter: ${SCENARIO_FILTER}"

# ---------------------------------------------------------------------------
# 3) Run inside wunder-devtools-ee
# ---------------------------------------------------------------------------

# For Molecule we prefer running as root in the container to avoid UID/GID mapping issues.
export WUNDER_DEVTOOLS_RUN_AS_HOST_UID=0

WUNDER_DEVTOOLS_RUN_AS_HOST_UID=0 \
COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE}" \
COLLECTION_NAME="${COLLECTION_NAME}" \
SCENARIO_FILTER="${SCENARIO_FILTER}" \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -euo pipefail

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"
  scenario_filter="${SCENARIO_FILTER-}"

  echo "Preparing collection ${ns}.${name} for Molecule tests..."
  [ -n "$scenario_filter" ] && echo "Limiting to scenario: ${scenario_filter}"

  #
  # 0) Docker sanity check (CLI only)
  #

  echo "DEBUG: docker info inside wunder-devtools-ee..."
  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: docker info failed inside devtools container."
    exit 1
  fi

  #
  # 1) Clean potentially stale dependency installs (from galaxy.yml)
  #

  dep_paths=()
  dep_fqcns=()

  if [ -f /workspace/galaxy.yml ]; then
    while IFS= read -r line; do
      dep_paths+=("${line%::*}")
      dep_fqcns+=("${line##*::}")
    done < <(
      python3 - <<'"PY"'
import yaml, sys, os

galaxy_path = "/workspace/galaxy.yml"
try:
    if os.path.exists(galaxy_path):
        with open(galaxy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        deps = data.get("dependencies") or {}
        for fqcn in deps.keys():
            parts = fqcn.split(".")
            if len(parts) == 2:
                ns, name = parts
                path = f"/tmp/wunder/collections/ansible_collections/{ns}/{name}"
                print(f"{path}::{fqcn}")
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

  #
  # 2) Build + install collection into /tmp/wunder/collections
  #

  /workspace/scripts/devtools-collection-prepare.sh

  #
  # 2b) Install declared dependencies freshly (if any)
  #

  for dep_fqcn in "${dep_fqcns[@]}"; do
    if [ -n "$dep_fqcn" ]; then
      echo "Installing dependency ${dep_fqcn} into /tmp/wunder/collections..."
      ansible-galaxy collection install \
        "$dep_fqcn" \
        -p /tmp/wunder/collections \
        --force
    fi
  done

  #
  # 3) Configure Ansible environment for Molecule
  #

  export ANSIBLE_COLLECTIONS_PATHS=/tmp/wunder/collections

  if [ -f /workspace/ansible.cfg ]; then
    export ANSIBLE_CONFIG=/workspace/ansible.cfg
  fi

  export MOLECULE_NO_LOG="${MOLECULE_NO_LOG:-false}"
  export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"

  #
  # 4) Discover non-heavy scenarios (or apply filter) and run molecule test
  #

  scenarios=()

  if [ -n "$scenario_filter" ]; then
    # Only run a single, explicitly requested scenario
    if [ -d "molecule/$scenario_filter" ] && [ -f "molecule/$scenario_filter/molecule.yml" ]; then
      scenarios+=("$scenario_filter")
    else
      echo "ERROR: Requested scenario '"'"'$scenario_filter'"'"' not found under molecule/." >&2
      exit 1
    fi
  else
    # Discover all non-*heavy scenarios
    if [ -d molecule ]; then
      while IFS= read -r dir; do
        scen="${dir##*/}"
        case "$scen" in
          *_heavy)
            echo "Skipping heavy scenario '"'"'$scen'"'"' in devtools-molecule.sh (run manually via dedicated script)."
            ;;
          *)
            scenarios+=("$scen")
            ;;
        esac
      done < <(find molecule -maxdepth 1 -mindepth 1 -type d)
    fi
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
