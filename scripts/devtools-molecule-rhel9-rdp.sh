#!/usr/bin/env bash
set -euo pipefail

# This script runs an RHEL9 Vagrant VM and executes the rhel9-rdp Molecule
# scenario inside the wunder-devtools-ee container.
#
# It is intended as a **manual** heavy-weight scenario:
# - requires Vagrant
# - requires a working provider (e.g. VirtualBox/VMware/libvirt)
#
# It is safe to call even on systems without a provider: in that case it will
# print a note and exit 0 without running anything.

# 0) Check if vagrant is available at all
if ! command -v vagrant >/dev/null 2>&1; then
  echo "NOTE: vagrant is not installed. Skipping rhel9-rdp scenario."
  exit 0
fi

# 1) VM start (but first check provider availability)
pushd vagrant/rhel9 >/dev/null

if ! vagrant status >/dev/null 2>&1; then
  echo "NOTE: Vagrant is installed, but no usable provider is available."
  echo "      Install a provider (e.g. VirtualBox/VMware/libvirt) if you want"
  echo "      to run the rhel9-rdp scenario. Skipping for now."
  popd >/dev/null
  exit 0
fi

vagrant up
popd >/dev/null

# 2) Molecule (inside wunder-devtools-ee)
ANSIBLE_COLLECTIONS_PATHS="$PWD" \
ANSIBLE_ROLES_PATH="$PWD/roles" \
bash scripts/wunder-devtools-ee.sh \
  molecule test -s rhel9-rdp

# 3) VM destroy
pushd vagrant/rhel9 >/dev/null
vagrant destroy -f
popd >/dev/null
