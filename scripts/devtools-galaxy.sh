#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage:
  scripts/devtools-galaxy.sh value <key> [galaxy.yml]
  scripts/devtools-galaxy.sh dependencies [galaxy.yml]
USAGE
}

galaxy_value() {
  local key="$1"
  local file="$2"
  awk -v key="$key" '
    BEGIN { found=0 }
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    {
      line=$0
      sub(/^[[:space:]]+/, "", line)
      if (line ~ ("^" key ":[[:space:]]*")) {
        val=line
        sub(("^" key ":[[:space:]]*"), "", val)
        sub(/[[:space:]]+#.*$/, "", val)
        gsub(/^["\047]|["\047]$/, "", val)
        print val
        found=1
        exit
      }
    }
    END {
      if (!found) {
        exit 1
      }
    }
  ' "$file"
}

galaxy_dependencies() {
  local file="$1"
  awk '
    BEGIN { in_deps=0 }
    {
      raw=$0
      line=raw
      sub(/^[[:space:]]+/, "", line)

      if (line ~ /^#/ || line ~ /^$/) {
        next
      }

      if (!in_deps && line ~ /^dependencies:[[:space:]]*$/) {
        in_deps=1
        next
      }

      if (in_deps) {
        if (raw ~ /^[^[:space:]]/) {
          in_deps=0
          next
        }

        dep=line
        if (dep ~ /^#/ || dep ~ /^$/) {
          next
        }

        if (dep !~ /^[A-Za-z0-9_.-]+:[[:space:]]*/) {
          next
        }

        key=dep
        sub(/:.*/, "", key)

        val=dep
        sub(/^[^:]+:[[:space:]]*/, "", val)
        sub(/[[:space:]]+#.*$/, "", val)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", val)
        gsub(/["\047]/, "", val)

        if (val == "" || val == "*" || val == "null" || val == "~") {
          print key
        } else {
          print key ":" val
        }
      }
    }
  ' "$file"
}

main() {
  local cmd="${1:-}"
  case "$cmd" in
    value)
      if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
        usage
        exit 2
      fi
      local key="$2"
      local file="${3:-galaxy.yml}"
      galaxy_value "$key" "$file"
      ;;
    dependencies)
      if [ "$#" -gt 2 ]; then
        usage
        exit 2
      fi
      local file="${2:-galaxy.yml}"
      galaxy_dependencies "$file"
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
