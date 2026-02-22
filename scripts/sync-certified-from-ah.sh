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

token="$(printf '%s' "${token}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
if [[ "${token}" == RH_AUTOMATION_HUB_TOKEN:* ]]; then
  token="${token#RH_AUTOMATION_HUB_TOKEN:}"
  token="$(printf '%s' "${token}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
fi

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
  auth_headers+=("${token}")
  auth_scheme_names+=("${token%% *}")
else
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

get_latest_version_for_collection() {
  local namespace="$1"
  local collection="$2"
  local current_base
  local url
  local http_code
  local -a all_versions=()
  local -a page_versions=()

  for current_base in "${api_bases[@]}"; do
    url="${current_base}/${namespace}/${collection}/versions/?limit=1000"
    http_code="$(request_with_auth_header "${resolved_auth_header}" "${url}")"

    case "${http_code}" in
      200)
        mapfile -t page_versions < <(
          python3 - <<'PY' "${tmp_response}" 2>/dev/null
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

versions = set()

def walk(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"version", "highest_version", "latest_version"} and isinstance(value, str):
                value = value.strip()
                if value:
                    versions.add(value)
            walk(value)
    elif isinstance(node, list):
        for value in node:
            walk(value)

walk(data)
for version in sorted(versions):
    print(version)
PY
        )
        if [[ ${#page_versions[@]} -gt 0 ]]; then
          while IFS= read -r parsed_version; do
            if [[ "${parsed_version}" =~ ^[0-9][0-9A-Za-z._-]*$ ]]; then
              all_versions+=("${parsed_version}")
            fi
          done < <(printf '%s\n' "${page_versions[@]}")
        fi
        ;;
      401|403)
        echo "Authentication/authorization failed for Automation Hub API (${http_code})." >&2
        cat "${tmp_response}" >&2 || true
        echo "Auth header used: ${resolved_auth_header}" >&2
        exit 1
        ;;
      404)
        ;;
      *)
        echo "ERROR: Unexpected response ${http_code} while listing ${namespace}.${collection} at ${current_base}" >&2
        cat "${tmp_response}" >&2 || true
        exit 1
        ;;
    esac
  done

  if [[ ${#all_versions[@]} -eq 0 ]]; then
    return 1
  fi

  printf '%s\n' "${all_versions[@]}" | awk 'NF > 0' | sort -Vu | tail -n1
}

probe_url=""
first_dep="${deps[0]}"
first_name="${first_dep%% *}"
first_namespace="${first_name%%.*}"
first_collection="${first_name#*.}"
probe_url="${api_bases[0]}/${first_namespace}/${first_collection}/versions/"

if ! resolve_auth_header "${probe_url}"; then
  echo "Authentication/authorization failed for Automation Hub API." >&2
  if [[ -n "${resolved_auth_failure_code}" ]]; then
    echo "HTTP status: ${resolved_auth_failure_code}" >&2
  fi
  if [[ -n "${resolved_auth_failure_body}" ]]; then
    printf '%s\n' "${resolved_auth_failure_body}" >&2
  fi
  echo "Tried auth schemes: ${auth_scheme_names[*]}" >&2
  exit 1
fi

updates_file="$(mktemp)"
trap 'rm -f "${tmp_response}" "${updates_file}"' EXIT

failures=0
changes=0

for dep in "${deps[@]}"; do
  name="${dep%% *}"
  current_version="${dep#* }"
  namespace="${name%%.*}"
  collection="${name#*.}"

  latest_version="$(get_latest_version_for_collection "${namespace}" "${collection}" || true)"
  if [[ -z "${latest_version}" ]]; then
    echo "MISSING: ${name} has no resolvable versions on Automation Hub." >&2
    failures=$((failures + 1))
    continue
  fi

  if [[ "${latest_version}" != "${current_version}" ]]; then
    printf '%s\t%s\n' "${name}" "${latest_version}" >> "${updates_file}"
    echo "SYNC: ${name} ${current_version} -> ${latest_version}"
    changes=$((changes + 1))
  else
    echo "OK: ${name}:${current_version}"
  fi
done

if [[ ${failures} -gt 0 ]]; then
  echo "Automation Hub sync failed for ${failures} dependency(ies)." >&2
  exit 1
fi

if [[ ${changes} -eq 0 ]]; then
  echo "No updates needed for ${requirements_file}."
  exit 0
fi

tmp_updated="$(mktemp)"
awk -v updates_file="${updates_file}" '
  BEGIN {
    while ((getline < updates_file) > 0) {
      split($0, row, "\t")
      desired[row[1]] = row[2]
    }
  }
  {
    if (match($0, /^[[:space:]]*-[[:space:]]*name:[[:space:]]*([^[:space:]]+)/, m)) {
      current_name = m[1]
      gsub(/["\047]/, "", current_name)
      print
      next
    }
    if (match($0, /^[[:space:]]*version:[[:space:]]*["\047]?([^"\047[:space:]]+)["\047]?[[:space:]]*$/, m) && (current_name in desired)) {
      indent = ""
      if (match($0, /^[[:space:]]+/)) {
        indent = substr($0, RSTART, RLENGTH)
      }
      print indent "version: \"" desired[current_name] "\""
      next
    }
    print
  }
' "${requirements_file}" > "${tmp_updated}"

mv "${tmp_updated}" "${requirements_file}"
echo "Updated ${requirements_file} with ${changes} version change(s)."
