#!/usr/bin/env bash
set -euo pipefail

: "${KEYCLOAK_CONTAINER_NAME:=identity-stack-keycloak}"
: "${KEYCLOAK_PUBLIC_URL:=http://127.0.0.1:8080}"
: "${KEYCLOAK_INTERNAL_URL:=http://127.0.0.1:8080}"
: "${KEYCLOAK_REALM:=wunderbox}"
: "${KEYCLOAK_ADMIN_USER:=admin}"
: "${SECRETS_DIR:=/srv/wunderbox/identity/secrets}"
: "${KEYCLOAK_ADMIN_PASSWORD_FILE:=${SECRETS_DIR}/keycloak_admin_password}"
: "${LDAP_BIND_DN:=cn=Directory Manager}"
: "${LDAP_BIND_PASSWORD_FILE:=${SECRETS_DIR}/ds_dm_password}"
: "${LDAP_CONNECTION_URL:=ldap://127.0.0.1:3389}"
: "${BASE_DN:=dc=wunderbox,dc=local}"
: "${LDAP_USERS_DN:=ou=people,${BASE_DN}}"
: "${LDAP_GROUPS_DN:=ou=groups,${BASE_DN}}"
: "${LDAP_PROVIDER_NAME:=ldap-389ds}"
: "${LDAP_GROUP_MAPPER_NAME:=ldap-groups-memberof}"
: "${GROUP_SCOPE_NAME:=wunderbox-groups}"
: "${GROUP_SCOPE_MAPPER_NAME:=groups}"
: "${DEMO_CLIENT_ID:=demo}"
: "${DEMO_REDIRECT_URI:=http://localhost:8081/*}"

if [ -z "${KEYCLOAK_ADMIN_PASSWORD:-}" ]; then
  if [ -f "${KEYCLOAK_ADMIN_PASSWORD_FILE}" ]; then
    KEYCLOAK_ADMIN_PASSWORD="$(tr -d '\r\n' < "${KEYCLOAK_ADMIN_PASSWORD_FILE}")"
  else
    echo "ERROR: KEYCLOAK_ADMIN_PASSWORD is not set and ${KEYCLOAK_ADMIN_PASSWORD_FILE} is missing." >&2
    exit 1
  fi
fi

if [ -z "${LDAP_BIND_PASSWORD:-}" ]; then
  if [ -f "${LDAP_BIND_PASSWORD_FILE}" ]; then
    LDAP_BIND_PASSWORD="$(tr -d '\r\n' < "${LDAP_BIND_PASSWORD_FILE}")"
  else
    echo "ERROR: LDAP_BIND_PASSWORD is not set and ${LDAP_BIND_PASSWORD_FILE} is missing." >&2
    exit 1
  fi
fi

kc() {
  podman exec -i "${KEYCLOAK_CONTAINER_NAME}" /opt/keycloak/bin/kcadm.sh "$@"
}

extract_first_id() {
  awk -F'"' '/"id"[[:space:]]*:/ {print $4; exit}'
}

wait_for_keycloak() {
  local i
  for i in $(seq 1 120); do
    if curl -fsS "${KEYCLOAK_PUBLIC_URL}/realms/master/.well-known/openid-configuration" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "ERROR: Keycloak not reachable at ${KEYCLOAK_PUBLIC_URL}." >&2
  return 1
}

wait_for_keycloak

kc config credentials \
  --server "${KEYCLOAK_INTERNAL_URL}" \
  --realm master \
  --user "${KEYCLOAK_ADMIN_USER}" \
  --password "${KEYCLOAK_ADMIN_PASSWORD}" >/dev/null

if ! kc get "realms/${KEYCLOAK_REALM}" >/dev/null 2>&1; then
  kc create realms \
    -s realm="${KEYCLOAK_REALM}" \
    -s enabled=true >/dev/null
fi

ldap_component_id="$(
  kc get components -r "${KEYCLOAK_REALM}" -q name="${LDAP_PROVIDER_NAME}" | extract_first_id || true
)"

if [ -z "${ldap_component_id}" ]; then
  kc create components -r "${KEYCLOAK_REALM}" \
    -s name="${LDAP_PROVIDER_NAME}" \
    -s providerId=ldap \
    -s providerType=org.keycloak.storage.UserStorageProvider \
    -s parentId="${KEYCLOAK_REALM}" \
    -s 'config.enabled=["true"]' \
    -s 'config.priority=["0"]' \
    -s 'config.importEnabled=["true"]' \
    -s 'config.editMode=["READ_ONLY"]' \
    -s 'config.syncRegistrations=["false"]' \
    -s 'config.vendor=["other"]' \
    -s 'config.connectionUrl=["'"${LDAP_CONNECTION_URL}"'"]' \
    -s 'config.usersDn=["'"${LDAP_USERS_DN}"'"]' \
    -s 'config.usernameLDAPAttribute=["uid"]' \
    -s 'config.rdnLDAPAttribute=["uid"]' \
    -s 'config.uuidLDAPAttribute=["entryUUID"]' \
    -s 'config.userObjectClasses=["inetOrgPerson,organizationalPerson,person,top"]' \
    -s 'config.searchScope=["2"]' \
    -s 'config.authType=["simple"]' \
    -s 'config.bindDn=["'"${LDAP_BIND_DN}"'"]' \
    -s 'config.bindCredential=["'"${LDAP_BIND_PASSWORD}"'"]' \
    -s 'config.pagination=["true"]' \
    -s 'config.connectionPooling=["true"]' >/dev/null

  ldap_component_id="$(
    kc get components -r "${KEYCLOAK_REALM}" -q name="${LDAP_PROVIDER_NAME}" | extract_first_id || true
  )"
else
  kc update "components/${ldap_component_id}" -r "${KEYCLOAK_REALM}" \
    -s name="${LDAP_PROVIDER_NAME}" \
    -s providerId=ldap \
    -s providerType=org.keycloak.storage.UserStorageProvider \
    -s parentId="${KEYCLOAK_REALM}" \
    -s 'config.enabled=["true"]' \
    -s 'config.priority=["0"]' \
    -s 'config.importEnabled=["true"]' \
    -s 'config.editMode=["READ_ONLY"]' \
    -s 'config.syncRegistrations=["false"]' \
    -s 'config.vendor=["other"]' \
    -s 'config.connectionUrl=["'"${LDAP_CONNECTION_URL}"'"]' \
    -s 'config.usersDn=["'"${LDAP_USERS_DN}"'"]' \
    -s 'config.usernameLDAPAttribute=["uid"]' \
    -s 'config.rdnLDAPAttribute=["uid"]' \
    -s 'config.uuidLDAPAttribute=["entryUUID"]' \
    -s 'config.userObjectClasses=["inetOrgPerson,organizationalPerson,person,top"]' \
    -s 'config.searchScope=["2"]' \
    -s 'config.authType=["simple"]' \
    -s 'config.bindDn=["'"${LDAP_BIND_DN}"'"]' \
    -s 'config.bindCredential=["'"${LDAP_BIND_PASSWORD}"'"]' \
    -s 'config.pagination=["true"]' \
    -s 'config.connectionPooling=["true"]' >/dev/null
fi

if [ -z "${ldap_component_id}" ]; then
  echo "ERROR: LDAP user federation component could not be resolved." >&2
  exit 1
fi

group_mapper_id="$(
  kc get components -r "${KEYCLOAK_REALM}" -q name="${LDAP_GROUP_MAPPER_NAME}" | extract_first_id || true
)"

if [ -z "${group_mapper_id}" ]; then
  kc create components -r "${KEYCLOAK_REALM}" \
    -s name="${LDAP_GROUP_MAPPER_NAME}" \
    -s providerId=group-ldap-mapper \
    -s providerType=org.keycloak.storage.ldap.mappers.LDAPStorageMapper \
    -s parentId="${ldap_component_id}" \
    -s 'config.mode=["LDAP_ONLY"]' \
    -s 'config.groups.dn=["'"${LDAP_GROUPS_DN}"'"]' \
    -s 'config.group.name.ldap.attribute=["cn"]' \
    -s 'config.group.object.classes=["groupOfNames"]' \
    -s 'config.membership.ldap.attribute=["member"]' \
    -s 'config.membership.attribute.type=["DN"]' \
    -s 'config.memberof.ldap.attribute=["memberOf"]' \
    -s 'config.user.roles.retrieve.strategy=["GET_GROUPS_FROM_USER_MEMBEROF_ATTRIBUTE"]' \
    -s 'config.preserve.group.inheritance=["true"]' \
    -s 'config.drop.non.existing.groups.during.sync=["false"]' \
    -s 'config.ignore.missing.groups=["true"]' >/dev/null
else
  kc update "components/${group_mapper_id}" -r "${KEYCLOAK_REALM}" \
    -s name="${LDAP_GROUP_MAPPER_NAME}" \
    -s providerId=group-ldap-mapper \
    -s providerType=org.keycloak.storage.ldap.mappers.LDAPStorageMapper \
    -s parentId="${ldap_component_id}" \
    -s 'config.mode=["LDAP_ONLY"]' \
    -s 'config.groups.dn=["'"${LDAP_GROUPS_DN}"'"]' \
    -s 'config.group.name.ldap.attribute=["cn"]' \
    -s 'config.group.object.classes=["groupOfNames"]' \
    -s 'config.membership.ldap.attribute=["member"]' \
    -s 'config.membership.attribute.type=["DN"]' \
    -s 'config.memberof.ldap.attribute=["memberOf"]' \
    -s 'config.user.roles.retrieve.strategy=["GET_GROUPS_FROM_USER_MEMBEROF_ATTRIBUTE"]' \
    -s 'config.preserve.group.inheritance=["true"]' \
    -s 'config.drop.non.existing.groups.during.sync=["false"]' \
    -s 'config.ignore.missing.groups=["true"]' >/dev/null
fi

scope_id="$(kc get client-scopes -r "${KEYCLOAK_REALM}" -q name="${GROUP_SCOPE_NAME}" | extract_first_id || true)"
if [ -z "${scope_id}" ]; then
  kc create client-scopes -r "${KEYCLOAK_REALM}" \
    -s name="${GROUP_SCOPE_NAME}" \
    -s protocol=openid-connect >/dev/null
  scope_id="$(kc get client-scopes -r "${KEYCLOAK_REALM}" -q name="${GROUP_SCOPE_NAME}" | extract_first_id || true)"
fi

if [ -z "${scope_id}" ]; then
  echo "ERROR: Client scope ${GROUP_SCOPE_NAME} could not be resolved." >&2
  exit 1
fi

if ! kc get "client-scopes/${scope_id}/protocol-mappers/models" -r "${KEYCLOAK_REALM}" \
  | grep -Eq '"name"[[:space:]]*:[[:space:]]*"'"${GROUP_SCOPE_MAPPER_NAME}"'"'; then
  kc create "client-scopes/${scope_id}/protocol-mappers/models" -r "${KEYCLOAK_REALM}" \
    -s name="${GROUP_SCOPE_MAPPER_NAME}" \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-group-membership-mapper \
    -s 'config."full.path"="false"' \
    -s 'config."id.token.claim"="true"' \
    -s 'config."access.token.claim"="true"' \
    -s 'config."userinfo.token.claim"="true"' \
    -s 'config."claim.name"="groups"' \
    -s 'config."jsonType.label"="String"' >/dev/null
fi

if ! kc get "realms/${KEYCLOAK_REALM}/default-default-client-scopes" \
  | grep -Eq '"name"[[:space:]]*:[[:space:]]*"'"${GROUP_SCOPE_NAME}"'"'; then
  kc update "realms/${KEYCLOAK_REALM}/default-default-client-scopes/${scope_id}" -n >/dev/null
fi

demo_client_uuid="$(kc get clients -r "${KEYCLOAK_REALM}" -q clientId="${DEMO_CLIENT_ID}" | extract_first_id || true)"
if [ -z "${demo_client_uuid}" ]; then
  kc create clients -r "${KEYCLOAK_REALM}" \
    -s clientId="${DEMO_CLIENT_ID}" \
    -s publicClient=true \
    -s enabled=true \
    -s directAccessGrantsEnabled=true \
    -s standardFlowEnabled=true \
    -s 'redirectUris=["'"${DEMO_REDIRECT_URI}"'"]' >/dev/null
  demo_client_uuid="$(kc get clients -r "${KEYCLOAK_REALM}" -q clientId="${DEMO_CLIENT_ID}" | extract_first_id || true)"
fi

if [ -n "${demo_client_uuid}" ] && ! kc get "clients/${demo_client_uuid}/default-client-scopes" -r "${KEYCLOAK_REALM}" \
  | grep -Eq '"name"[[:space:]]*:[[:space:]]*"'"${GROUP_SCOPE_NAME}"'"'; then
  kc update "clients/${demo_client_uuid}/default-client-scopes/${scope_id}" -r "${KEYCLOAK_REALM}" -n >/dev/null
fi

echo "Keycloak bootstrap completed successfully for realm ${KEYCLOAK_REALM}."
