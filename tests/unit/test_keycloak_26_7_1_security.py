"""Regression tests for the pre-approved Keycloak 26.7.1 verifier."""

from __future__ import annotations

import json
import runpy
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "scripts" / "verify-keycloak-26.7.1-security.py"
PROFILE = "lit.supplementary/keycloak-26.7.1-security-v1"
IMAGE = (
    "quay.io/keycloak/keycloak:26.7.1@"
    "sha256:f1f1f01e472c8a78df40d8f2a49a925274eda4d3d80d5f6edbb5c880ee3c01c6"
)


class Keycloak2671SecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = runpy.run_path(
            str(VERIFIER),
            run_name="keycloak_26_7_1_security_module",
        )

    def write_fixture(self, root: Path) -> None:
        defaults = root / "roles" / "keycloak_deploy" / "defaults" / "main.yml"
        manifest = root / "manifests" / "identity-stack.pod.yaml"
        inventory = root / "meta" / "source-dependencies.yml"
        for path in (defaults, manifest, inventory):
            path.parent.mkdir(parents=True, exist_ok=True)
        defaults.write_text(
            yaml.safe_dump({"keycloak_deploy_image": IMAGE}, sort_keys=False),
            encoding="utf-8",
        )
        manifest.write_text(
            yaml.safe_dump(
                {"spec": {"containers": [{"name": "keycloak", "image": IMAGE}]}},
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        inventory.write_text(
            yaml.safe_dump(
                {
                    "container_images": [
                        {
                            "reference": IMAGE,
                            "locations": [
                                "manifests/identity-stack.pod.yaml",
                                "roles/keycloak_deploy/defaults/main.yml",
                            ],
                        }
                    ]
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def test_profile_is_preapproved_with_the_exact_contract(self) -> None:
        registry = json.loads(
            (ROOT / ".lit" / "security-release-profiles.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            {
                "description": (
                    "Verify the packaged Keycloak runtime is pinned to official "
                    "26.7.1 OCI index digest in role defaults, identity manifest, "
                    "and source inventory."
                ),
                "releaseEligible": True,
            },
            registry["profiles"][PROFILE],
        )

    def test_verifier_accepts_only_the_exact_packaged_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fixture(root)
            self.module["verify"](root)

            defaults = root / "roles" / "keycloak_deploy" / "defaults" / "main.yml"
            defaults.write_text(
                yaml.safe_dump(
                    {"keycloak_deploy_image": IMAGE.replace("26.7.1", "26.7.0")},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SystemExit, "role default"):
                self.module["verify"](root)

    def test_verifier_rejects_a_mismatched_identity_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fixture(root)
            manifest = root / "manifests" / "identity-stack.pod.yaml"
            manifest.write_text(
                yaml.safe_dump(
                    {"spec": {"containers": [{"name": "keycloak", "image": "mutable"}]}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SystemExit, "identity-stack"):
                self.module["verify"](root)

    def test_reader_rejects_parent_traversal_and_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            root = parent / "collection"
            root.mkdir()
            outside = parent / "outside.yml"
            outside.write_text("secret: value\n", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "escapes the collection root"):
                self.module["read_bounded_file"](
                    root,
                    root / ".." / outside.name,
                )

            invalid = root / "invalid.yml"
            invalid.write_bytes(b"\xff\xfe")
            with self.assertRaisesRegex(SystemExit, "cannot read"):
                self.module["read_bounded_file"](root, invalid)

    def test_loader_rejects_unhashable_yaml_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_fixture(root)
            defaults = root / "roles/keycloak_deploy/defaults/main.yml"
            defaults.write_text(
                "? [not, hashable]\n: value\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SystemExit, "must be hashable"):
                self.module["load_yaml"](
                    root,
                    "roles/keycloak_deploy/defaults/main.yml",
                )


if __name__ == "__main__":
    unittest.main()
