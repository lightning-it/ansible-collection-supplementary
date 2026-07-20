"""Regression tests for candidate-bound CycloneDX enrichment."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/enrich-cyclonedx-sbom.py"
SPEC = importlib.util.spec_from_file_location("enrich_cyclonedx_sbom", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"unable to import {SCRIPT}")
SBOM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SBOM)


class EnrichCycloneDxSbomTests(unittest.TestCase):
    def test_every_purl_segment_encoder_percent_encodes_plus(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        unsafe_safe_set = re.search(r"safe=(?P<quote>['\"])[^'\"]*\+[^'\"]*(?P=quote)", source)
        self.assertIsNone(unsafe_safe_set, unsafe_safe_set.group(0) if unsafe_safe_set else "")

    def test_os_package_purls_encode_plus_and_rpm_epoch_canonically(self) -> None:
        self.assertEqual(
            "pkg:deb/ubuntu/libc%2B%2B6@1:2.39%2Breally2.39-0ubuntu8.4?"
            "arch=amd64&distro=ubuntu-24.04&upstream="
            "pkg%3Adeb%2Fubuntu%2Fglibc%252B%252B%40"
            "1%3A2.39%252Breally2.39-0ubuntu8.4",
            SBOM._os_package_purl(
                os_id="ubuntu",
                distro="ubuntu-24.04",
                name="libc++6",
                version="1:2.39+really2.39-0ubuntu8.4",
                architecture="amd64",
                source_name="glibc++",
                source_version="1:2.39+really2.39-0ubuntu8.4",
            ),
        )
        self.assertEqual(
            "pkg:rpm/redhat/mod_ssl@2.4.62-13.el9?"
            "arch=x86_64&distro=rhel-9&epoch=1&upstream="
            "pkg%3Arpm%2Fredhat%2Fhttpd%402.4.62-13.el9",
            SBOM._os_package_purl(
                os_id="rhel",
                distro="rhel-9",
                name="mod_ssl",
                version="1:2.4.62-13.el9",
                architecture="x86_64",
                source_name="httpd",
                source_version="2.4.62-13.el9",
            ),
        )

    def _replace_candidate_member(self, candidate: Path, filename: str, content: bytes) -> None:
        with tarfile.open(candidate, "r:gz") as archive:
            files: dict[str, bytes] = {}
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:  # pragma: no cover - tarfile invariant
                    raise RuntimeError(f"cannot read fixture member {member.name}")
                files[member.name] = extracted.read()
        files[filename] = content
        with tarfile.open(candidate, "w:gz") as archive:
            for member_name, member_content in files.items():
                member = tarfile.TarInfo(member_name)
                member.size = len(member_content)
                archive.addfile(member, fileobj=io.BytesIO(member_content))

    def _bind_registry_policy(self, root: Path, policy: dict[str, object]) -> None:
        scenario = "keycloak-tiny"
        target = "ubuntu-24.04"
        registry_content = yaml.safe_dump(
            {"scenarios": {scenario: {"test_application": policy}}},
            sort_keys=False,
        )
        source_registry = root / "meta" / "role-coverage.yml"
        source_registry.parent.mkdir(parents=True, exist_ok=True)
        source_registry.write_text(registry_content, encoding="utf-8")

        dependencies = root / "cell" / "dependencies"
        registry_evidence = dependencies / f"role-coverage-{scenario}-{target}.yml"
        registry_evidence.write_text(registry_content, encoding="utf-8")
        inventory_path = dependencies / "test-application-dependencies.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        inventory["registry_policy"] = {
            "path": "meta/role-coverage.yml",
            "sha256": hashlib.sha256(registry_content.encode()).hexdigest(),
            "evidence_file": registry_evidence.name,
        }
        inventory["test_application_policy"] = policy
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")

    def _fixture(self, root: Path) -> dict[str, Path]:
        candidate = root / "lit-supplementary-1.40.0.tar.gz"
        galaxy = root / "galaxy.yml"
        galaxy.write_text(
            "---\nnamespace: lit\nname: supplementary\nversion: 1.40.0\n"
            "dependencies:\n  community.general: '>=11.4.9,<12.0.0'\n",
            encoding="utf-8",
        )
        requirements = root / "collections" / "requirements-rh.yml"
        requirements.parent.mkdir(parents=True)
        requirements.write_text(
            "---\ncollections:\n  - name: infra.aap_utilities\n    version: '3.3.0'\n",
            encoding="utf-8",
        )
        shipped_image = "docker.io/example/runtime:1.0@sha256:" + "d" * 64
        shipped_default = root / "roles" / "demo_deploy" / "defaults" / "main.yml"
        shipped_default.parent.mkdir(parents=True)
        shipped_default.write_text(f'---\ndemo_deploy_image: "{shipped_image}"\n', encoding="utf-8")
        aap_default = root / "roles" / "aap_deploy" / "defaults" / "main.yml"
        aap_default.parent.mkdir(parents=True)
        aap_default.write_text('---\naap_deploy_setup_download_version: "2.7"\n', encoding="utf-8")
        aap_install = root / "roles" / "aap_deploy" / "tasks" / "40_install.yml"
        aap_install.parent.mkdir(parents=True)
        aap_install.write_text(
            "---\n- ansible.builtin.debug:\n    msg: ansible.containerized_installer.install\n",
            encoding="utf-8",
        )
        aap_template = (
            root
            / "roles"
            / "aap_local_execution"
            / "templates"
            / "aap-local"
            / "inventories"
            / "group_vars"
            / "aaps"
            / "aap.yml.j2"
        )
        aap_template.parent.mkdir(parents=True)
        aap_template.write_text('---\naap_deploy_setup_download_version: "2.7"\n', encoding="utf-8")
        source_inventory = root / "meta" / "source-dependencies.yml"
        source_inventory.parent.mkdir(parents=True)
        source_inventory.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "container_images": [
                        {
                            "reference": shipped_image,
                            "locations": ["roles/demo_deploy/defaults/main.yml"],
                        }
                    ],
                    "derived_images": [],
                    "collections": [
                        {
                            "name": "community.general",
                            "requirement": ">=11.4.9,<12.0.0",
                            "source": "galaxy.yml",
                        },
                        {
                            "name": "infra.aap_utilities",
                            "requirement": "3.3.0",
                            "source": "collections/requirements-rh.yml",
                        },
                    ],
                    "external_products": [
                        {
                            "name": "red-hat-ansible-automation-platform",
                            "version": "2.7",
                            "type": "application",
                            "disposition": "blocked-external-license",
                            "reason": (
                                "The licensed AAP bundle is supplied only by a protected customer environment "
                                "and is unavailable to this untrusted fixture runtime."
                            ),
                            "provides_collections": ["ansible.containerized_installer"],
                            "locations": [
                                "roles/aap_deploy/defaults/main.yml",
                                "roles/aap_deploy/tasks/40_install.yml",
                                (
                                    "roles/aap_local_execution/templates/aap-local/inventories/"
                                    "group_vars/aaps/aap.yml.j2"
                                ),
                            ],
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        sbom = root / "sbom.cdx.json"
        sbom.write_text(
            json.dumps(
                {
                    "bomFormat": "CycloneDX",
                    "specVersion": "1.6",
                    "metadata": {},
                    "components": [],
                    "dependencies": [],
                }
            ),
            encoding="utf-8",
        )
        dependencies = root / "cell/dependencies"
        dependencies.mkdir(parents=True)
        (dependencies / "python-packages.json").write_text(
            json.dumps([{"name": "PyYAML", "version": "6.0.3+local"}]),
            encoding="utf-8",
        )
        (dependencies / "collection-dependencies.json").write_text(
            json.dumps(
                {
                    "collection_info": {
                        "lit.supplementary": {"version": "1.40.0"},
                        "community.general": {"version": "11.4.9+vendor"},
                    }
                }
            ),
            encoding="utf-8",
        )
        digest = "a" * 64
        container_inventory = dependencies / "container-image-digests.json"
        container_inventory.write_text(
            json.dumps(
                {
                    "container_inventory_available": True,
                    "images": [{"Digest": f"sha256:{digest}", "Names": ["example:1"]}],
                }
            ),
            encoding="utf-8",
        )
        (dependencies / "incus-base-image.json").write_text(json.dumps({"fingerprint": "b" * 64}), encoding="utf-8")
        config_content = "---\ndriver:\n  name: incus\n"
        source_config = root / "molecule" / "keycloak-tiny" / "molecule.yml"
        source_config.parent.mkdir(parents=True)
        source_config.write_text(config_content, encoding="utf-8")
        config_evidence = dependencies / "scenario-config-keycloak-tiny-ubuntu-24.04.yml"
        config_evidence.write_text(config_content, encoding="utf-8")
        config_sha = hashlib.sha256(config_content.encode()).hexdigest()
        (dependencies / "test-application-dependencies.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "profile": "tiny",
                    "scenario": "keycloak-tiny",
                    "target": "ubuntu-24.04",
                    "source_commit": "c" * 40,
                    "scenario_config": {
                        "path": "molecule/keycloak-tiny/molecule.yml",
                        "sha256": config_sha,
                        "evidence_file": config_evidence.name,
                    },
                    "applications": [
                        {
                            "type": "container",
                            "name": "quay.io/keycloak/keycloak:26.5.4",
                            "version": "sha256:" + "a" * 64,
                            "digest": "sha256:" + "a" * 64,
                            "source": "runtime-container",
                            "source_inventory": "container-image-digests.json",
                            "evidence_sha256": hashlib.sha256(container_inventory.read_bytes()).hexdigest(),
                        }
                    ],
                    "disposition": None,
                    "descriptor": None,
                }
            ),
            encoding="utf-8",
        )
        self._bind_registry_policy(
            root,
            {
                "mode": "runtime-container",
                "reason": (
                    "Scenario deploys and verifies independently versioned application containers; "
                    "immutable runtime digests are mandatory."
                ),
                "dependencies": [],
            },
        )
        candidate_files = {
            "MANIFEST.json": json.dumps(
                {
                    "collection_info": {
                        "namespace": "lit",
                        "name": "supplementary",
                        "version": "1.40.0",
                        "dependencies": {"community.general": ">=11.4.9,<12.0.0"},
                    }
                }
            ).encode(),
            "meta/source-dependencies.yml": source_inventory.read_bytes(),
            "collections/requirements-rh.yml": requirements.read_bytes(),
            "roles/demo_deploy/defaults/main.yml": shipped_default.read_bytes(),
            "roles/aap_deploy/defaults/main.yml": aap_default.read_bytes(),
            "roles/aap_deploy/tasks/40_install.yml": aap_install.read_bytes(),
            (
                "roles/aap_local_execution/templates/aap-local/inventories/group_vars/aaps/aap.yml.j2"
            ): aap_template.read_bytes(),
        }
        with tarfile.open(candidate, "w:gz") as archive:
            for filename, content in candidate_files.items():
                member = tarfile.TarInfo(filename)
                member.size = len(content)
                archive.addfile(member, fileobj=io.BytesIO(content))
        return {
            "candidate": candidate,
            "galaxy": galaxy,
            "sbom": sbom,
            "dependencies": root,
        }

    def _use_declared_application(self, root: Path, *, disposition: bool = False) -> Path:
        dependencies = root / "cell" / "dependencies"
        inventory_path = dependencies / "test-application-dependencies.json"
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        if disposition:
            reason = "This scenario has no separate test application dependency."
            policy: dict[str, object] = {
                "mode": "not-applicable",
                "reason": reason,
                "dependencies": [],
            }
            inventory["applications"] = []
            inventory["disposition"] = {"status": "not-applicable", "reason": reason}
        else:
            policy = {
                "mode": "declared-evidence",
                "reason": "Scenario exercises a versioned host client whose version output is captured as evidence.",
                "dependencies": [
                    {
                        "type": "host-package",
                        "name": "demo-client",
                        "version": "3.2.1",
                        "evidence_path": "test-applications/keycloak-tiny/demo-client-version.txt",
                    }
                ],
            }
            declared_evidence = root / "cell" / "test-applications" / "keycloak-tiny" / "demo-client-version.txt"
            declared_evidence.parent.mkdir(parents=True)
            declared_evidence.write_text("demo-client 3.2.1\n", encoding="utf-8")
            inventory["applications"] = [
                {
                    "type": "host-package",
                    "name": "demo-client",
                    "version": "3.2.1",
                    "source": "declared-evidence",
                    "evidence_path": "test-applications/keycloak-tiny/demo-client-version.txt",
                    "evidence_sha256": hashlib.sha256(declared_evidence.read_bytes()).hexdigest(),
                }
            ]
            inventory["disposition"] = None
        inventory["descriptor"] = None
        inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
        self._bind_registry_policy(root, policy)
        return inventory_path

    def test_installed_candidate_is_not_duplicated_or_self_referenced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._fixture(Path(directory))
            payload = SBOM.enrich_sbom(
                candidate=paths["candidate"],
                sbom_path=paths["sbom"],
                galaxy_path=paths["galaxy"],
                dependencies_root=paths["dependencies"],
                source_sha="c" * 40,
            )
            root_ref = "pkg:ansible/lit/supplementary@1.40.0"
            component_refs = [item["bom-ref"] for item in payload["components"]]
            self.assertEqual(len(component_refs), len(set(component_refs)))
            self.assertNotIn(root_ref, component_refs)
            root_relation = next(item for item in payload["dependencies"] if item["ref"] == root_ref)
            self.assertNotIn(root_ref, root_relation["dependsOn"])
            self.assertIn(
                "pkg:ansible/community/general@11.4.9%2Bvendor",
                root_relation["dependsOn"],
            )
            self.assertTrue(any(item.get("purl") == "pkg:pypi/pyyaml@6.0.3%2Blocal" for item in payload["components"]))
            self.assertTrue(
                any(
                    item["type"] == "application" and item["name"] == "quay.io/keycloak/keycloak:26.5.4"
                    for item in payload["components"]
                )
            )
            self.assertTrue(
                any(
                    item["type"] == "container"
                    and item["name"] == "docker.io/example/runtime:1.0"
                    and item["version"] == "sha256:" + "d" * 64
                    for item in payload["components"]
                )
            )
            self.assertTrue(
                any(item["name"] == "aap_utilities" and item["version"] == "3.3.0" for item in payload["components"])
            )
            self.assertTrue(
                any(
                    item["name"] == "red-hat-ansible-automation-platform" and item["version"] == "2.7"
                    for item in payload["components"]
                )
            )
            root_properties = payload["metadata"]["component"]["properties"]
            self.assertTrue(any(item["name"] == "lit:source-dependencies:sha256" for item in root_properties))

    def test_cell_bound_target_python_inventory_is_validated_and_ingested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._fixture(Path(directory))
            inventory = Path(directory) / "cell" / "dependencies" / "python-packages-keycloak-acceptance-target.json"
            inventory.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source": "target-venv",
                        "profile": "application-acceptance",
                        "scenario": "keycloak-application-acceptance",
                        "target": "ubuntu-24.04",
                        "source_commit": "c" * 40,
                        "packages": [
                            {"name": "Flask", "version": "3.1.2"},
                            {"name": "Authlib", "version": "1.6.4"},
                            {"name": "playwright", "version": "1.55.0"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            browser_inventory = (
                Path(directory) / "cell" / "dependencies" / "browser-runtime-keycloak-acceptance-target.json"
            )
            browser_inventory.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source": "playwright-target-runtime",
                        "profile": "application-acceptance",
                        "scenario": "keycloak-application-acceptance",
                        "target": "ubuntu-24.04",
                        "source_commit": "c" * 40,
                        "playwright_version": "1.55.0",
                        "chromium": {
                            "name": "chromium",
                            "channel": "chrome",
                            "version": "140.0.7339.16",
                            "executable": "/opt/google/chrome/chrome",
                            "sha256": "e" * 64,
                        },
                        "operating_system": {
                            "id": "ubuntu",
                            "version_id": "24.04",
                            "distro": "ubuntu-24.04",
                        },
                        "os_packages": [
                            {
                                "name": "libc++6",
                                "version": "1:2.39+really2.39-0ubuntu8.4",
                                "architecture": "amd64",
                                "source_name": "glibc++",
                                "source_version": "1:2.39+really2.39-0ubuntu8.4",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            payload = SBOM.enrich_sbom(
                candidate=paths["candidate"],
                sbom_path=paths["sbom"],
                galaxy_path=paths["galaxy"],
                dependencies_root=paths["dependencies"],
                source_sha="c" * 40,
            )
            target_flask = next(
                component
                for component in payload["components"]
                if component["name"] == "Flask" and component["bom-ref"].startswith("urn:lit:target-python-package:")
            )
            properties = {item["name"]: item["value"] for item in target_flask["properties"]}
            self.assertEqual("target-python", properties["lit:dependency:source"])
            self.assertEqual("application-acceptance", properties["lit:dependency:profile"])
            self.assertEqual("keycloak-application-acceptance", properties["lit:dependency:scenario"])
            self.assertEqual("ubuntu-24.04", properties["lit:dependency:target"])
            chromium = next(
                component
                for component in payload["components"]
                if component["name"] == "chromium" and component["bom-ref"].startswith("urn:lit:target-browser:")
            )
            self.assertEqual("e" * 64, chromium["hashes"][0]["content"])
            self.assertEqual(
                "cpe:2.3:a:google:chrome:140.0.7339.16:*:*:*:*:*:*:*",
                chromium["cpe"],
            )
            properties = {item["name"]: item["value"] for item in chromium["properties"]}
            self.assertEqual("chrome", properties["lit:dependency:browser-channel"])
            self.assertTrue(
                any(
                    component["name"] == "libc++6"
                    and component["bom-ref"].startswith("urn:lit:target-os-package:")
                    and "/libc%2B%2B6@1:2.39%2Breally2.39-0ubuntu8.4?" in component["purl"]
                    and "distro=ubuntu-24.04" in component["purl"]
                    and "upstream=pkg%3Adeb%2Fubuntu%2Fglibc%252B%252B%401%3A2.39%252Breally2.39-0ubuntu8.4"
                    in component["purl"]
                    for component in payload["components"]
                )
            )

            inventory_payload = json.loads(inventory.read_text(encoding="utf-8"))
            inventory_payload["source_commit"] = "d" * 40
            inventory.write_text(json.dumps(inventory_payload), encoding="utf-8")
            with self.assertRaisesRegex(SBOM.SbomError, "unbound target Python"):
                SBOM.enrich_sbom(
                    candidate=paths["candidate"],
                    sbom_path=paths["sbom"],
                    galaxy_path=paths["galaxy"],
                    dependencies_root=paths["dependencies"],
                    source_sha="c" * 40,
                )

    def test_root_version_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._fixture(Path(directory))
            inventory = next(paths["dependencies"].rglob("collection-dependencies.json"))
            payload = json.loads(inventory.read_text(encoding="utf-8"))
            payload["collection_info"]["lit.supplementary"]["version"] = "9.9.9"
            inventory.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(SBOM.SbomError, "differs from the SBOM root"):
                SBOM.enrich_sbom(
                    candidate=paths["candidate"],
                    sbom_path=paths["sbom"],
                    galaxy_path=paths["galaxy"],
                    dependencies_root=paths["dependencies"],
                    source_sha="c" * 40,
                )

    def test_candidate_source_dependency_binding_rejects_tampering(self) -> None:
        cases = ("candidate-default", "candidate-inventory", "source-inventory")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = self._fixture(root)
                if case == "candidate-default":
                    default = root / "roles/demo_deploy/defaults/main.yml"
                    tampered = default.read_bytes().replace(b"d" * 64, b"e" * 64)
                    self._replace_candidate_member(
                        paths["candidate"],
                        "roles/demo_deploy/defaults/main.yml",
                        tampered,
                    )
                    expected = "container dependency inventory differs"
                elif case == "candidate-inventory":
                    inventory = root / "meta/source-dependencies.yml"
                    self._replace_candidate_member(
                        paths["candidate"],
                        "meta/source-dependencies.yml",
                        inventory.read_bytes() + b"# tampered\n",
                    )
                    expected = "candidate dependency inventory differs"
                else:
                    inventory = root / "meta/source-dependencies.yml"
                    inventory.write_bytes(inventory.read_bytes() + b"# changed source\n")
                    expected = "candidate dependency inventory differs"
                with self.assertRaisesRegex(SBOM.SbomError, expected):
                    SBOM.enrich_sbom(
                        candidate=paths["candidate"],
                        sbom_path=paths["sbom"],
                        galaxy_path=paths["galaxy"],
                        dependencies_root=paths["dependencies"],
                        source_sha="c" * 40,
                    )

    def test_duplicate_component_refs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._fixture(Path(directory))
            payload = json.loads(paths["sbom"].read_text(encoding="utf-8"))
            component = {"type": "library", "name": "x", "bom-ref": "duplicate"}
            payload["components"] = [component, dict(component)]
            paths["sbom"].write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(SBOM.SbomError, "duplicate"):
                SBOM.enrich_sbom(
                    candidate=paths["candidate"],
                    sbom_path=paths["sbom"],
                    galaxy_path=paths["galaxy"],
                    dependencies_root=paths["dependencies"],
                    source_sha="c" * 40,
                )

    def test_missing_test_application_inventory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._fixture(Path(directory))
            inventory = next(paths["dependencies"].rglob("test-application-dependencies.json"))
            inventory.unlink()
            with self.assertRaisesRegex(SBOM.SbomError, "test_application"):
                SBOM.enrich_sbom(
                    candidate=paths["candidate"],
                    sbom_path=paths["sbom"],
                    galaxy_path=paths["galaxy"],
                    dependencies_root=paths["dependencies"],
                    source_sha="c" * 40,
                )

    def test_declared_and_not_applicable_applications_are_supported(self) -> None:
        for disposition in (False, True):
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = self._fixture(root)
                self._use_declared_application(root, disposition=disposition)
                payload = SBOM.enrich_sbom(
                    candidate=paths["candidate"],
                    sbom_path=paths["sbom"],
                    galaxy_path=paths["galaxy"],
                    dependencies_root=paths["dependencies"],
                    source_sha="c" * 40,
                )
                if disposition:
                    properties = payload["metadata"]["component"]["properties"]
                    self.assertTrue(any(item["name"].endswith(":disposition") for item in properties))
                else:
                    self.assertTrue(
                        any(
                            item["type"] == "library" and item["name"] == "demo-client"
                            for item in payload["components"]
                        )
                    )

    def test_test_application_source_and_registry_tampering_is_rejected(self) -> None:
        cases = (
            "commit",
            "config",
            "registry-copy",
            "registry-digest",
            "inventory-policy",
            "descriptor",
            "old-schema",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = self._fixture(root)
                inventory_path = next(root.rglob("test-application-dependencies.json"))
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                expected = ""
                if case == "commit":
                    inventory["source_commit"] = "d" * 40
                    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
                    expected = "malformed test-application identity"
                elif case == "config":
                    (root / "molecule" / "keycloak-tiny" / "molecule.yml").write_text(
                        "---\ndriver:\n  name: docker\n", encoding="utf-8"
                    )
                    expected = "scenario config differs from exact source"
                elif case == "registry-copy":
                    evidence_name = inventory["registry_policy"]["evidence_file"]
                    (inventory_path.parent / evidence_name).write_text("scenarios: {}\n", encoding="utf-8")
                    expected = "registry differs from exact source"
                elif case == "registry-digest":
                    inventory["registry_policy"]["sha256"] = "d" * 64
                    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
                    expected = "registry differs from exact source"
                elif case == "inventory-policy":
                    inventory["test_application_policy"]["mode"] = "not-applicable"
                    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
                    expected = "policy differs from the bound registry"
                elif case == "descriptor":
                    inventory["descriptor"] = {
                        "path": "molecule/keycloak-tiny/test-application-dependencies.yml",
                        "sha256": "a" * 64,
                        "evidence_file": "forged.yml",
                    }
                    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
                    expected = "descriptor cannot override registry policy"
                else:
                    inventory["schema_version"] = 1
                    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
                    expected = "malformed test-application identity"
                with self.assertRaisesRegex(SBOM.SbomError, expected):
                    SBOM.enrich_sbom(
                        candidate=paths["candidate"],
                        sbom_path=paths["sbom"],
                        galaxy_path=paths["galaxy"],
                        dependencies_root=paths["dependencies"],
                        source_sha="c" * 40,
                    )

    def test_registry_policy_modes_cannot_be_overridden(self) -> None:
        cases = ("runtime-as-not-applicable", "declared-as-runtime", "not-applicable-with-runtime")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = self._fixture(root)
                inventory_path = next(root.rglob("test-application-dependencies.json"))
                runtime_application = json.loads(inventory_path.read_text(encoding="utf-8"))["applications"][0]
                if case == "runtime-as-not-applicable":
                    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                    inventory["applications"] = []
                    inventory["disposition"] = {
                        "status": "not-applicable",
                        "reason": inventory["test_application_policy"]["reason"],
                    }
                    expected = "runtime-container policy requires runtime applications"
                elif case == "declared-as-runtime":
                    inventory_path = self._use_declared_application(root)
                    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                    inventory["applications"][0]["source"] = "runtime-container"
                    expected = "differs from declared-evidence registry policy"
                else:
                    inventory_path = self._use_declared_application(root, disposition=True)
                    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                    inventory["applications"] = [runtime_application]
                    inventory["disposition"] = None
                    expected = "not-applicable disposition differs from registry policy"
                inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
                with self.assertRaisesRegex(SBOM.SbomError, expected):
                    SBOM.enrich_sbom(
                        candidate=paths["candidate"],
                        sbom_path=paths["sbom"],
                        galaxy_path=paths["galaxy"],
                        dependencies_root=paths["dependencies"],
                        source_sha="c" * 40,
                    )

    def test_declared_application_claim_must_exactly_match_registry(self) -> None:
        for case in ("identity", "evidence-path"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = self._fixture(root)
                inventory_path = self._use_declared_application(root)
                inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                if case == "identity":
                    inventory["applications"][0]["name"] = "forged-client"
                else:
                    alternate = root / "cell" / "dependencies" / "alternate-client-version.txt"
                    alternate.write_text("demo-client 3.2.1\n", encoding="utf-8")
                    inventory["applications"][0]["evidence_path"] = "dependencies/alternate-client-version.txt"
                    inventory["applications"][0]["evidence_sha256"] = hashlib.sha256(alternate.read_bytes()).hexdigest()
                inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
                with self.assertRaisesRegex(SBOM.SbomError, "differ from the bound registry policy"):
                    SBOM.enrich_sbom(
                        candidate=paths["candidate"],
                        sbom_path=paths["sbom"],
                        galaxy_path=paths["galaxy"],
                        dependencies_root=paths["dependencies"],
                        source_sha="c" * 40,
                    )


if __name__ == "__main__":
    unittest.main()
