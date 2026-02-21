#!/usr/bin/env bash
set -euo pipefail

requirements_file="${1:-collections/requirements-certified.yml}"
api_base="${AUTOMATION_HUB_API_BASE:-}"
api_base_template="${AUTOMATION_HUB_API_BASE_TEMPLATE:-https://console.redhat.com/api/automation-hub/content/{repo}/v3/plugin/ansible/content/{repo}/collections/index}"
api_repositories="${AUTOMATION_HUB_REPOSITORIES:-published,validated}"
token="${AUTOMATION_HUB_TOKEN:-}"
sso_token_url="${AUTOMATION_HUB_SSO_TOKEN_URL:-https://sso.redhat.com/auth/realms/redhat-external/protocol/openid-connect/token}"
sso_client_id="${AUTOMATION_HUB_SSO_CLIENT_ID:-cloud-services}"
sso_exchange_enabled="${AUTOMATION_HUB_EXCHANGE_OFFLINE_TOKEN:-true}"

if [[ -z "${token}" ]]; then
  echo "AUTOMATION_HUB_TOKEN is required." >&2
  exit 2
fi

if [[ ! -f "${requirements_file}" ]]; then
  echo "Requirements file not found: ${requirements_file}" >&2
  exit 2
fi

declare -a api_bases=()
if [[ -n "${api_base}" ]]; then
  api_bases+=("${api_base%/}")
else
  IFS=',' read -r -a repo_candidates <<< "${api_repositories}"
  for repo_name in "${repo_candidates[@]}"; do
    repo_name="$(printf '%s' "${repo_name}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    if [[ -n "${repo_name}" ]]; then
      resolved_base="${api_base_template//\{repo\}/${repo_name}}"
      api_bases+=("${resolved_base%/}")
    fi
  done
fi

if [[ ${#api_bases[@]} -eq 0 ]]; then
  echo "No Automation Hub API base configured." >&2
  exit 2
fi

# Normalize token formatting.
token="$(printf '%s' "${token}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"

# Handle accidentally prefixed secret format:
# RH_AUTOMATION_HUB_TOKEN:<jwt>
if [[ "${token}" == RH_AUTOMATION_HUB_TOKEN:* ]]; then
  token="${token#RH_AUTOMATION_HUB_TOKEN:}"
  token="$(printf '%s' "${token}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
fi

# If the token looks like a JWT refresh/offline token, try exchanging it for an
# access token accepted by Automation Hub APIs.
if [[ "${sso_exchange_enabled}" == "true" && "${token}" == *.*.* ]]; then
  token_exchange_response="$(mktemp)"
  exchange_http_code="$(
    curl -sS \
      -o "${token_exchange_response}" \
      -w "%{http_code}" \
      -X POST \
      -H "Content-Type: application/x-www-form-urlencoded" \
      --data-urlencode "grant_type=refresh_token" \
      --data-urlencode "client_id=${sso_client_id}" \
      --data-urlencode "refresh_token=${token}" \
      "${sso_token_url}" || true
  )"

  if [[ "${exchange_http_code}" == "200" ]]; then
    exchanged_access_token="$(
      python3 - <<'PY' "${token_exchange_response}" 2>/dev/null
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
print(data.get("access_token", ""))
PY
    )"
    if [[ -n "${exchanged_access_token}" ]]; then
      token="${exchanged_access_token}"
      echo "INFO: Exchanged Red Hat offline token for access token."
    fi
  fi

  rm -f "${token_exchange_response}" || true
fi

declare -a auth_headers=()
declare -a auth_scheme_names=()
if [[ "${token}" =~ ^(Bearer|Token)[[:space:]]+.+$ ]]; then
  # Already includes an auth scheme.
  auth_headers+=("${token}")
  auth_scheme_names+=("${token%% *}")
else
  # Try both common schemes used by Red Hat APIs/gateways.
  auth_headers+=("Bearer ${token}")
  auth_headers+=("Token ${token}")
  auth_scheme_names+=("Bearer" "Token")
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
  probe_url="${api_bases[0]}/${namespace}/${collection}/versions/${version}/"

  if [[ -z "${resolved_auth_header}" ]]; then
    if ! resolve_auth_header "${probe_url}"; then
      echo "Authentication/authorization failed for Automation Hub API." >&2
      if [[ -n "${resolved_auth_failure_code}" ]]; then
        echo "HTTP status: ${resolved_auth_failure_code}" >&2
      fi
      if [[ -n "${resolved_auth_failure_body}" ]]; then
        printf '%s\n' "${resolved_auth_failure_body}" >&2
      fi
      echo "Tried auth schemes: ${auth_scheme_names[*]}" >&2
      echo "Set RH_AUTOMATION_HUB_TOKEN to a valid token from cloud.redhat.com Automation Hub token management." >&2
      exit 1
    fi
  fi

  found_in_base=""
  unexpected_error=false

  for current_base in "${api_bases[@]}"; do
    url="${current_base}/${namespace}/${collection}/versions/${version}/"
    http_code="$(request_with_auth_header "${resolved_auth_header}" "${url}")"

    case "${http_code}" in
      200)
        found_in_base="${current_base}"
        break
        ;;
      401|403)
        echo "Authentication/authorization failed for Automation Hub API (${http_code})." >&2
        cat "${tmp_response}" >&2 || true
        echo "Auth header used: ${resolved_auth_header}" >&2
        exit 1
        ;;
      404)
        # Try next configured repository base.
        ;;
      *)
        echo "ERROR: Unexpected response ${http_code} for ${name}:${version} at ${current_base}" >&2
        cat "${tmp_response}" >&2 || true
        failures=$((failures + 1))
        unexpected_error=true
        break
        ;;
    esac
  done

  if [[ -n "${found_in_base}" ]]; then
    echo "OK: ${name}:${version}"
    continue
  fi

  if [[ "${unexpected_error}" == "true" ]]; then
    continue
  fi

  echo "MISSING: ${name}:${version} is not available on Automation Hub." >&2
  failures=$((failures + 1))
done

if [[ ${failures} -gt 0 ]]; then
  echo "Automation Hub validation failed for ${failures} dependency(ies)." >&2
  exit 1
fi

echo "Automation Hub validation succeeded for all certified dependencies."
