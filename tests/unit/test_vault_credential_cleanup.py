"""A rescued credential failure cannot retain the Vault document or selection."""

import copy
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class CredentialCleanupTests(unittest.TestCase):
    def test_real_rescue_clears_sensitive_intermediates_for_every_validation_failure(self):
        tasks = yaml.safe_load((ROOT / "roles/vault_connection_credentials/tasks/read_source.yml").read_text())
        source = {
            "vault_path": "test/accounts",
            "destination": "desktop_password",
            "username": "p1005a",
            "tier": 1,
            "subject": "fixture",
            "purpose": "desktop",
        }
        base = {
            "schema_version": 1,
            "subject": "fixture",
            "purpose": "desktop",
            "accounts": [{"username": "p1005a", "tier": 1, "password": "SECRET-CANARY" * 4}],
        }
        for field, value in [
            ("schema_version", 2),
            ("subject", "foreign"),
            ("purpose", "wrong"),
            ("accounts", []),
            ("accounts", base["accounts"] * 2),
            ("accounts", [{**base["accounts"][0], "password": "short"}]),
            ("accounts", [{**base["accounts"][0], "password": ["SECRET-CANARY"] * 32}]),
        ]:
            with self.subTest(field=field):
                document = {**base, field: value}
                actual = copy.deepcopy(tasks)
                actual[1]["block"][0] = {
                    "ansible.builtin.set_fact": {"vault_connection_credentials_document": {"secret": document}},
                    "no_log": True,
                }
                play = [
                    {
                        "hosts": "localhost",
                        "gather_facts": False,
                        "vars": {
                            "vault_connection_credentials_source": source,
                            "vault_connection_credentials_result": {},
                        },
                        "tasks": [
                            {
                                "block": actual,
                                "rescue": [
                                    {
                                        "ansible.builtin.assert": {
                                            "that": [
                                                "vault_connection_credentials_document == {}",
                                                "vault_connection_credentials_matches == []",
                                                "vault_connection_credentials_result == {}",
                                            ]
                                        },
                                        "no_log": True,
                                    }
                                ],
                            }
                        ],
                    }
                ]
                with tempfile.TemporaryDirectory(dir=os.environ["HOME"]) as tmp:
                    path = Path(tmp)
                    (path / "play.yml").write_text(yaml.safe_dump(play))
                    (path / "ansible.cfg").write_text("[defaults]\n")
                    result = subprocess.run(  # noqa: S603 - controlled offline Ansible fixture
                        [shutil.which("ansible-playbook"), "-i", "localhost,", "-c", "local", str(path / "play.yml")],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        env={
                            **os.environ,
                            "ANSIBLE_CONFIG": str(path / "ansible.cfg"),
                            "ANSIBLE_LOCAL_TEMP": str(path / "ansible"),
                        },
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("rescued=1", result.stdout)
                    self.assertNotIn("SECRET-CANARY", result.stdout + result.stderr)

    def test_later_source_failure_discards_the_previously_resolved_bundle(self):
        main = yaml.safe_load((ROOT / "roles/vault_connection_credentials/tasks/main.yml").read_text())
        source_tasks = yaml.safe_load((ROOT / "roles/vault_connection_credentials/tasks/read_source.yml").read_text())
        source_tasks[1]["block"][0] = {
            "ansible.builtin.set_fact": {
                "vault_connection_credentials_document": (
                    "{{ fixture_documents[vault_connection_credentials_source.username] }}"
                )
            },
            "no_log": True,
        }
        accounts = [
            {"username": "first", "tier": "tier-1", "password": "SECRET-CANARY" * 4},
            {"username": "second", "tier": "tier-2", "password": "short"},
        ]
        sources = [
            {
                "vault_path": "fixture/" + a["username"],
                "destination": a["username"] + "_password",
                "username": a["username"],
                "tier": a["tier"],
                "subject": "fixture",
                "purpose": "desktop",
            }
            for a in accounts
        ]
        with tempfile.TemporaryDirectory(dir=os.environ["HOME"]) as temporary:
            path = Path(temporary)
            shutil.copy(ROOT / "roles/vault_connection_credentials/tasks/assert.yml", path / "assert.yml")
            (path / "read_source.yml").write_text(yaml.safe_dump(source_tasks))
            (path / "main.yml").write_text(yaml.safe_dump(main))
            play = [
                {
                    "hosts": "localhost",
                    "gather_facts": False,
                    "vars": {
                        "vault_connection_credentials_sources": sources,
                        "vault_connection_credentials_kv_mount": "fixture",
                        "vault_connection_credentials_auth": {
                            "url": "https://fixture",
                            "ca_cert": "/fixture.pem",
                            "role_id": "fixture",
                            "secret_id": "fixture",
                            "auth_mount_point": "approle",
                        },
                        "fixture_documents": {
                            a["username"]: {
                                "secret": {
                                    "schema_version": 1,
                                    "subject": "fixture",
                                    "purpose": "desktop",
                                    "accounts": [a],
                                }
                            }
                            for a in accounts
                        },
                    },
                    "tasks": [
                        {
                            "block": [{"ansible.builtin.import_tasks": str(path / "main.yml")}],
                            "rescue": [
                                {
                                    "ansible.builtin.assert": {
                                        "that": [
                                            "vault_connection_credentials_result == {}",
                                            "vault_connection_credentials_document == {}",
                                            "vault_connection_credentials_matches == []",
                                        ]
                                    },
                                    "no_log": True,
                                }
                            ],
                        }
                    ],
                }
            ]
            (path / "play.yml").write_text(yaml.safe_dump(play))
            (path / "ansible.cfg").write_text("[defaults]\n")
            result = subprocess.run(  # noqa: S603 - controlled offline transaction fixture
                [shutil.which("ansible-playbook"), "-i", "localhost,", "-c", "local", str(path / "play.yml")],
                capture_output=True,
                text=True,
                check=False,
                timeout=45,
                env={
                    **os.environ,
                    "ANSIBLE_CONFIG": str(path / "ansible.cfg"),
                    "ANSIBLE_LOCAL_TEMP": str(path / "ansible"),
                },
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("rescued=2", result.stdout)
            self.assertNotIn("SECRET-CANARY", result.stdout + result.stderr)
