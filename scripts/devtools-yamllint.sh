#!/usr/bin/env bash
set -euo pipefail

image="quay.io/l-it/ee-wunder-devtools-ubi9:v1.8.3"
batch_size=200

collect_yaml_files() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git ls-files --cached -- '*.yml' '*.yaml'
    return
  fi

  rg --files -g '*.yml' -g '*.yaml'
}

run_with_engine() {
  local engine="$1"
  shift
  local mount_flag=""
  if [ "$engine" = "podman" ]; then
    mount_flag=":Z"
  fi

  printf '%s\n' "$@" | "$engine" run --rm -i \
    -v "$PWD":/workspace"${mount_flag}" \
    -w /workspace \
    "$image" \
    bash -lc '
      set -euo pipefail
      mapfile -t yaml_args
      if [ "${#yaml_args[@]}" -eq 0 ]; then
        exit 0
      fi
      yamllint "${yaml_args[@]}"
    '
}

if [ "$#" -eq 0 ]; then
  mapfile -t yaml_args < <(collect_yaml_files)
else
  yaml_args=("$@")
fi

if [ "${#yaml_args[@]}" -eq 0 ]; then
  exit 0
fi

engine=""
if command -v podman >/dev/null 2>&1 && podman info >/dev/null 2>&1; then
  engine="podman"
elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  engine="docker"
fi

if [ -z "$engine" ] && { [ "${CI:-false}" = "true" ] || [ "${GITHUB_ACTIONS:-false}" = "true" ]; }; then
  echo "ERROR: yamllint requires podman or docker in CI." >&2
  exit 1
fi

if [ -z "$engine" ]; then
  echo "Skipping yamllint locally because neither podman nor docker is available." >&2
  exit 0
fi

for ((offset = 0; offset < ${#yaml_args[@]}; offset += batch_size)); do
  batch=("${yaml_args[@]:offset:batch_size}")
  run_with_engine "$engine" "${batch[@]}"
done
