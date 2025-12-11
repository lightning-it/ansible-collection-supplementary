#!/usr/bin/env bash
set -euo pipefail

# Build and install the collection inside the wunder-devtools-ee container.
# Installs into /tmp/wunder/collections for use by other helper scripts.

rm -rf /tmp/wunder/.cache/ansible-compat \
       /tmp/wunder/collections \
       /tmp/wunder/lightning_it-*.tar.gz

ansible-galaxy collection build \
  --output-path /tmp/wunder \
  --force

ansible-galaxy collection install \
  /tmp/wunder/lightning_it-supplementary-*.tar.gz \
  -p /tmp/wunder/collections \
  --force
