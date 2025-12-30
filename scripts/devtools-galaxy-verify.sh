#!/usr/bin/env bash
# Lightweight Galaxy-style checks: ensure the collection builds and every role
# has meta/main.yml and a README.* present. Runs inside wunder-devtools-ee.
set -eo pipefail

COLLECTION_NAMESPACE="${COLLECTION_NAMESPACE:-lit}"

if [ -z "${COLLECTION_NAME:-}" ]; then
  if [ -f galaxy.yml ]; then
    COLLECTION_NAME="$(python3 - <<'PY'
import yaml
with open("galaxy.yml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f) or {}
print(data.get("name", ""))
PY
)"
  fi
  if [ -z "${COLLECTION_NAME:-}" ]; then
    echo "ERROR: COLLECTION_NAME not set and galaxy.yml missing 'name'." >&2
    exit 1
  fi
fi

echo "Using collection: ${COLLECTION_NAMESPACE}.${COLLECTION_NAME}"

COLLECTION_NAMESPACE="$COLLECTION_NAMESPACE" \
COLLECTION_NAME="$COLLECTION_NAME" \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -euo pipefail

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"

  echo "Building and verifying collection ${ns}.${name}..."

  # devtools-collection-prepare.sh prints the per-run collections dir on the last line
  COLLECTIONS_DIR="$(/workspace/scripts/devtools-collection-prepare.sh | tail -n 1)"

  if [ -z "${COLLECTIONS_DIR:-}" ] || [ ! -d "${COLLECTIONS_DIR}" ]; then
    echo "ERROR: COLLECTIONS_DIR not found/invalid: ${COLLECTIONS_DIR:-<empty>}" >&2
    exit 1
  fi

  coll_root="${COLLECTIONS_DIR}/ansible_collections/${ns}/${name}"
  if [ ! -d "$coll_root" ]; then
    echo "Collection root not found at $coll_root" >&2
    exit 1
  fi

  rc=0
  shopt -s nullglob
  for role_dir in "$coll_root"/roles/*; do
    [ -d "$role_dir" ] || continue
    role_name="$(basename "$role_dir")"

    meta_file="$role_dir/meta/main.yml"
    readme_file=""
    for f in "$role_dir"/README.* "$role_dir"/readme.*; do
      if [ -f "$f" ]; then
        readme_file="$f"
        break
      fi
    done

    if [ ! -f "$meta_file" ]; then
      echo "ERROR: role ${role_name} missing meta/main.yml" >&2
      rc=1
    fi

    if [ -z "$readme_file" ]; then
      echo "ERROR: role ${role_name} missing README.*" >&2
      rc=1
    fi
  done

  exit $rc
'
