"""No-credential tests for the coupled native transition preparation."""

import importlib.util
import traceback
import unittest
from copy import deepcopy
from pathlib import Path

from ansible.errors import AnsibleFilterError

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("native_transition", ROOT / "plugins/filter/keycloak_native_migration.py")
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


def fixtures():
    components = {}
    for name in ("keycloak", "postgres"):
        manifest_path = f"/etc/podman/pods/{name}.yml"
        description = f"{name} fixture service"
        image = "example.invalid/" + name + "@sha256:" + ("1" if name == "keycloak" else "2") * 64
        host_data = f"/srv/fixture/{name}"
        container_data = "/data"
        networks = ["database.network:ip=192.0.2." + ("2" if name == "keycloak" else "3")]
        manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name},
            "spec": {
                "containers": [
                    {
                        "name": name,
                        "image": image,
                        "ports": [{"containerPort": 8080, "hostPort": 8080, "hostIP": "127.0.0.1"}],
                        "env": [
                            {"name": "KC_DB_URL_HOST", "value": "fixture-database"},
                            {"name": "KC_DB_URL_PORT", "value": "5432"},
                            {"name": "TEST_CANARY", "value": "SYNTHETIC-NOT-A-CREDENTIAL"},
                        ],
                        "volumeMounts": [{"name": "data", "mountPath": container_data}],
                    }
                ],
                "volumes": [{"name": "data", "hostPath": {"path": host_data, "type": "DirectoryOrCreate"}}],
            },
        }
        components[name] = {
            "description": description,
            "manifest_path": manifest_path,
            "pod_name": name,
            "container_name": name,
            "image": image,
            "host_data_dir": host_data,
            "container_data_dir": container_data,
            "previous_networks": [],
            "networks": networks,
            "manifest": manifest,
            "network_runtime_names": {"database.network": "database"},
            "quadlet_content": NATIVE.quadlet_text(description, manifest_path, []),
        }
    return components


class KeycloakNativeMigrationPlanTests(unittest.TestCase):
    def test_managed_container_alias_does_not_require_renaming_the_database_pod(self):
        components = fixtures()
        components["postgres"]["pod_name"] = "keycloak-postgres"
        components["postgres"]["manifest"]["metadata"]["name"] = "keycloak-postgres"
        self.assertTrue(
            NATIVE.private_database_endpoint_valid(
                "postgres",
                components["keycloak"]["networks"],
                components["postgres"]["networks"],
                "keycloak-postgres",
                "postgres",
            )
        )
        result = NATIVE.prepare_transition(components, "postgres", 5432)
        self.assertEqual(result["components"]["postgres"]["manifest"], components["postgres"]["manifest"])
        self.assertEqual(
            result["components"]["keycloak"]["manifest"]["spec"]["hostAliases"],
            [{"ip": "192.0.2.3", "hostnames": ["postgres"]}],
        )
        for host in ("other", "postgres.example.invalid", "POSTGRES", "postgres\n", "8.8.8.8"):
            with self.subTest(host=host), self.assertRaises(AnsibleFilterError):
                NATIVE.prepare_transition(components, host, 5432)

    def test_dns_runtime_requires_exclusively_the_bound_private_peer(self):
        components = fixtures()
        output = "192.0.2.3 STREAM postgres\n192.0.2.3 DGRAM\n192.0.2.3 RAW\n"
        self.assertTrue(NATIVE.database_resolution_valid(output, components, "postgres"))
        for invalid in (
            "",
            "192.0.2.4 STREAM postgres",
            output + "8.8.8.8 STREAM postgres\n",
            "::1 STREAM postgres",
            "192.0.2.3",
            None,
        ):
            with self.subTest(output=invalid), self.assertRaises(AnsibleFilterError):
                NATIVE.database_resolution_valid(invalid, components, "postgres")

    def test_dns_binding_selects_only_the_unique_shared_static_database_network(self):
        keycloak = ["database.network:ip=192.0.2.2"]
        postgres = ["database.network:ip=192.0.2.3", "backup.network:ip=198.51.100.3"]
        self.assertTrue(NATIVE.private_database_endpoint_valid("postgres", keycloak, postgres, "postgres"))
        for peers in (["other.network"], keycloak + ["backup.network"]):
            with self.subTest(peers=peers), self.assertRaises(AnsibleFilterError):
                NATIVE.private_database_endpoint_valid("postgres", peers, postgres, "postgres")

    def test_all_port_bindings_must_be_literal_loopback_addresses(self):
        for address in ("127.0.0.1", "127.0.0.2", "127.255.255.254", "::1"):
            components = fixtures()
            for component in components.values():
                component["manifest"]["spec"]["containers"][0]["ports"][0]["hostIP"] = address
            with self.subTest(address=address):
                result = NATIVE.prepare_transition(components, "postgres", 5432)
                for name in components:
                    self.assertEqual(
                        result["components"][name]["manifest"]["spec"]["containers"][0]["ports"],
                        components[name]["manifest"]["spec"]["containers"][0]["ports"],
                    )
        rejected = ("0.0.0.0", "::", "10.0.0.2", "fe80::1", "localhost", "", None, 2130706433)  # noqa: S104 -- rejection fixture.
        for address in rejected:
            for name in ("keycloak", "postgres"):
                components = fixtures()
                ports = components[name]["manifest"]["spec"]["containers"][0]["ports"]
                ports.append({"containerPort": 9000, "hostPort": 9000, "hostIP": address})
                with self.subTest(address=address, component=name), self.assertRaises(AnsibleFilterError):
                    NATIVE.prepare_transition(components, "postgres", 5432)

    def test_dynamic_database_peer_keeps_exact_network_and_private_endpoint_binding(self):
        components = fixtures()
        components["keycloak"]["networks"] = ["database.network", "proxy.network"]
        for host in ("postgres", "192.0.2.3"):
            with self.subTest(host=host):
                self.assertTrue(
                    NATIVE.private_database_endpoint_valid(
                        host, components["keycloak"]["networks"], components["postgres"]["networks"], "postgres"
                    )
                )
                self.assertTrue(NATIVE.prepare_transition(components, host, 5432)["changed"])
        for keycloak, postgres in (
            (["other.network"], ["database.network:ip=192.0.2.3"]),
            (["database.network:ip=192.0.2.3"], ["database.network:ip=192.0.2.3"]),
            (["database.network"], ["database.network:ip=8.8.8.8"]),
            (["database.network"], ["database.network"]),
        ):
            with self.subTest(keycloak=keycloak, postgres=postgres), self.assertRaises(AnsibleFilterError):
                NATIVE.private_database_endpoint_valid("postgres", keycloak, postgres, "postgres")

    def test_dynamic_additional_networks_keep_name_binding_without_pinning_address(self):
        components = fixtures()
        records = {}
        for name, component in components.items():
            component["networks"].append("proxy.network")
            component["previous_networks"] = component["networks"].copy()
            component["network_runtime_names"]["proxy.network"] = "proxy"
            component["quadlet_content"] = NATIVE.quadlet_text(
                component["description"], component["manifest_path"], component["networks"]
            )
            component["manifest"]["spec"]["containers"][0]["env"][0]["value"] = "postgres"
            records[name] = {
                "ImageName": component["image"],
                "Mounts": [
                    {
                        "Source": component["host_data_dir"],
                        "Destination": component["container_data_dir"],
                        "Type": "bind",
                        "RW": True,
                    }
                ],
                "NetworkSettings": {
                    "Networks": {
                        "database": {"IPAddress": "192.0.2." + ("2" if name == "keycloak" else "3")},
                        "proxy": {"IPAddress": "192.0.2.9"},
                    }
                },
                "Config": {"Env": ["KC_DB_URL_HOST=postgres", "KC_DB_URL_PORT=5432"]},
            }
        captured = NATIVE.capture_original_runtime(components, records)
        self.assertIsNone(captured["keycloak"]["original_runtime"]["static_networks"]["proxy"])
        plan = NATIVE.prepare_transition(components, "postgres", 5432)
        self.assertTrue(plan["changed"])
        for name, prepared in plan["components"].items():
            components[name].update(prepared)
        self.assertFalse(NATIVE.prepare_transition(components, "postgres", 5432)["changed"])
        for desired in (True, False):
            changed = deepcopy(records)
            changed["keycloak"]["NetworkSettings"]["Networks"]["proxy"]["IPAddress"] = "192.0.2.10"
            self.assertTrue(NATIVE.runtime_valid(captured, changed, "postgres", 5432, desired))
            for drift in ("static", "missing", "extra", "empty", "invalid"):
                altered = deepcopy(changed)
                networks = altered["keycloak"]["NetworkSettings"]["Networks"]
                if drift == "static":
                    networks["database"]["IPAddress"] = "192.0.2.4"
                elif drift == "missing":
                    del networks["proxy"]
                elif drift == "extra":
                    networks["other"] = {"IPAddress": "192.0.2.11"}
                else:
                    networks["proxy"]["IPAddress"] = "" if drift == "empty" else "not-an-address"
                with self.subTest(desired=desired, drift=drift), self.assertRaises(AnsibleFilterError):
                    NATIVE.runtime_valid(captured, altered, "postgres", 5432, desired)
                with self.subTest(pre_stop=drift), self.assertRaises(AnsibleFilterError):
                    NATIVE.capture_original_runtime(components, altered)

    def test_exact_managed_database_dns_name_is_supported_without_loosening_bindings(self):
        components = fixtures()
        result = NATIVE.prepare_transition(components, "postgres", 5432)
        environment = result["components"]["keycloak"]["manifest"]["spec"]["containers"][0]["env"]
        self.assertEqual(environment[0]["value"], "postgres")
        expected_aliases = [{"ip": "192.0.2.3", "hostnames": ["postgres"]}]
        self.assertEqual(result["components"]["keycloak"]["manifest"]["spec"]["hostAliases"], expected_aliases)
        for name, prepared in result["components"].items():
            components[name].update(prepared)
        self.assertFalse(NATIVE.prepare_transition(components, "postgres", 5432)["changed"])
        for aliases in (
            [{"ip": "192.0.2.4", "hostnames": ["postgres"]}],
            [{"ip": "192.0.2.3", "hostnames": ["other"]}],
            expected_aliases + [{"ip": "192.0.2.4", "hostnames": ["other"]}],
        ):
            altered = deepcopy(components)
            altered["keycloak"]["manifest"]["spec"]["hostAliases"] = aliases
            with self.subTest(aliases=aliases), self.assertRaises(AnsibleFilterError):
                NATIVE.prepare_transition(altered, "postgres", 5432)
        self.assertTrue(
            NATIVE.private_database_endpoint_valid(
                "postgres", components["keycloak"]["networks"], components["postgres"]["networks"], "postgres"
            )
        )
        for host in ("other-database", "postgres.attacker.invalid", "localhost", "POSTGRES", "postgres\n"):
            with self.subTest(host=host), self.assertRaises(AnsibleFilterError):
                NATIVE.prepare_transition(components, host, 5432)
        components["keycloak"]["networks"] = ["other.network:ip=192.0.2.2"]
        with self.assertRaises(AnsibleFilterError):
            NATIVE.prepare_transition(components, "postgres", 5432)

    def test_prepares_both_networks_and_database_endpoint_without_other_changes(self):
        components = fixtures()
        original = deepcopy(components)
        result = NATIVE.prepare_transition(components, "192.0.2.3", 5432)
        self.assertTrue(result["changed"])
        self.assertEqual(components, original, "Preparation must never mutate caller snapshots")
        self.assertEqual(result["components"]["postgres"]["manifest"], components["postgres"]["manifest"])
        expected = deepcopy(components["keycloak"]["manifest"])
        expected["spec"]["containers"][0]["env"][0]["value"] = "192.0.2.3"
        self.assertEqual(result["components"]["keycloak"]["manifest"], expected)
        for name in components:
            self.assertIn("Network=database.network:", result["components"][name]["quadlet_content"])

    def test_second_preparation_is_idempotent(self):
        components = fixtures()
        first = NATIVE.prepare_transition(components, "192.0.2.3", 5432)
        for name, prepared in first["components"].items():
            components[name].update(prepared)
        self.assertFalse(NATIVE.prepare_transition(components, "192.0.2.3", 5432)["changed"])

    def test_foreign_unit_is_rejected_without_leaking_contents(self):
        components = fixtures()
        components["postgres"]["quadlet_content"] += "ExecStart=SYNTHETIC-NOT-A-CREDENTIAL\n"
        with self.assertRaises(AnsibleFilterError) as error:
            NATIVE.prepare_transition(components, "192.0.2.3", 5432)
        self.assertNotIn("SYNTHETIC-NOT-A-CREDENTIAL", str(error.exception))

    def test_mixed_controller_state_is_rejected(self):
        components = fixtures()
        component = components["postgres"]
        component["quadlet_content"] = NATIVE.quadlet_text(
            component["description"], component["manifest_path"], component["networks"]
        )
        with self.assertRaises(AnsibleFilterError):
            NATIVE.prepare_transition(components, "192.0.2.3", 5432)

    def test_image_upgrade_and_data_move_are_not_network_migrations(self):
        for field, value in (
            ("image", "example.invalid/postgres@sha256:" + "3" * 64),
            ("host_data_dir", "/srv/other-data"),
        ):
            with self.subTest(field=field):
                components = fixtures()
                components["postgres"][field] = value
                with self.assertRaises(AnsibleFilterError):
                    NATIVE.prepare_transition(components, "192.0.2.3", 5432)

    def test_duplicate_or_missing_database_field_is_rejected(self):
        for duplicate in (True, False):
            components = fixtures()
            environment = components["keycloak"]["manifest"]["spec"]["containers"][0]["env"]
            if duplicate:
                environment.append(deepcopy(environment[0]))
            else:
                environment.pop(0)
            with self.assertRaises(AnsibleFilterError):
                NATIVE.prepare_transition(components, "192.0.2.3", 5432)

    def test_public_ports_and_competing_manifest_network_settings_rejected(self):
        for field in ("public-port", "network-annotation", "host-alias"):
            components = fixtures()
            manifest = components["keycloak"]["manifest"]
            if field == "public-port":
                manifest["spec"]["containers"][0]["ports"][0]["hostIP"] = "0.0.0.0"  # noqa: S104 -- rejection fixture.
            elif field == "network-annotation":
                manifest["metadata"]["annotations"] = {"io.podman.annotations.networks": "other"}
            else:
                manifest["spec"]["hostAliases"] = [{"ip": "192.0.2.7", "hostnames": ["fixture-database"]}]
            with self.assertRaises(AnsibleFilterError):
                NATIVE.prepare_transition(components, "192.0.2.3", 5432)

    def test_invalid_address_and_duplicate_network_are_rejected(self):
        for value in ("hostname.invalid", "192.0.2.999"):
            with self.assertRaises(AnsibleFilterError):
                NATIVE.prepare_transition(fixtures(), value, 5432)
        components = fixtures()
        components["keycloak"]["networks"] *= 2
        with self.assertRaises(AnsibleFilterError):
            NATIVE.prepare_transition(components, "192.0.2.3", 5432)

    def test_database_endpoint_must_match_shared_network_without_address_collision(self):
        for variant in ("wrong-endpoint", "different-network", "same-address", "ambiguous-endpoint"):
            with self.subTest(variant=variant):
                components = fixtures()
                endpoint = "192.0.2.3"
                if variant == "wrong-endpoint":
                    endpoint = "192.0.2.4"
                elif variant == "different-network":
                    components["keycloak"]["networks"] = ["other.network:ip=192.0.2.2"]
                elif variant == "same-address":
                    components["keycloak"]["networks"] = ["database.network:ip=192.0.2.3"]
                else:
                    components["postgres"]["networks"].append("other.network:ip=192.0.2.3")
                with self.assertRaises(AnsibleFilterError):
                    NATIVE.prepare_transition(components, endpoint, 5432)

    def test_managed_paths_must_be_canonical_absolute_paths(self):
        for field in ("manifest_path", "host_data_dir", "container_data_dir"):
            for value in ("relative/path", "/srv/../other", "//srv/other", "/srv/other/", "/srv/other\x00"):
                with self.subTest(field=field, value=value):
                    components = fixtures()
                    components["postgres"][field] = value
                    with self.assertRaises(AnsibleFilterError):
                        NATIVE.prepare_transition(components, "192.0.2.3", 5432)

    def test_database_address_requires_string_and_error_traceback_redacts_inputs(self):
        for endpoint in (True, 3221225987, "SYNTHETIC-NOT-A-CREDENTIAL"):
            with self.subTest(endpoint=endpoint):
                try:
                    NATIVE.prepare_transition(fixtures(), endpoint, 5432)
                except AnsibleFilterError as error:
                    rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
                    self.assertNotIn("SYNTHETIC-NOT-A-CREDENTIAL", rendered)
                    self.assertIsNone(error.__cause__)
                    self.assertTrue(error.__suppress_context__)
                else:
                    self.fail("Nonliteral database address accepted")

    def test_network_parser_error_traceback_redacts_input(self):
        components = fixtures()
        components["postgres"]["networks"] = ["database.network:ip=999.999.999.999"]
        try:
            NATIVE.prepare_transition(components, "192.0.2.3", 5432)
        except AnsibleFilterError as error:
            rendered = "".join(traceback.format_exception(type(error), error, error.__traceback__))
            self.assertNotIn("999.999.999.999", rendered)
            self.assertIsNone(error.__cause__)
        else:
            self.fail("Invalid network address accepted")

    def test_runtime_checks_detect_image_mount_network_and_endpoint_drift(self):
        components = fixtures()
        records = {}
        for name, component in components.items():
            records[name] = {
                "ImageName": component["image"],
                "Mounts": [
                    {
                        "Source": component["host_data_dir"],
                        "Destination": component["container_data_dir"],
                        "Type": "bind",
                        "RW": True,
                    }
                ],
                "NetworkSettings": {
                    "Networks": {"database": {"IPAddress": "192.0.2." + ("2" if name == "keycloak" else "3")}}
                },
                "Config": {"Env": ["KC_DB_URL_HOST=192.0.2.3", "KC_DB_URL_PORT=5432"]},
            }
        self.assertTrue(NATIVE.runtime_valid(components, records, "192.0.2.3", 5432))
        for drift in ("image", "mount", "network", "network-name", "endpoint"):
            with self.subTest(drift=drift):
                changed = deepcopy(records)
                if drift == "image":
                    changed["postgres"]["ImageName"] = "example.invalid/postgres@sha256:" + "3" * 64
                elif drift == "mount":
                    changed["postgres"]["Mounts"][0]["Source"] = "/srv/other"
                elif drift == "network":
                    changed["postgres"]["NetworkSettings"]["Networks"]["database"]["IPAddress"] = "192.0.2.4"
                elif drift == "network-name":
                    changed["postgres"]["NetworkSettings"]["Networks"]["other"] = changed["postgres"][
                        "NetworkSettings"
                    ]["Networks"].pop("database")
                else:
                    changed["keycloak"]["Config"]["Env"][0] = "KC_DB_URL_HOST=other"
                with self.assertRaises(AnsibleFilterError):
                    NATIVE.runtime_valid(components, changed, "192.0.2.3", 5432)

    def test_pre_stop_validation_and_rollback_preserve_original_network_and_endpoint(self):
        components = fixtures()
        records = {}
        for name, component in components.items():
            records[name] = {
                "ImageName": component["image"],
                "Mounts": [
                    {
                        "Source": component["host_data_dir"],
                        "Destination": component["container_data_dir"],
                        "Type": "bind",
                        "RW": True,
                    }
                ],
                "NetworkSettings": {
                    "Networks": {
                        "podman-default-kube-network": {"IPAddress": "192.0.2." + ("7" if name == "keycloak" else "8")}
                    }
                },
                "Config": {"Env": ["KC_DB_URL_HOST=fixture-database", "KC_DB_URL_PORT=5432"]},
            }
        original = deepcopy(components)
        captured = NATIVE.capture_original_runtime(components, records)
        self.assertEqual(components, original)
        self.assertTrue(NATIVE.runtime_valid(captured, records, "postgres", 5432, False))
        moved = deepcopy(records)
        moved["postgres"]["NetworkSettings"]["Networks"]["podman-default-kube-network"]["IPAddress"] = "192.0.2.9"
        self.assertTrue(NATIVE.runtime_valid(captured, moved, "postgres", 5432, False))
        for name in ("keycloak", "postgres"):
            extra = deepcopy(records)
            extra[name]["NetworkSettings"]["Networks"]["manual-extra"] = {"IPAddress": "192.0.2.10"}
            with self.subTest(implicit_extra=name), self.assertRaises(AnsibleFilterError):
                NATIVE.capture_original_runtime(components, extra)
        for drift in ("image", "mount", "endpoint", "network-name"):
            changed = deepcopy(records)
            if drift == "image":
                changed["postgres"]["ImageName"] = "example.invalid/postgres@sha256:" + "3" * 64
            elif drift == "mount":
                changed["postgres"]["Mounts"][0]["RW"] = False
            elif drift == "endpoint":
                changed["keycloak"]["Config"]["Env"][0] = "KC_DB_URL_HOST=other"
            else:
                changed["postgres"]["NetworkSettings"]["Networks"] = {"other": {"IPAddress": "192.0.2.8"}}
            with self.subTest(drift=drift), self.assertRaises(AnsibleFilterError):
                NATIVE.runtime_valid(captured, changed, "postgres", 5432, False)
            with self.subTest(pre_stop=drift), self.assertRaises(AnsibleFilterError):
                NATIVE.capture_original_runtime(components, changed)

    def test_unmapped_network_and_unproven_rollback_are_rejected(self):
        components = fixtures()
        records = {}
        for name, component in components.items():
            records[name] = {
                "ImageName": component["image"],
                "Mounts": [
                    {
                        "Source": component["host_data_dir"],
                        "Destination": component["container_data_dir"],
                        "Type": "bind",
                        "RW": True,
                    }
                ],
                "NetworkSettings": {
                    "Networks": {"database": {"IPAddress": "192.0.2." + ("2" if name == "keycloak" else "3")}}
                },
                "Config": {"Env": ["KC_DB_URL_HOST=fixture-database", "KC_DB_URL_PORT=5432"]},
            }
        with self.assertRaises(AnsibleFilterError):
            NATIVE.runtime_valid(components, records, "postgres", 5432, False)
        components["postgres"]["network_runtime_names"] = {}
        with self.assertRaises(AnsibleFilterError):
            NATIVE.capture_original_runtime(components, records)

    def test_pre_stop_binding_selects_proven_old_or_desired_quadlet_state(self):
        components = fixtures()
        records = {}
        for name, component in components.items():
            address = "192.0.2." + ("7" if name == "keycloak" else "8")
            component["previous_networks"] = ["old.network:ip=" + address]
            component["network_runtime_names"]["old.network"] = "old"
            component["quadlet_content"] = NATIVE.quadlet_text(
                component["description"], component["manifest_path"], component["previous_networks"]
            )
            records[name] = {
                "ImageName": component["image"],
                "Mounts": [
                    {
                        "Source": component["host_data_dir"],
                        "Destination": component["container_data_dir"],
                        "Type": "bind",
                        "RW": True,
                    }
                ],
                "NetworkSettings": {"Networks": {"old": {"IPAddress": address}}},
                "Config": {"Env": ["KC_DB_URL_HOST=fixture-database", "KC_DB_URL_PORT=5432"]},
            }
        captured = NATIVE.capture_original_runtime(components, records)
        self.assertEqual(captured["postgres"]["original_runtime"]["static_networks"], {"old": "192.0.2.8"})
        restored_wrong = deepcopy(records)
        restored_wrong["postgres"]["NetworkSettings"]["Networks"]["old"]["IPAddress"] = "192.0.2.9"
        with self.assertRaises(AnsibleFilterError):
            NATIVE.runtime_valid(captured, restored_wrong, "postgres", 5432, False)
        prepared = NATIVE.prepare_transition(components, "postgres", 5432)
        for name, component in components.items():
            component.update(prepared["components"][name])
            records[name]["NetworkSettings"]["Networks"] = {
                "database": {"IPAddress": "192.0.2." + ("2" if name == "keycloak" else "3")}
            }
        records["keycloak"]["Config"]["Env"][0] = "KC_DB_URL_HOST=postgres"
        self.assertFalse(NATIVE.prepare_transition(components, "postgres", 5432)["changed"])
        NATIVE.capture_original_runtime(components, records)
        for drift in ("wrong-name", "wrong-ip"):
            changed = deepcopy(records)
            if drift == "wrong-name":
                changed["postgres"]["NetworkSettings"]["Networks"] = {"other": {"IPAddress": "192.0.2.3"}}
            else:
                changed["postgres"]["NetworkSettings"]["Networks"]["database"]["IPAddress"] = "192.0.2.4"
            with self.subTest(drift=drift), self.assertRaises(AnsibleFilterError):
                NATIVE.capture_original_runtime(components, changed)


if __name__ == "__main__":
    unittest.main()
