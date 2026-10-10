#!/usr/bin/python
# Copyright: (c) 2026 Lightning IT
# SPDX-License-Identifier: MIT OR GPL-3.0-or-later
# GNU General Public License v3.0+ alternative: https://www.gnu.org/licenses/gpl-3.0.txt
# ruff: noqa: E402
"""Remove only explicitly allowlisted children of a Keycloak default role."""

DOCUMENTATION = r"""
---
module: keycloak_default_role_composites
short_description: Remove allowlisted Keycloak realm default-role composites
description:
  - Reconciles an empty effective default-role composite for one realm.
  - Fails closed if an existing child is not explicitly allowlisted.
  - Does not delete role definitions or alter user role mappings.
options:
  api_url:
    description: Keycloak API origin; remote endpoints require HTTPS.
    type: str
    required: true
  auth_realm:
    description: Realm used for administrator authentication.
    type: str
    required: true
  auth_username:
    description: Administrator username.
    type: str
    required: true
  auth_password:
    description: Administrator password, suppressed by the runtime argument specification.
    type: str
    required: true
  realm:
    description: Realm whose allowlisted default-role children are reconciled.
    type: str
    required: true
  allowed_removals:
    type: list
    elements: dict
    required: true
    description:
      - Exact role name and optional client ID for every child permitted to be removed.
  require_empty_realm:
    type: bool
    default: false
    description:
      - Refuse removal while the realm has users or active client sessions.
  validate_certs:
    description: Validate the TLS certificate; disabling validation is refused.
    type: bool
    default: true
  ca_cert:
    description: Optional CA certificate bundle used for TLS validation.
    type: path
author:
  - Lightning IT (@litroc)
"""

EXAMPLES = r"""
- name: Remove observed stock defaults from a broker-only realm
  lit.supplementary.keycloak_default_role_composites:
    api_url: http://127.0.0.1:8080
    auth_realm: master
    auth_username: admin
    auth_password: "{{ keycloak_admin_password }}"
    realm: tier-1
    allowed_removals:
      - {name: offline_access}
      - {name: uma_authorization}
      - {name: manage-account, client_id: account}
      - {name: manage-account-links, client_id: account}
      - {name: view-profile, client_id: account}
"""

RETURN = r"""
removed:
  description: Names of removed composite roles, without IDs or credentials.
  returned: success
  type: list
  elements: str
"""


import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from ansible.module_utils.basic import AnsibleModule


def canonical_allowed(entries):
    if not isinstance(entries, list):
        raise ValueError("allowed_removals must be a list")
    canonical = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"name", "client_id"}:
            raise ValueError("allowed_removals has an unexpected field")
        name = entry.get("name")
        client_id = entry.get("client_id")
        if (
            not isinstance(name, str)
            or not name
            or (client_id is not None and (not isinstance(client_id, str) or not client_id))
        ):
            raise ValueError("allowed_removals contains an invalid role")
        key = (client_id, name)
        if key in canonical:
            raise ValueError("allowed_removals contains a duplicate role")
        canonical.add(key)
    return canonical


def role_identity(role, client_lookup):
    if not isinstance(role, dict) or not isinstance(role.get("name"), str):
        raise ValueError("Keycloak returned a malformed composite role")
    if role.get("clientRole") is True:
        container_id = role.get("containerId")
        if not isinstance(container_id, str) or not container_id:
            raise ValueError("Keycloak client role lacks a container ID")
        client_id = client_lookup(container_id)
        if not isinstance(client_id, str) or not client_id:
            raise ValueError("Keycloak client role lacks a client ID")
        return client_id, role["name"]
    if role.get("clientRole") is not False:
        raise ValueError("Keycloak role has an ambiguous clientRole flag")
    return None, role["name"]


def plan_removal(children, allowed, client_lookup):
    if not isinstance(children, list) or len(children) > 100:
        raise ValueError("Keycloak default-role response is invalid or too large")
    actual = [role_identity(role, client_lookup) for role in children]
    if len(actual) != len(set(actual)):
        raise ValueError("Keycloak returned duplicate default-role composites")
    if set(actual) - allowed:
        raise ValueError("Keycloak default role contains a non-allowlisted composite")
    return sorted(actual, key=lambda item: (item[0] or "", item[1]))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class KeycloakAPI:
    def __init__(self, api_url, validate_certs, ca_cert):
        parsed = urlsplit(api_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path not in ("", "/"):
            raise ValueError("api_url must be an origin URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("api_url must not contain credentials or a query")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("plaintext Keycloak API is allowed only on loopback")
        if parsed.scheme == "https" and not validate_certs:
            raise ValueError("Keycloak TLS validation cannot be disabled")
        self.base = api_url.rstrip("/")
        try:
            self.context = ssl.create_default_context(cafile=ca_cert) if parsed.scheme == "https" else None
        except (OSError, ssl.SSLError):
            raise ValueError("Keycloak CA trust configuration could not be loaded") from None
        transport = HTTPSHandler(context=self.context) if self.context else HTTPHandler()
        self.opener = build_opener(ProxyHandler({}), transport, NoRedirect())

    def call(self, path, method="GET", data=None, token=None):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        if data is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(data).encode()
        # The constructor accepts only a validated HTTP(S) origin.
        request = Request(self.base + path, data=data, headers=headers, method=method)  # noqa: S310
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(1024 * 1024)
                return response.status, json.loads(raw) if raw else None
        except HTTPError as error:
            return error.code, None
        except (URLError, ValueError) as error:
            raise ValueError("Keycloak API request failed") from error

    def login(self, auth_realm, username, password):
        path = "/realms/" + quote(auth_realm, safe="") + "/protocol/openid-connect/token"
        body = urlencode(
            {
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": username,
                "password": password,
            }
        ).encode()
        request = Request(  # noqa: S310
            self.base + path,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=15) as response:
                value = json.load(response).get("access_token")
        except (HTTPError, URLError, ValueError) as error:
            raise ValueError("Keycloak administrator authentication failed") from error
        if not isinstance(value, str) or not value:
            raise ValueError("Keycloak administrator token is absent")
        return value


def require_no_users_or_sessions(api, prefix, token):
    status, users = api.call(prefix + "/users/count", token=token)
    if status != 200 or (not isinstance(users, int) or isinstance(users, bool)) or users < 0:
        raise ValueError("Keycloak realm user count is unavailable")
    status, sessions = api.call(prefix + "/client-session-stats", token=token)
    if status != 200 or not isinstance(sessions, list) or len(sessions) > 1000:
        raise ValueError("Keycloak realm session count is unavailable")
    active = []
    for item in sessions:
        if not isinstance(item, dict):
            raise ValueError("Keycloak realm session count is malformed")
        value = item.get("active")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            active.append(value)
        elif isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 9:
            active.append(int(value))
        else:
            raise ValueError("Keycloak realm session count is malformed")
    if users or any(active):
        raise ValueError("Keycloak realm has users or active client sessions")


def reconcile(api, realm, token, allowed, check_mode=False, require_empty_realm=False):
    prefix = "/admin/realms/" + quote(realm, safe="")
    name = "default-roles-" + realm
    status, root = api.call(prefix + "/roles/" + quote(name, safe=""), token=token)
    if status != 200 or not isinstance(root, dict) or root.get("name") != name:
        raise ValueError("Keycloak default role is absent or unexpected")
    role_id = root.get("id")
    if not isinstance(role_id, str) or not role_id:
        raise ValueError("Keycloak default role ID is absent")
    path = prefix + "/roles-by-id/" + quote(role_id, safe="") + "/composites"
    status, children = api.call(path, token=token)
    if status != 200:
        raise ValueError("Keycloak default-role readback failed")
    clients = {}

    def client_lookup(container_id):
        if container_id not in clients:
            code, detail = api.call(prefix + "/clients/" + quote(container_id, safe=""), token=token)
            if code != 200 or not isinstance(detail, dict):
                raise ValueError("Keycloak default-role client lookup failed")
            clients[container_id] = detail.get("clientId")
        return clients[container_id]

    planned = plan_removal(children, allowed, client_lookup)
    if planned and require_empty_realm:
        require_no_users_or_sessions(api, prefix, token)
    if not planned or check_mode:
        return planned
    status, _response = api.call(path, method="DELETE", data=children, token=token)
    if status != 204:
        raise ValueError("Keycloak default-role composite removal failed")
    status, remaining = api.call(path, token=token)
    if status != 200 or remaining != []:
        raise ValueError("Keycloak default-role composite readback is not empty")
    return planned


def main():
    module = AnsibleModule(
        argument_spec={
            "api_url": {"type": "str", "required": True},
            "auth_realm": {"type": "str", "required": True},
            "auth_username": {"type": "str", "required": True},
            "auth_password": {"type": "str", "required": True, "no_log": True},
            "realm": {"type": "str", "required": True},
            "allowed_removals": {"type": "list", "elements": "dict", "required": True},
            "require_empty_realm": {"type": "bool", "default": False},
            "validate_certs": {"type": "bool", "default": True},
            "ca_cert": {"type": "path"},
        },
        supports_check_mode=True,
    )
    p = module.params
    try:
        allowed = canonical_allowed(p["allowed_removals"])
        api = KeycloakAPI(p["api_url"], p["validate_certs"], p["ca_cert"])
        token = api.login(p["auth_realm"], p["auth_username"], p["auth_password"])
        removed = reconcile(api, p["realm"], token, allowed, module.check_mode, p["require_empty_realm"])
        module.exit_json(
            changed=bool(removed),
            removed=[(client + "/" if client else "") + name for client, name in removed],
        )
    except ValueError as error:
        module.fail_json(msg=str(error))


if __name__ == "__main__":
    main()
