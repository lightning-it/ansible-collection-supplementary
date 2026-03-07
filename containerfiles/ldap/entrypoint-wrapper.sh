#!/usr/bin/env bash
set -euo pipefail

: "${LDAP_INSTANCE:=localhost}"
: "${LDAP_PORT:=3389}"
: "${LDAP_BASE_DN:=${DS_SUFFIX:-dc=wunderbox,dc=local}}"
: "${LDAP_DM_DN:=cn=Directory Manager}"
: "${LDAP_BOOTSTRAP_MARKER:=/data/.bootstrap_done}"
: "${LDAP_SEED_LDIF:=/opt/wunderbox/bootstrap/seed.ldif}"

if [ -n "${DS_DM_PASSWORD_FILE:-}" ] && [ -f "${DS_DM_PASSWORD_FILE}" ]; then
  export DS_DM_PASSWORD
  DS_DM_PASSWORD="$(tr -d '\r\n' < "${DS_DM_PASSWORD_FILE}")"
fi

: "${LDAP_DM_PASSWORD:=${DS_DM_PASSWORD:-}}"
if [ -z "${LDAP_DM_PASSWORD}" ]; then
  echo "ERROR: LDAP DM password is missing. Set DS_DM_PASSWORD or DS_DM_PASSWORD_FILE." >&2
  exit 1
fi

find_ldap_start_cmd() {
  local cmd
  for cmd in \
    /usr/libexec/dirsrv/dscontainer \
    /usr/sbin/dscontainer \
    /usr/local/sbin/dscontainer \
    /entrypoint.sh \
    /usr/local/bin/docker-entrypoint.sh
  do
    if [ -x "${cmd}" ]; then
      echo "${cmd}"
      return 0
    fi
  done

  if command -v dscontainer >/dev/null 2>&1; then
    command -v dscontainer
    return 0
  fi

  return 1
}

start_ldap() {
  local start_cmd
  start_cmd="$(find_ldap_start_cmd)" || {
    echo "ERROR: Could not locate original 389ds startup command." >&2
    exit 1
  }

  echo "Starting 389ds via: ${start_cmd}"
  "${start_cmd}" "$@" &
  LDAP_PID=$!
}

wait_for_ldap() {
  local i
  for i in $(seq 1 120); do
    if ldapsearch -x \
      -H "ldap://127.0.0.1:${LDAP_PORT}" \
      -D "${LDAP_DM_DN}" \
      -w "${LDAP_DM_PASSWORD}" \
      -b '' -s base namingContexts >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  echo "ERROR: Timed out waiting for 389ds on ldap://127.0.0.1:${LDAP_PORT}" >&2
  return 1
}

ensure_memberof_plugin() {
  dsconf localhost plugin memberof enable || true
  dsconf localhost plugin memberof set --scope "${LDAP_BASE_DN}" || true

  ldapmodify -x \
    -H "ldap://127.0.0.1:${LDAP_PORT}" \
    -D "${LDAP_DM_DN}" \
    -w "${LDAP_DM_PASSWORD}" <<LDIF || true
dn: cn=MemberOf Plugin,cn=plugins,cn=config
changetype: modify
replace: memberOfSkipNested
memberOfSkipNested: off
LDIF
}

seed_directory_if_needed() {
  if [ -f "${LDAP_BOOTSTRAP_MARKER}" ]; then
    echo "LDAP bootstrap marker found (${LDAP_BOOTSTRAP_MARKER}), skipping LDIF seed."
    return 0
  fi

  if [ ! -f "${LDAP_SEED_LDIF}" ]; then
    echo "ERROR: Seed LDIF file not found: ${LDAP_SEED_LDIF}" >&2
    return 1
  fi

  local rendered_ldif base_rdn base_rdn_attr base_rdn_value
  base_rdn="${LDAP_BASE_DN%%,*}"
  if [[ "${base_rdn}" != *=* ]]; then
    echo "ERROR: LDAP_BASE_DN (${LDAP_BASE_DN}) is invalid." >&2
    return 1
  fi
  base_rdn_attr="${base_rdn%%=*}"
  base_rdn_value="${base_rdn#*=}"

  rendered_ldif="$(mktemp /tmp/wunderbox-seed.XXXXXX.ldif)"
  awk \
    -v basedn="${LDAP_BASE_DN}" \
    -v rdn_attr="${base_rdn_attr}" \
    -v rdn_value="${base_rdn_value}" \
    '{
      gsub(/__BASE_DN__/, basedn);
      gsub(/__BASE_RDN_ATTR__/, rdn_attr);
      gsub(/__BASE_RDN_VALUE__/, rdn_value);
      print
    }' "${LDAP_SEED_LDIF}" > "${rendered_ldif}"

  ldapmodify -x \
    -H "ldap://127.0.0.1:${LDAP_PORT}" \
    -D "${LDAP_DM_DN}" \
    -w "${LDAP_DM_PASSWORD}" \
    -a -c -f "${rendered_ldif}" || true

  rm -f "${rendered_ldif}"

  dsconf localhost plugin memberof fixup "${LDAP_BASE_DN}" || true
  touch "${LDAP_BOOTSTRAP_MARKER}"
  echo "LDAP bootstrap completed."
}

restart_if_possible() {
  dsctl localhost restart || true
}

cleanup() {
  if [ -n "${LDAP_PID:-}" ] && kill -0 "${LDAP_PID}" >/dev/null 2>&1; then
    kill "${LDAP_PID}" >/dev/null 2>&1 || true
    wait "${LDAP_PID}" || true
  fi
}

trap cleanup TERM INT

start_ldap "$@"
wait_for_ldap
ensure_memberof_plugin
restart_if_possible
wait_for_ldap
seed_directory_if_needed

wait "${LDAP_PID}"
