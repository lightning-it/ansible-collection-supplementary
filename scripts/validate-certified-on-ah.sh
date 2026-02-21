#!/usr/bin/env bash
set -euo pipefail

requirements_file="${1:-collections/requirements-certified.yml}"
api_base="${AUTOMATION_HUB_API_BASE:-https://console.redhat.com/api/automation-hub/content/published/v3/plugin/ansible/content/published/collections/index}"
token="${AUTOMATION_HUB_TOKEN:-}"

if [[ -z "${token}" ]]; then
  echo "AUTOMATION_HUB_TOKEN is required." >&2
  exit 2
fi

if [[ ! -f "${requirements_file}" ]]; then
  echo "Requirements file not found: ${requirements_file}" >&2
  exit 2
fi

mapfile -t deps < <(
  awk '
    match($0, /^[[:space:]]*-[[:space:]]*name:[[:space:]]*([^[:space:]]+)/, m) {
      name = m[1]
      gsub(/["\047]/, "", name)
      next
    }
    match($0, /^[[:space:]]*version:[[:space:]]*([^[:space:]]+)/, m) {
      version = m[1]
      gsub(/["\047]/, "", version)
      if (name ~ /^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$/) {
        print name " " version
      }
    }
  ' "${requirements_file}"
)

if [[ ${#deps[@]} -eq 0 ]]; then
  echo "No collection dependencies parsed from ${requirements_file}" >&2
  exit 2
fi

failures=0
tmp_response="$(mktemp)"
trap 'rm -f "${tmp_response}"' EXIT

for dep in "${deps[@]}"; do
  name="${dep%% *}"
  version="${dep#* }"
  namespace="${name%%.*}"
  collection="${name#*.}"
  url="${api_base}/${namespace}/${collection}/versions/${version}/"

  http_code="$(
    curl -sS \
      -o "${tmp_response}" \
      -w "%{http_code}" \
      -H "Authorization: Bearer ${token}" \
      "${url}"
  )"

  case "${http_code}" in
    200)
      echo "OK: ${name}:${version}"
      ;;
    401|403)
      echo "Authentication/authorization failed for Automation Hub API (${http_code})." >&2
      cat "${tmp_response}" >&2 || true
      exit 1
      ;;
    404)
      echo "MISSING: ${name}:${version} is not available on Automation Hub." >&2
      failures=$((failures + 1))
      ;;
    *)
      echo "ERROR: Unexpected response ${http_code} for ${name}:${version}" >&2
      cat "${tmp_response}" >&2 || true
      failures=$((failures + 1))
      ;;
  esac
done

if [[ ${failures} -gt 0 ]]; then
  echo "Automation Hub validation failed for ${failures} dependency(ies)." >&2
  exit 1
fi

echo "Automation Hub validation succeeded for all certified dependencies."
