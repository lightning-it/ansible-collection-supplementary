"""Pure preparation of one coupled native Keycloak network transition."""

import ipaddress
import posixpath
import re
from copy import deepcopy

from ansible.errors import AnsibleFilterError

NETWORK_ENTRY = re.compile(
    r"(?P<unit>[A-Za-z0-9][A-Za-z0-9_.-]{0,127})"
    r"(?::ip=(?P<address>[0-9]{1,3}(?:[.][0-9]{1,3}){3})"
    r"(?:,alias=(?P<alias>[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))?)?"
)


def parse_network_entry(entry):
    """Return one exact Quadlet network binding without retaining option suffixes."""
    if not isinstance(entry, str):
        raise ValueError("network entry must be a string")
    match = NETWORK_ENTRY.fullmatch(entry)
    if match is None:
        raise ValueError("invalid exact native network binding")
    address = match.group("address")
    if address is not None:
        address = str(ipaddress.IPv4Address(address))
    return match.group("unit"), address, match.group("alias")


def canonical_path(value):
    """Reject relative, aliased and control-bearing managed path inputs."""
    return (
        isinstance(value, str)
        and value.startswith("/")
        and not value.startswith("//")
        and value != "/"
        and posixpath.normpath(value) == value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def database_binding(components, database_host):
    """Bind an IP or an exact managed Pod/container DNS name to its private network."""
    if not isinstance(database_host, str):
        raise ValueError("database endpoint must be a string")
    bindings = {}
    for name in ("keycloak", "postgres"):
        networks = components[name]["networks"]
        # Validate grammar and real IPv4 addresses even when the endpoint is a DNS name.
        quadlet_text("Binding validation", "/etc/fixture.yml", networks)
        bindings[name] = {}
        for entry in networks:
            network, address, alias = parse_network_entry(entry)
            bindings[name][network] = {"address": address, "alias": alias}
    pod_name = components["postgres"]["pod_name"]
    managed_names = {pod_name, components["postgres"].get("container_name")}
    managed_names.discard(None)
    aliases = {binding["alias"] for binding in bindings["postgres"].values() if binding["alias"]}
    if aliases & managed_names:
        raise ValueError("explicit database alias must not duplicate a managed PostgreSQL name")
    keycloak_names = {
        components["keycloak"].get("pod_name"),
        components["keycloak"].get("container_name"),
    }
    keycloak_names.discard(None)
    keycloak_names.update(binding["alias"] for binding in bindings["keycloak"].values() if binding["alias"])
    if database_host in keycloak_names:
        raise ValueError("database endpoint must be owned exclusively by PostgreSQL")
    if database_host in managed_names or database_host in aliases:
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", database_host):
            raise ValueError("invalid managed database DNS name")
        explicit_alias = database_host in aliases and database_host not in managed_names
        candidates = [
            network
            for network, binding in bindings["postgres"].items()
            if binding["address"] is not None
            and network in bindings["keycloak"]
            and (not explicit_alias or binding["alias"] == database_host)
        ]
    else:
        ipaddress.IPv4Address(database_host)
        candidates = [
            network for network, binding in bindings["postgres"].items() if binding["address"] == database_host
        ]
    if len(candidates) != 1:
        raise ValueError("database endpoint requires exactly one declared database network")
    network = candidates[0]
    address = bindings["postgres"][network]["address"]
    if (
        network not in bindings["keycloak"]
        or bindings["keycloak"][network]["address"] == address
        or bindings["keycloak"][network]["alias"] == database_host
        or not ipaddress.IPv4Address(address).is_private
    ):
        raise ValueError("database requires distinct private peer addresses on its declared network")
    return network


def private_database_endpoint_valid(
    database_host,
    keycloak_networks,
    postgres_networks,
    postgres_pod_name,
    postgres_container_name=None,
    keycloak_pod_name=None,
    keycloak_container_name=None,
):
    """Pure role precheck; DNS runtime proof remains mandatory before acceptance."""
    try:
        database_binding(
            {
                "keycloak": {
                    "networks": keycloak_networks,
                    "pod_name": keycloak_pod_name,
                    "container_name": keycloak_container_name,
                },
                "postgres": {
                    "networks": postgres_networks,
                    "pod_name": postgres_pod_name,
                    "container_name": postgres_container_name,
                },
            },
            database_host,
        )
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AnsibleFilterError("Managed private database endpoint rejected") from None


def database_resolution_valid(output, components, database_host):
    """Require every actual getent IPv4 result to equal the uniquely bound database peer."""
    try:
        network = database_binding(components, database_host)
        expected = components["postgres"]["networks"]
        address = next(parse_network_entry(entry)[1] for entry in expected if parse_network_entry(entry)[0] == network)
        if not isinstance(output, str) or not output.strip():
            raise ValueError("missing database resolution")
        addresses = set()
        for line in output.splitlines():
            fields = line.split()
            if len(fields) not in (2, 3) or fields[1] not in ("STREAM", "DGRAM", "RAW"):
                raise ValueError("invalid getent result")
            addresses.add(str(ipaddress.IPv4Address(fields[0])))
        if addresses != {address}:
            raise ValueError("database resolution drift")
        return True
    except (KeyError, TypeError, ValueError, AttributeError, StopIteration):
        raise AnsibleFilterError("Managed database DNS runtime validation rejected") from None


def quadlet_text(description, manifest_path, networks):
    """Use the existing role-owned Quadlet contract, not arbitrary file edits."""
    if not all(
        isinstance(value, str) and value and "\n" not in value and "\r" not in value
        for value in (description, manifest_path)
    ):
        raise AnsibleFilterError("Invalid native unit identity")
    if not canonical_path(manifest_path):
        raise AnsibleFilterError("Invalid native manifest path")
    if not isinstance(networks, list):
        raise AnsibleFilterError("Invalid exact native network bindings")
    try:
        parsed_networks = [parse_network_entry(network) for network in networks]
    except (TypeError, ValueError, AttributeError):
        raise AnsibleFilterError("Invalid exact native network bindings") from None
    if len({network[0] for network in parsed_networks}) != len(networks):
        raise AnsibleFilterError("Duplicate native network binding")
    return "\n".join(
        [
            "[Unit]",
            "Description=" + description,
            "After=network-online.target",
            "Wants=network-online.target",
            "[Kube]",
            "Yaml=" + manifest_path,
        ]
        + ["Network=" + network for network in networks]
        + ["[Install]", "WantedBy=multi-user.target", ""]
    )


def prepare_transition(components, database_host, database_port):
    """Validate both old units before preparing either desired configuration.

    Returned manifests contain secrets already present in the supplied manifests.
    Consumers MUST use no_log, memory-only snapshots and identity-bound writers.
    This filter does not authorize or execute any runtime mutation.
    """
    try:
        if not isinstance(database_host, str):
            raise ValueError("literal database address required")
        if not isinstance(database_port, int) or isinstance(database_port, bool) or not 1 <= database_port <= 65535:
            raise ValueError("invalid database port")
        if not isinstance(components, dict) or set(components) != {"keycloak", "postgres"}:
            raise ValueError("exactly two components required")
        prepared = {}
        states = []
        for name in ("keycloak", "postgres"):
            component = components[name]
            if not all(canonical_path(component[field]) for field in ("host_data_dir", "container_data_dir")):
                raise ValueError("canonical data paths required")
            old = quadlet_text(component["description"], component["manifest_path"], component["previous_networks"])
            new = quadlet_text(component["description"], component["manifest_path"], component["networks"])
            actual = component["quadlet_content"]
            actual_lines = [line for line in actual.splitlines() if line != ""]
            old_lines = [line for line in old.splitlines() if line != ""]
            new_lines = [line for line in new.splitlines() if line != ""]
            if actual_lines not in (old_lines, new_lines):
                raise ValueError("unproven native unit")
            states.append(actual_lines == new_lines)
            manifest = component["manifest"]
            if manifest.get("kind") != "Pod" or manifest.get("metadata", {}).get("name") != component["pod_name"]:
                raise ValueError("unproven pod identity")
            spec = manifest["spec"]
            if spec.get("hostNetwork", False) is not False or spec.get("hostAliases", []):
                raise ValueError("nonportable manifest networking")
            annotations = manifest.get("metadata", {}).get("annotations", {})
            if any("network" in key.lower() or key.lower().endswith(".ip") for key in annotations):
                raise ValueError("manifest owns competing network settings")
            containers = spec["containers"]
            if len(containers) != 1 or containers[0]["name"] != component["container_name"]:
                raise ValueError("unproven container identity")
            container = containers[0]
            image = component["image"]
            if not re.search(r"@sha256:[0-9a-f]{64}\Z", image):
                raise ValueError("immutable image required")
            if container["image"].split("@")[-1] != image.split("@")[-1]:
                raise ValueError("network transition cannot change image")
            data_mounts = [
                mount for mount in container["volumeMounts"] if mount["mountPath"] == component["container_data_dir"]
            ]
            if len(data_mounts) != 1 or data_mounts[0].get("readOnly", False):
                raise ValueError("unproven data mount")
            volumes = [volume for volume in spec["volumes"] if volume["name"] == data_mounts[0]["name"]]
            if len(volumes) != 1 or volumes[0].get("hostPath", {}).get("path") != component["host_data_dir"]:
                raise ValueError("network transition cannot change data directory")
            if not container.get("ports") or any(
                not isinstance(port.get("hostIP"), str) or not ipaddress.ip_address(port["hostIP"]).is_loopback
                for port in container["ports"]
            ):
                raise ValueError("loopback-only host bindings required")
            prepared[name] = {"quadlet_content": new, "manifest": deepcopy(manifest)}
        if len(set(states)) != 1:
            raise ValueError("mixed prior/desired controller state")
        database_binding(components, database_host)
        environment = prepared["keycloak"]["manifest"]["spec"]["containers"][0]["env"]
        for key, value in (("KC_DB_URL_HOST", database_host), ("KC_DB_URL_PORT", str(database_port))):
            matches = [entry for entry in environment if entry.get("name") == key]
            if len(matches) != 1 or set(matches[0]) != {"name", "value"}:
                raise ValueError("exact existing database fields required")
            matches[0]["value"] = value
        return {
            "changed": not all(states) or prepared["keycloak"]["manifest"] != components["keycloak"]["manifest"],
            "components": prepared,
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        # Never interpolate data: inputs may contain existing credentials.
        raise AnsibleFilterError("Native migration preparation rejected; no mutation authorized") from None


def runtime_identity_valid(component, record):
    """Shared pre-stop and post-start image/data identity boundary."""
    if record["ImageName"].split("@")[-1] != component["image"].split("@")[-1]:
        raise ValueError("runtime image drift")
    mounts = [mount for mount in record["Mounts"] if mount["Destination"] == component["container_data_dir"]]
    if (
        len(mounts) != 1
        or mounts[0]["Source"] != component["host_data_dir"]
        or mounts[0].get("Type") != "bind"
        or mounts[0].get("RW") is not True
    ):
        raise ValueError("runtime data drift")


def expected_runtime_networks(component, field="networks"):
    """Require explicit Quadlet-unit to Podman-name binding, never guess it."""
    quadlet_text("Runtime binding validation", "/etc/fixture.yml", component[field])
    expected = {}
    for entry in component[field]:
        unit, address, _alias = parse_network_entry(entry)
        name = component["network_runtime_names"][unit]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", name) or name in expected:
            raise ValueError("unproven network runtime identity")
        expected[name] = address
    return expected


def runtime_networks_match(actual, expected):
    """Bind every network name, but only pin explicitly declared addresses."""
    if set(actual) != set(expected):
        return False
    for name, address in actual.items():
        ipaddress.IPv4Address(address)
        if expected[name] is not None and address != expected[name]:
            return False
    return True


def database_environment(record):
    environment = record["Config"]["Env"]
    result = {}
    for key in ("KC_DB_URL_HOST", "KC_DB_URL_PORT"):
        matches = [entry for entry in environment if entry.startswith(key + "=")]
        if len(matches) != 1:
            raise ValueError("unproven runtime endpoint")
        result[key] = matches[0].split("=", 1)[1]
    return result


def capture_original_runtime(components, records):
    """Prove the running pair before stop and retain only rollback identity fields."""
    try:
        if set(components) != {"keycloak", "postgres"} or set(records) != set(components):
            raise ValueError("exact pair required")
        captured = deepcopy(components)
        for name, component in captured.items():
            record = records[name]
            runtime_identity_valid(component, record)
            # Prove desired mapping before any mutation, even for an implicit old network.
            expected_runtime_networks(component)
            actual = {network: value["IPAddress"] for network, value in record["NetworkSettings"]["Networks"].items()}
            if not actual or any(not address for address in actual.values()):
                raise ValueError("unproven original network")
            for address in actual.values():
                ipaddress.IPv4Address(address)
            current_lines = [line for line in component["quadlet_content"].splitlines() if line != ""]
            desired_lines = [
                line
                for line in quadlet_text(
                    component["description"], component["manifest_path"], component["networks"]
                ).splitlines()
                if line != ""
            ]
            previous_lines = [
                line
                for line in quadlet_text(
                    component["description"], component["manifest_path"], component["previous_networks"]
                ).splitlines()
                if line != ""
            ]
            if current_lines == desired_lines:
                bound = expected_runtime_networks(component)
            elif current_lines == previous_lines:
                bound = expected_runtime_networks(component, "previous_networks")
            else:
                raise ValueError("unproven current network controller")
            # Podman's non-host kube default when no Network option is supplied.
            # An arbitrary singleton or extra manual attachments cannot be
            # reconstructed by restoring the original empty Quadlet list.
            if not bound and set(actual) != {"podman-default-kube-network"}:
                raise ValueError("unreconstructable implicit original network")
            if bound and not runtime_networks_match(actual, bound):
                raise ValueError("current runtime network drift")
            component["original_runtime"] = {"network_names": sorted(actual), "static_networks": bound}
        original_db = database_environment(records["keycloak"])
        manifest_env = captured["keycloak"]["manifest"]["spec"]["containers"][0]["env"]
        for key, value in original_db.items():
            matches = [entry for entry in manifest_env if entry.get("name") == key]
            if len(matches) != 1 or matches[0].get("value") != value:
                raise ValueError("original database runtime/config drift")
        captured["keycloak"]["original_runtime"]["database_environment"] = original_db
        return captured
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AnsibleFilterError("Native pre-stop runtime validation rejected") from None


def runtime_valid(components, records, database_host, database_port, desired_networks=True):
    """Validate inspected runtime identity without returning credential-bearing data."""
    try:
        if set(components) != {"keycloak", "postgres"} or set(records) != set(components):
            raise ValueError("exact pair required")
        for name, component in components.items():
            record = records[name]
            runtime_identity_valid(component, record)
            actual = {network: value["IPAddress"] for network, value in record["NetworkSettings"]["Networks"].items()}
            if desired_networks:
                if not runtime_networks_match(actual, expected_runtime_networks(component)):
                    raise ValueError("runtime network drift")
            else:
                original = component["original_runtime"]
                if sorted(actual) != original["network_names"]:
                    raise ValueError("rollback network identity drift")
                if original["static_networks"] and not runtime_networks_match(actual, original["static_networks"]):
                    raise ValueError("rollback static address drift")
                if any(not value for value in actual.values()):
                    raise ValueError("rollback address missing")
                for address in actual.values():
                    ipaddress.IPv4Address(address)
        if desired_networks:
            if database_environment(records["keycloak"]) != {
                "KC_DB_URL_HOST": database_host,
                "KC_DB_URL_PORT": str(database_port),
            }:
                raise ValueError("runtime endpoint drift")
        elif (
            database_environment(records["keycloak"])
            != components["keycloak"]["original_runtime"]["database_environment"]
        ):
            raise ValueError("rollback endpoint drift")
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        raise AnsibleFilterError("Native migration runtime validation rejected") from None


class FilterModule:
    def filters(self):
        return {
            "keycloak_native_migration_plan": prepare_transition,
            "keycloak_native_runtime_valid": runtime_valid,
            "keycloak_native_snapshot_runtime": capture_original_runtime,
            "keycloak_database_resolution_valid": database_resolution_valid,
            "keycloak_private_database_endpoint_valid": private_database_endpoint_valid,
        }
