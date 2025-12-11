#!/usr/bin/env bash
set -euo pipefail

# Run ansible-lint INSIDE the wunder-devtools-ee container:
#  - build collection
#  - install collection under /tmp/wunder/collections
#  - run ansible-lint from the collection context

bash scripts/wunder-devtools-ee.sh bash -lc '
  set -e

  # Clean workspace and prepare collection
  rm -rf /tmp/wunder/.cache/ansible-compat \
         /tmp/wunder/collections \
         /tmp/wunder/lit-*.tar.gz
  /workspace/scripts/devtools-prepare-collection.sh

  # Switch into collection root and configure env
  cd /tmp/wunder/collections/ansible_collections/lit/supplementary

  export ANSIBLE_CONFIG="/workspace/ansible.cfg"
  export ANSIBLE_COLLECTIONS_PATHS="/tmp/wunder/collections"
  export ANSIBLE_LINT_OFFLINE=true
  export ANSIBLE_LINT_SKIP_GALAXY_INSTALL=1

  ansible-lint
'
