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

# Normalize token value in case it was pasted with whitespace/newline artifacts.
token="$(printf '%s' "${token}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"

declare -a auth_headers=()
if [[ "${token}" =~ ^(Bearer|Token)[[:space:]]+.+$ ]]; then
  # If caller already provided auth scheme, keep it verbatim.
  auth_headers+=("${token}")
else
  # Try both common schemes used across Red Hat endpoints.
  auth_headers+=("Bearer ${token}")
  auth_headers+=("Token ${token}")
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

resolved_auth_header=""
resolved_http_code=""
resolved_auth_failure_code=""
resolved_auth_failure_body=""

request_with_auth_header() {
  local header="$1"
  local url="$2"

  curl -sS \
    -o "${tmp_response}" \
    -w "%{http_code}" \
    -H "Authorization: ${header}" \
    "${url}"
}

resolve_auth_header() {
  local url="$1"
  local header
  local http_code

  resolved_http_code=""
  resolved_auth_failure_code=""
  resolved_auth_failure_body=""

  for header in "${auth_headers[@]}"; do
    http_code="$(request_with_auth_header "${header}" "${url}")"

    if [[ "${http_code}" != "401" && "${http_code}" != "403" ]]; then
      resolved_auth_header="${header}"
      resolved_http_code="${http_code}"
      return 0
    fi

    if [[ -z "${resolved_auth_failure_code}" ]]; then
      resolved_auth_failure_code="${http_code}"
      resolved_auth_failure_body="$(cat "${tmp_response}" 2>/dev/null || true)"
    fi
  done

  return 1
}

for dep in "${deps[@]}"; do
  name="${dep%% *}"
  version="${dep#* }"
  namespace="${name%%.*}"
  collection="${name#*.}"
  url="${api_base}/${namespace}/${collection}/versions/${version}/"

  if [[ -z "${resolved_auth_header}" ]]; then
    if ! resolve_auth_header "${url}"; then
      echo "Authentication/authorization failed for Automation Hub API." >&2
      if [[ -n "${resolved_auth_failure_code}" ]]; then
        echo "HTTP status: ${resolved_auth_failure_code}" >&2
      fi
      if [[ -n "${resolved_auth_failure_body}" ]]; then
        printf '%s\n' "${resolved_auth_failure_body}" >&2
      fi
      echo "Tried auth schemes: ${auth_headers[*]}" >&2
      echo "Set RH_AUTOMATION_HUB_TOKEN to a valid token from cloud.redhat.com Automation Hub token management." >&2
      exit 1
    fi
    http_code="${resolved_http_code}"
  else
    http_code="$(request_with_auth_header "${resolved_auth_header}" "${url}")"
  fi

  case "${http_code}" in
    200)
      echo "OK: ${name}:${version}"
      ;;
    401|403)
      echo "Authentication/authorization failed for Automation Hub API (${http_code})." >&2
      cat "${tmp_response}" >&2 || true
      echo "Auth header used: ${resolved_auth_header}" >&2
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
