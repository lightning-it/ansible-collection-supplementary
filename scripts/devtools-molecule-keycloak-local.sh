#!/usr/bin/env bash
set -euo pipefail

# Run from HOST: inside wunder-devtools-ee we:
#  - build the lightning_it.supplementary collection from /workspace
#  - install it into /tmp/wunder/collections
#  - run molecule test -s keycloak-local with the collection path set

bash scripts/wunder-devtools-ee.sh bash -lc '
  set -e

  # 1) Clean temporary collection workspace
  rm -rf /tmp/wunder/.cache/ansible-compat \
         /tmp/wunder/collections \
         /tmp/wunder/lightning_it-*.tar.gz

  # 2) Build collection from /workspace (mounted repo)
  ansible-galaxy collection build \
    --output-path /tmp/wunder \
    --force

  # 3) Install built collection into /tmp/wunder/collections
  ansible-galaxy collection install \
    /tmp/wunder/lightning_it-supplementary-*.tar.gz \
    -p /tmp/wunder/collections \
    --force

  # 4) Configure env for Molecule
  export ANSIBLE_CONFIG="/workspace/ansible.cfg"
  export ANSIBLE_COLLECTIONS_PATHS="/tmp/wunder/collections"

  # 5) Run the keycloak-local Molecule scenario
  molecule test -s keycloak-local
'
