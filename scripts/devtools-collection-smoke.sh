#!/usr/bin/env bash
set -euo pipefail

# Run a full collection smoke test INSIDE the wunder-devtools-ee container:
#  - build the collection
#  - install it into /tmp/wunder/collections
#  - run the example playbook using the installed FQCN

bash scripts/wunder-devtools-ee.sh bash -lc '
  set -e

  # Clean previous build + install
  rm -rf /tmp/wunder/collections \
         /tmp/wunder/lit-*.tar.gz

  # Build collection from /workspace (mounted repo)
  ansible-galaxy collection build \
    --output-path /tmp/wunder \
    --force

  # Install built collection into /tmp/wunder/collections
  ansible-galaxy collection install \
    /tmp/wunder/lit-supplementary-*.tar.gz \
    -p /tmp/wunder/collections \
    --force

  # Use installed collection via ANSIBLE_COLLECTIONS_PATHS
  export ANSIBLE_COLLECTIONS_PATHS=/tmp/wunder/collections

  ansible-playbook \
    -i localhost, \
    playbooks/keycloak_config_example.yml
'
