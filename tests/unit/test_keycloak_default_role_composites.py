"""The default-role cleanup must be bounded, idempotent and fail closed."""

import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "plugins/modules/keycloak_default_role_composites.py"
SPEC = importlib.util.spec_from_file_location("keycloak_default_role_composites", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


ALLOWED = MODULE.canonical_allowed(
    [
        {"name": "offline_access"},
        {"name": "uma_authorization"},
        {"name": "manage-account", "client_id": "account"},
        {"name": "manage-account-links", "client_id": "account"},
        {"name": "view-profile", "client_id": "account"},
    ]
)
TOKEN = object()


def realm_role(name):
    return {"name": name, "id": name + "-id", "clientRole": False}


def client_role(name, container="account-uuid"):
    return {
        "name": name,
        "id": name + "-id",
        "clientRole": True,
        "containerId": container,
    }


class FakeAPI:
    def __init__(self, children, users=0, active=0):
        self.children = children
        self.users = users
        self.active = active
        self.deleted = 0

    def call(self, path, method="GET", data=None, token=None):
        assert token is TOKEN
        if path.endswith("/roles/default-roles-tier-1"):
            return 200, {"id": "default-id", "name": "default-roles-tier-1"}
        if path.endswith("/clients/account-uuid"):
            return 200, {"clientId": "account"}
        if path.endswith("/users/count"):
            return 200, self.users
        if path.endswith("/client-session-stats"):
            return 200, [{"active": self.active}]
        if path.endswith("/roles-by-id/default-id/composites"):
            if method == "DELETE":
                assert data == self.children
                self.deleted += 1
                self.children = []
                return 204, None
            return 200, self.children
        raise AssertionError("Unexpected Keycloak API path: " + path)


class KeycloakDefaultRoleTests(unittest.TestCase):
    def test_exact_stock_roles_are_removed_once(self):
        api = FakeAPI(
            [
                realm_role("offline_access"),
                realm_role("uma_authorization"),
                client_role("manage-account"),
                client_role("manage-account-links"),
                client_role("view-profile"),
            ]
        )
        removed = MODULE.reconcile(api, "tier-1", TOKEN, ALLOWED)
        self.assertEqual(len(removed), 5)
        self.assertEqual(api.deleted, 1)
        self.assertEqual(MODULE.reconcile(api, "tier-1", TOKEN, ALLOWED), [])
        self.assertEqual(api.deleted, 1)

    def test_check_mode_does_not_delete(self):
        api = FakeAPI([realm_role("offline_access")])
        self.assertEqual(
            MODULE.reconcile(api, "tier-1", TOKEN, ALLOWED, True),
            [(None, "offline_access")],
        )
        self.assertEqual(api.deleted, 0)

    def test_empty_realm_guard_refuses_existing_users(self):
        api = FakeAPI([realm_role("offline_access")], users=1)
        with self.assertRaisesRegex(ValueError, "users or active client sessions"):
            MODULE.reconcile(api, "tier-1", TOKEN, ALLOWED, require_empty_realm=True)
        self.assertEqual(api.deleted, 0)

    def test_empty_realm_guard_refuses_active_sessions(self):
        api = FakeAPI([realm_role("offline_access")], active=1)
        with self.assertRaisesRegex(ValueError, "users or active client sessions"):
            MODULE.reconcile(api, "tier-1", TOKEN, ALLOWED, require_empty_realm=True)
        self.assertEqual(api.deleted, 0)

    def test_empty_realm_guard_refuses_malformed_counts(self):
        api = FakeAPI([realm_role("offline_access")], active=0.5)
        with self.assertRaisesRegex(ValueError, "session count is malformed"):
            MODULE.reconcile(api, "tier-1", TOKEN, ALLOWED, require_empty_realm=True)
        self.assertEqual(api.deleted, 0)

    def test_empty_realm_guard_allows_exact_empty_cleanup(self):
        api = FakeAPI([realm_role("offline_access")])
        self.assertEqual(
            MODULE.reconcile(api, "tier-1", TOKEN, ALLOWED, require_empty_realm=True),
            [(None, "offline_access")],
        )
        self.assertEqual(api.deleted, 1)

    def test_unknown_role_blocks_every_delete(self):
        api = FakeAPI([realm_role("offline_access"), client_role("manage-users")])
        with self.assertRaisesRegex(ValueError, "non-allowlisted"):
            MODULE.reconcile(api, "tier-1", TOKEN, ALLOWED)
        self.assertEqual(api.deleted, 0)

    def test_unexpected_client_blocks_every_delete(self):
        api = FakeAPI([client_role("manage-account", "other-uuid")])
        api.call = lambda path, method="GET", data=None, token=None: (
            (200, {"clientId": "realm-management"})
            if path.endswith("/clients/other-uuid")
            else FakeAPI.call(api, path, method, data, token)
        )
        with self.assertRaisesRegex(ValueError, "non-allowlisted"):
            MODULE.reconcile(api, "tier-1", TOKEN, ALLOWED)
        self.assertEqual(api.deleted, 0)

    def test_ambiguous_or_duplicate_contract_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            MODULE.canonical_allowed([{"name": "offline_access"}] * 2)
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            MODULE.plan_removal([{"name": "offline_access"}], ALLOWED, lambda _: "")

    def test_remote_api_must_use_loopback_or_validated_tls(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            MODULE.KeycloakAPI("http://keycloak.example", True, None)
        with self.assertRaisesRegex(ValueError, "cannot be disabled"):
            MODULE.KeycloakAPI("https://keycloak.example", False, None)


if __name__ == "__main__":
    unittest.main()
