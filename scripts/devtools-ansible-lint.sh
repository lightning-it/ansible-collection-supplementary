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

if [ -z "${ANSIBLE_CORE_VERSION:-}" ] || [ -z "${ANSIBLE_LINT_VERSION:-}" ]; then
  echo "ERROR: ANSIBLE_CORE_VERSION and ANSIBLE_LINT_VERSION must be set." >&2
  exit 1
fi

echo "Running ansible-lint for collection: ${COLLECTION_NAMESPACE}.${COLLECTION_NAME}"
echo "Using ansible-core ${ANSIBLE_CORE_VERSION}, ansible-lint ${ANSIBLE_LINT_VERSION}"

# 3) Run inside the wunder-devtools-ee container
COLLECTION_NAMESPACE="$COLLECTION_NAMESPACE" \
COLLECTION_NAME="$COLLECTION_NAME" \
ANSIBLE_CORE_VERSION="${ANSIBLE_CORE_VERSION}" \
ANSIBLE_LINT_VERSION="${ANSIBLE_LINT_VERSION}" \
bash scripts/wunder-devtools-ee.sh bash -lc '
  set -e

  ns="${COLLECTION_NAMESPACE}"
  name="${COLLECTION_NAME}"

  echo "Building and installing collection ${ns}.${name}..."
  # 1) Build + install collection into /tmp/wunder/collections
  /workspace/scripts/devtools-collection-prepare.sh

  coll_root="/tmp/wunder/collections/ansible_collections/${ns}/${name}"
  if [ ! -d "$coll_root" ]; then
    echo "Collection root not found at $coll_root" >&2
    exit 1
  fi

  # 2) Switch into installed collection root
  cd "$coll_root"

  # 3) Use versions passed from CI (with defaults)
  core_ver="${ANSIBLE_CORE_VERSION}"
  lint_ver="${ANSIBLE_LINT_VERSION}"

  python3 -m pip install --upgrade \
    "ansible-core==${core_ver}" \
    "ansible-lint==${lint_ver}"

  export ANSIBLE_CONFIG="/workspace/ansible.cfg"
  export ANSIBLE_COLLECTIONS_PATHS="/tmp/wunder/collections"
  export ANSIBLE_LINT_OFFLINE=true
  export ANSIBLE_LINT_SKIP_GALAXY_INSTALL=1

  echo "Running ansible-lint in ${coll_root}..."
  ansible-lint
'
