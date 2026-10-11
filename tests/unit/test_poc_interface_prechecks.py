"""Execute the shipped side-effect-free POC guards before transport or tasksets."""

import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CANARY = "POC_INTERFACE_SECRET_CANARY"


class PocInterfacePrecheckTests(unittest.TestCase):
    def exercise(self, role, valid, invalid):
        defaults = yaml.safe_load((ROOT / "roles" / role / "defaults/main.yml").read_text())
        plays = []
        for values, rejected in [(valid, False), *[(value, True) for value in invalid]]:
            plays.append(
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {**defaults, **values},
                    "tasks": [
                        {"ansible.builtin.set_fact": {"guard_rejected": False}},
                        {
                            "block": [
                                {"ansible.builtin.import_tasks": str(ROOT / "roles" / role / "tasks/assert.yml")}
                            ],
                            "rescue": [{"ansible.builtin.set_fact": {"guard_rejected": True}}],
                        },
                        {"ansible.builtin.assert": {"that": [f"guard_rejected is sameas {str(rejected).lower()}"]}},
                    ],
                }
            )
        with tempfile.TemporaryDirectory(dir=os.environ["HOME"]) as temporary:
            directory = Path(temporary)
            playbook = directory / "prechecks.yml"
            playbook.write_text(yaml.safe_dump(plays))
            config = directory / "ansible.cfg"
            config.write_text("[defaults]\n")
            executable = shutil.which("ansible-playbook")
            self.assertIsNotNone(executable, "The pinned Ansible runtime is required")
            result = subprocess.run(  # noqa: S603 - controlled offline Ansible fixture, no transport
                [executable, "-i", "localhost,", "-c", "local", str(playbook)],
                capture_output=True,
                check=False,
                text=True,
                timeout=90,
                env={**os.environ, "ANSIBLE_CONFIG": str(config), "ANSIBLE_LOCAL_TEMP": str(directory / "tmp")},
            )
        output = result.stdout + result.stderr
        self.assertNotIn(CANARY, output)
        self.assertEqual(result.returncode, 0, output[-4000:])
        self.assertNotIn("couldn't resolve module/action", output)

    def test_root_namespace_is_explicit_and_wrong_or_missing_namespace_is_rejected(self):
        auth = {
            "url": "https://vault.example",
            "ca_cert": "/fixture.pem",
            "namespace": "",
            "role_id": "fixture",
            "secret_id": CANARY,
            "auth_mount_point": "approle",
        }
        valid = {"vault_connection_credentials_auth": auth, "vault_connection_credentials_kv_mount": "fixture"}
        missing = {k: v for k, v in auth.items() if k != "namespace"}
        invalid = [
            {**valid, "vault_connection_credentials_auth": value}
            for value in (missing, {**auth, "namespace": None}, {**auth, "namespace": {}})
        ]
        self.exercise("vault_connection_credentials", valid, invalid)

    def check_pki_transport(self, role, valid, token):
        invalid = []
        for suffix, values in (("ca_path", ("", None, [], "relative.pem")), (token, ("", None, [], " "))):
            for value in values:
                invalid.append({**valid, role + "_" + suffix: value})
        self.exercise(role, valid, invalid)

    def test_certificate_custody_requires_ca_and_token_before_vault_access(self):
        self.check_pki_transport(
            "vault_pki_certificate",
            {
                "vault_pki_certificate_api_url": "https://vault.example",
                "vault_pki_certificate_ca_path": "/fixture.pem",
                "vault_pki_certificate_kv_token": CANARY,
                "vault_pki_certificate_kv_path": "kv/data/fixture",
                "vault_pki_certificate_issue_path": "pki/issuer/fixture/issue/server",
                "vault_pki_certificate_common_name": "fixture.example",
                "vault_pki_certificate_cert_path": "/fixture/cert.pem",
                "vault_pki_certificate_key_path": "/fixture/key.pem",
            },
            "kv_token",
        )

    def test_leaf_cac_requires_ca_and_token_before_vault_access(self):
        self.check_pki_transport(
            "vault_pki_leaf_cac",
            {
                "vault_pki_leaf_cac_api_url": "https://vault.example",
                "vault_pki_leaf_cac_ca_path": "/fixture.pem",
                "vault_pki_leaf_cac_admin_token": CANARY,
                "vault_pki_leaf_cac_mount": "pki",
                "vault_pki_leaf_cac_name": "server",
                "vault_pki_leaf_cac_definition": {
                    "issuer_ref": "fixture",
                    "allowed_domains": ["fixture.example"],
                    "allow_bare_domains": True,
                    "allow_subdomains": False,
                    "allow_glob_domains": False,
                    "allow_any_name": False,
                    "allow_ip_sans": False,
                    "allow_localhost": False,
                    "allow_wildcard_certificates": False,
                    "server_flag": True,
                    "client_flag": False,
                },
            },
            "admin_token",
        )

    def test_cleanup_role_identities_are_checked_before_earlier_tasksets(self):
        removals = [{"name": "fixture"}, {"name": "fixture", "client_id": "account"}]
        valid = {
            "keycloak_cac_realms": [{"realm": "fixture"}],
            "keycloak_cac_default_role_cleanup_enabled": True,
            "keycloak_cac_default_role_cleanup": [{"realm": "fixture", "allowed_removals": removals}],
        }
        invalid = []
        for entries in (
            [{}],
            [{"name": ""}],
            [{"name": " "}],
            [{"name": "fixture", "extra": CANARY}],
            [{"name": "fixture", "client_id": None}],
            [{"name": "fixture", "client_id": ""}],
            [{"name": "fixture", "client_id": " "}],
            ["fixture"],
            [removals[0], removals[0]],
            [removals[1], {"client_id": "account", "name": "fixture"}],
        ):
            case = copy.deepcopy(valid)
            case["keycloak_cac_default_role_cleanup"][0]["allowed_removals"] = entries
            invalid.append(case)
        self.exercise("keycloak_cac", valid, invalid)
