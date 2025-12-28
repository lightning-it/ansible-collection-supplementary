#!/usr/bin/env bash
set -eo pipefail

# Run all non-*heavy Molecule scenarios for the current collection
# inside the wunder-devtools-ee container.
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

# For Molecule (Docker + delegated etc.) we run as root inside the container
# so that the Docker SDK sees a valid /etc/passwd entry and can reach the socket.
export WUNDER_DEVTOOLS_RUN_AS_HOST_UID=0

WUNDER_DEVTOOLS_RUN_AS_HOST_UID=0 \
COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE}" \
COLLECTION_NAME="${COLLECTION_NAME}" \
SCENARIO_FILTER="${SCENARIO_FILTER}" \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -euo pipefail

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"
  scenario_filter="${SCENARIO_FILTER:-}"

  echo "Preparing collection ${ns}.${name} for Molecule tests..."
  if [ -n "${scenario_filter}" ]; then
    echo "Limiting to scenario: ${scenario_filter}"
  fi

  echo "DEBUG: docker info inside wunder-devtools-ee..."
  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: docker info failed inside devtools container."
    exit 1
  fi

  # -------------------------------------------------------------
  # 1) Clean potentially stale dependency installs
  #    so we can re-install galaxy.yml dependencies cleanly
  # -------------------------------------------------------------
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
      chmod -R u+w "$dep_path" 2>/dev/null || true
      rm -rf "$dep_path" 2>/dev/null || true
      if [ -d "$dep_path" ]; then
        python3 - "$dep_path" <<'PY'
import shutil
import sys
import os

paths = sys.argv[1:]
for p in paths:
    if os.path.exists(p):
        shutil.rmtree(p, ignore_errors=True)
PY
        rm -rf "$dep_path" 2>/dev/null || true
      fi
    fi
  done

  # -------------------------------------------------------------
  # 2) Build + install collection into /tmp/wunder/collections
  # -------------------------------------------------------------
  /workspace/scripts/devtools-collection-prepare.sh

  # 2b) Install declared dependencies freshly (if any)
  for dep_fqcn in "${dep_fqcns[@]}"; do
    if [ -n "$dep_fqcn" ]; then
      echo "Installing dependency ${dep_fqcn} into /tmp/wunder/collections..."
      ansible-galaxy collection install \
        "$dep_fqcn" \
        -p /tmp/wunder/collections \
        --force
    fi
  done

  # -------------------------------------------------------------
  # 3) Configure Ansible env for Molecule
  # -------------------------------------------------------------
  export ANSIBLE_COLLECTIONS_PATHS=/tmp/wunder/collections

  if [ -f /workspace/ansible.cfg ]; then
    export ANSIBLE_CONFIG=/workspace/ansible.cfg
  fi

  export MOLECULE_NO_LOG="${MOLECULE_NO_LOG:-false}"
  # Inside the container the Docker socket is mounted at /var/run/docker.sock
  export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"

  # -------------------------------------------------------------
  # 4) Discover scenarios
  #    - If SCENARIO_FILTER is set, run only that one
  #    - Otherwise, run all non-*heavy scenarios
  # -------------------------------------------------------------
  scenarios=()

  if [ -n "$scenario_filter" ]; then
    if [ -d "molecule/$scenario_filter" ] && [ -f "molecule/$scenario_filter/molecule.yml" ]; then
      scenarios+=("$scenario_filter")
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
            echo "Skipping heavy scenario '${scen}' in devtools-molecule.sh (run manually via dedicated script)."
            ;;
          *)
            scenarios+=("$scen")
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
