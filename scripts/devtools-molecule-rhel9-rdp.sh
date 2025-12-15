#!/usr/bin/env bash
set -euo pipefail

# This script is intended to be run from the repo root.
# It will:
#  1) Start the RHEL9 Vagrant VM
#  2) Run the rhel9-rdp Molecule scenario via wunder-devtools-ee
#  3) Destroy the VM again

# 1) VM start
pushd vagrant/rhel9 >/dev/null
vagrant up
popd >/dev/null

# 2) Molecule (inside wunder-devtools-ee container)
ANSIBLE_COLLECTIONS_PATH="$PWD" \
ANSIBLE_ROLES_PATH="$PWD/roles" \
bash scripts/wunder-devtools-ee.sh \
  molecule test -s rhel9-rdp

# 3) VM destroy
pushd vagrant/rhel9 >/dev/null
vagrant destroy -f
popd >/dev/null
