"""Bind a CycloneDX SBOM to the collection candidate and tested dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from source_dependencies import (  # noqa: E402
    SourceDependencyError,
    validate_source_dependencies,
)

TEST_APPLICATION_MODES = {
    "runtime-container",
    "declared-evidence",
    "not-applicable",
}
DECLARED_APPLICATION_TYPES = {
    "application",
    "external-api",
    "host-package",
    "host-service",
}
MUTABLE_APPLICATION_VERSIONS = {
    "latest",
    "n/a",
    "not-applicable",
    "unknown",
    "unversioned",
    "unspecified",
}


class SbomError(ValueError):
    """Raised when SBOM identity or dependency evidence is unsafe."""


def _os_package_purl(
    *,
    os_id: str,
    distro: str,
    name: str,
    version: str,
    architecture: str,
    source_name: str,
    source_version: str,
) -> str:
    purl_type = "deb/ubuntu" if os_id == "ubuntu" else "rpm/redhat"
    package_version = version
    package_epoch: str | None = None
    source_purl_version = source_version
    source_epoch: str | None = None
    if os_id == "rhel":
        package_match = re.fullmatch(r"(?:(?P<epoch>[0-9]+):)?(?P<version>[^:]+)", version)
        source_match = re.fullmatch(r"(?:(?P<epoch>[0-9]+):)?(?P<version>[^:]+)", source_version)
        if package_match is None or source_match is None:
            raise SbomError("malformed RPM epoch/version identity")
        package_epoch = package_match.group("epoch")
        package_version = package_match.group("version")
        source_epoch = source_match.group("epoch")
        source_purl_version = source_match.group("version")

    upstream = f"pkg:{purl_type}/{quote(source_name, safe='._-')}@{quote(source_purl_version, safe='._:-')}"
    if source_epoch is not None:
        upstream += f"?epoch={source_epoch}"
    qualifiers = {
        "arch": architecture,
        "distro": distro,
        "upstream": upstream,
    }
    if package_epoch is not None:
        qualifiers["epoch"] = package_epoch
    encoded_qualifiers = "&".join(
        f"{key}={quote(value, safe='._-') if key != 'upstream' else quote(value, safe='')}"
        for key, value in sorted(qualifiers.items())
    )
    return f"pkg:{purl_type}/{quote(name, safe='._-')}@{quote(package_version, safe='._:-')}?{encoded_qualifiers}"


def _json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SbomError(f"cannot read JSON object {path}: {error}") from error
    if not isinstance(payload, dict):
        raise SbomError(f"expected JSON object: {path}")
    return payload


def _collection_identity(galaxy_path: Path) -> tuple[str, str, str]:
    try:
        galaxy = yaml.safe_load(galaxy_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise SbomError(f"cannot read collection identity: {error}") from error
    if not isinstance(galaxy, dict):
        raise SbomError("galaxy.yml must be a mapping")
    identity = tuple(str(galaxy.get(field, "")).strip() for field in ("namespace", "name", "version"))
    if not all(identity):
        raise SbomError("galaxy.yml has incomplete collection identity")
    return identity  # type: ignore[return-value]


def _registry_test_application_policy(
    *,
    dependency: Path,
    galaxy_path: Path,
    inventory: dict[str, Any],
    scenario: str,
    target: str,
) -> dict[str, Any]:
    binding = inventory.get("registry_policy")
    inventory_policy = inventory.get("test_application_policy")
    if (
        not isinstance(binding, dict)
        or set(binding) != {"path", "sha256", "evidence_file"}
        or not isinstance(inventory_policy, dict)
    ):
        raise SbomError(f"missing test-application registry policy binding: {dependency}")

    registry_path = Path(str(binding.get("path", "")))
    registry_file = Path(str(binding.get("evidence_file", "")))
    registry_digest = str(binding.get("sha256", ""))
    expected_registry_path = Path("meta/role-coverage.yml")
    expected_registry_file = Path(f"role-coverage-{scenario}-{target}.yml")
    if (
        registry_path != expected_registry_path
        or registry_path.is_absolute()
        or ".." in registry_path.parts
        or registry_file != expected_registry_file
        or registry_file.is_absolute()
        or ".." in registry_file.parts
        or len(registry_file.parts) != 1
        or re.fullmatch(r"[0-9a-f]{64}", registry_digest) is None
    ):
        raise SbomError(f"unsafe test-application registry policy binding: {dependency}")

    evidence_registry = dependency.parent / registry_file
    source_registry = galaxy_path.parent / registry_path
    try:
        if evidence_registry.is_symlink() or source_registry.is_symlink():
            raise OSError("registry bindings cannot be symlinks")
        if evidence_registry.stat().st_size > 8 * 1024 * 1024 or source_registry.stat().st_size > 8 * 1024 * 1024:
            raise OSError("registry binding exceeds the size limit")
        evidence_registry_bytes = evidence_registry.read_bytes()
        source_registry_bytes = source_registry.read_bytes()
    except OSError as error:
        raise SbomError(f"cannot bind test-application registry policy: {error}") from error
    evidence_registry_digest = hashlib.sha256(evidence_registry_bytes).hexdigest()
    source_registry_digest = hashlib.sha256(source_registry_bytes).hexdigest()
    if (
        registry_digest != evidence_registry_digest
        or evidence_registry_digest != source_registry_digest
        or evidence_registry_bytes != source_registry_bytes
    ):
        raise SbomError(f"test-application registry differs from exact source: {dependency}")

    try:
        registry = yaml.safe_load(source_registry_bytes) or {}
    except yaml.YAMLError as error:
        raise SbomError(f"cannot parse test-application registry policy: {error}") from error
    if not isinstance(registry, dict):
        raise SbomError(f"malformed test-application registry policy: {dependency}")
    scenarios = registry.get("scenarios")
    scenario_entry = scenarios.get(scenario) if isinstance(scenarios, dict) else None
    source_policy = scenario_entry.get("test_application") if isinstance(scenario_entry, dict) else None
    if not isinstance(source_policy, dict):
        raise SbomError(f"registry lacks test-application policy for {scenario}: {dependency}")
    assert isinstance(scenario_entry, dict)
    if inventory_policy != source_policy:
        raise SbomError(f"test-application policy differs from the bound registry: {dependency}")
    if (
        source_policy.get("mode") == "not-applicable"
        and scenario_entry.get("state") == "supported"
        and scenario_entry.get("implementation") == "real"
    ):
        raise SbomError(f"supported real scenario cannot declare test applications not applicable: {dependency}")
    return source_policy


def _declared_policy_claims(
    policy: dict[str, Any],
    dependency: Path,
    scenario: str,
) -> list[dict[str, str]]:
    if set(policy) != {"mode", "reason", "dependencies"}:
        raise SbomError(f"malformed test-application registry policy: {dependency}")
    mode = policy.get("mode")
    reason = policy.get("reason")
    raw_claims = policy.get("dependencies")
    if (
        mode not in TEST_APPLICATION_MODES
        or not isinstance(reason, str)
        or reason != reason.strip()
        or not 20 <= len(reason) <= 500
        or any(ord(character) < 32 for character in reason)
        or not isinstance(raw_claims, list)
    ):
        raise SbomError(f"malformed test-application registry policy: {dependency}")
    if mode != "declared-evidence":
        if raw_claims:
            raise SbomError(f"non-declared test-application policy has dependencies: {dependency}")
        return []
    if not raw_claims:
        raise SbomError(f"declared test-application policy has no dependencies: {dependency}")

    claims: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_claim in raw_claims:
        if not isinstance(raw_claim, dict):
            raise SbomError(f"malformed declared registry dependency: {dependency}")
        required_keys = {"type", "name", "version", "evidence_path"}
        if (
            not required_keys.issubset(raw_claim)
            or not set(raw_claim).issubset(required_keys | {"digest"})
            or any(not isinstance(raw_claim[key], str) for key in required_keys)
            or ("digest" in raw_claim and not isinstance(raw_claim["digest"], str))
        ):
            raise SbomError(f"malformed declared registry dependency: {dependency}")
        claim = {key: str(raw_claim[key]) for key in required_keys}
        if "digest" in raw_claim:
            claim["digest"] = str(raw_claim["digest"])
        evidence_path = Path(claim["evidence_path"])
        if (
            claim["type"] not in DECLARED_APPLICATION_TYPES
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", claim["name"]) is None
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+:/@-]{0,127}", claim["version"]) is None
            or claim["version"].lower() in MUTABLE_APPLICATION_VERSIONS
            or not claim["evidence_path"]
            or evidence_path.is_absolute()
            or ".." in evidence_path.parts
            or evidence_path.parts[:2] != ("test-applications", scenario)
            or evidence_path.as_posix() != claim["evidence_path"]
            or ("digest" in claim and re.fullmatch(r"sha256:[0-9a-f]{64}", claim["digest"]) is None)
        ):
            raise SbomError(f"malformed declared registry dependency: {dependency}")
        identity = (claim["type"], claim["name"], claim["version"])
        if identity in seen:
            raise SbomError(f"duplicate declared registry dependency: {dependency}")
        seen.add(identity)
        claims.append(claim)
    return claims


def enrich_sbom(
    *,
    candidate: Path,
    sbom_path: Path,
    galaxy_path: Path,
    dependencies_root: Path,
    source_sha: str,
) -> dict[str, Any]:
    namespace, name, version = _collection_identity(galaxy_path)
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise SbomError("source commit must be a full lowercase SHA")
    try:
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError as error:
        raise SbomError(f"cannot read candidate: {error}") from error
    try:
        source_dependencies = validate_source_dependencies(
            root=galaxy_path.parent.resolve(),
            candidate=candidate,
        )
    except SourceDependencyError as error:
        raise SbomError(f"shipped source dependency validation failed: {error}") from error

    payload = _json_object(sbom_path)
    if payload.get("bomFormat") != "CycloneDX":
        raise SbomError("Syft did not produce a CycloneDX JSON object")
    metadata = payload.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise SbomError("CycloneDX metadata must be an object")
    root_ref = f"pkg:ansible/{namespace}/{name}@{version}"
    metadata["component"] = {
        "type": "library",
        "group": namespace,
        "name": name,
        "version": version,
        "bom-ref": root_ref,
        "purl": root_ref,
        "hashes": [{"alg": "SHA-256", "content": digest}],
        "properties": [
            {"name": "lit:candidate:filename", "value": candidate.name},
            {"name": "lit:candidate:commit", "value": source_sha},
            {
                "name": "lit:source-dependencies:path",
                "value": "meta/source-dependencies.yml",
            },
            {
                "name": "lit:source-dependencies:sha256",
                "value": str(source_dependencies["sha256"]),
            },
            {
                "name": "lit:source-dependencies:commit",
                "value": source_sha,
            },
        ],
    }

    components = payload.get("components", [])
    if not isinstance(components, list):
        raise SbomError("CycloneDX components must be an array")
    by_ref: dict[str, dict[str, Any]] = {}
    seen_refs = {root_ref}
    for component in components:
        if not isinstance(component, dict):
            raise SbomError("CycloneDX component entries must be objects")
        reference = component.get("bom-ref")
        if not isinstance(reference, str) or not reference:
            raise SbomError("every CycloneDX component requires a bom-ref")
        if reference in seen_refs:
            raise SbomError(f"duplicate or root-colliding component bom-ref: {reference}")
        seen_refs.add(reference)
        by_ref[reference] = component

    added_refs: set[str] = set()
    counts = {
        "python": 0,
        "collection": 0,
        "container": 0,
        "incus": 0,
        "test_application": 0,
        "source_container": 0,
        "derived_container": 0,
        "source_collection": 0,
        "external_product": 0,
        "browser": 0,
        "os_package": 0,
    }
    runtime_application_required = False
    target_python_cells: set[tuple[str, str, str]] = set()
    target_browser_cells: set[tuple[str, str, str]] = set()
    target_playwright_versions: dict[tuple[str, str, str], str] = {}
    target_browser_playwright_versions: dict[tuple[str, str, str], str] = {}

    def add_component(component: dict[str, Any], category: str) -> None:
        reference = component.get("bom-ref")
        if not isinstance(reference, str) or not reference:
            raise SbomError("generated dependency component has no bom-ref")
        if reference == root_ref:
            raise SbomError("collection dependency inventory contains the SBOM root")
        if reference not in by_ref:
            by_ref[reference] = component
            components.append(component)
        added_refs.add(reference)
        counts[category] += 1

    source_inventory = source_dependencies["inventory"]
    for image in source_inventory["container_images"]:
        exact_reference = str(image["reference"])
        tagged_reference, image_digest = exact_reference.rsplit("@", 1)
        repository, tag = tagged_reference.rsplit(":", 1)
        immutable = image_digest.removeprefix("sha256:")
        reference = f"urn:lit:shipped-container:sha256:{immutable}"
        purl = (
            f"pkg:oci/{quote(repository.rsplit('/', 1)[-1], safe='._-')}@"
            f"{quote(image_digest, safe=':')}?repository_url={quote(repository, safe='')}"
        )
        add_component(
            {
                "type": "container",
                "name": tagged_reference,
                "version": image_digest,
                "bom-ref": reference,
                "purl": purl,
                "hashes": [{"alg": "SHA-256", "content": immutable}],
                "properties": [
                    {"name": "lit:dependency:source", "value": "shipped-role-default"},
                    {"name": "lit:dependency:reference", "value": exact_reference},
                    {"name": "lit:dependency:tag", "value": tag},
                    {
                        "name": "lit:dependency:locations",
                        "value": ",".join(image["locations"]),
                    },
                    {"name": "lit:dependency:source-commit", "value": source_sha},
                    {
                        "name": "lit:dependency:inventory-sha256",
                        "value": str(source_dependencies["sha256"]),
                    },
                ],
            },
            "source_container",
        )

    for image in source_inventory["derived_images"]:
        local_reference = str(image["reference"])
        identity = hashlib.sha256(f"{local_reference}\0{image['base_reference']}\0{source_sha}".encode()).hexdigest()
        reference = f"urn:lit:derived-container:sha256:{identity}"
        add_component(
            {
                "type": "container",
                "name": local_reference,
                "version": f"source-commit-{source_sha}",
                "bom-ref": reference,
                "properties": [
                    {"name": "lit:dependency:source", "value": "local-build-output"},
                    {"name": "lit:dependency:disposition", "value": str(image["disposition"])},
                    {"name": "lit:dependency:build-file", "value": str(image["build_file"])},
                    {
                        "name": "lit:dependency:base-reference",
                        "value": str(image["base_reference"]),
                    },
                    {
                        "name": "lit:dependency:locations",
                        "value": ",".join(image["locations"]),
                    },
                    {"name": "lit:dependency:source-commit", "value": source_sha},
                ],
            },
            "derived_container",
        )

    for collection in source_inventory["collections"]:
        collection_name = str(collection["name"])
        requirement = str(collection["requirement"])
        collection_namespace, short_name = collection_name.split(".", 1)
        identity = hashlib.sha256(f"{collection_name}\0{requirement}\0{collection['source']}".encode()).hexdigest()
        reference = f"urn:lit:shipped-collection:sha256:{identity}"
        add_component(
            {
                "type": "library",
                "group": collection_namespace,
                "name": short_name,
                "version": requirement,
                "bom-ref": reference,
                "properties": [
                    {"name": "lit:dependency:source", "value": "shipped-collection-requirement"},
                    {"name": "lit:dependency:collection", "value": collection_name},
                    {"name": "lit:dependency:requirement", "value": requirement},
                    {"name": "lit:dependency:location", "value": str(collection["source"])},
                    {"name": "lit:dependency:source-commit", "value": source_sha},
                ],
            },
            "source_collection",
        )

    for product in source_inventory["external_products"]:
        product_name = str(product["name"])
        product_version = str(product["version"])
        reference = f"pkg:generic/{quote(product_name, safe='._-')}@{quote(product_version, safe='._-')}"
        add_component(
            {
                "type": str(product["type"]),
                "name": product_name,
                "version": product_version,
                "bom-ref": reference,
                "purl": reference,
                "properties": [
                    {"name": "lit:dependency:source", "value": "licensed-external-product"},
                    {"name": "lit:dependency:disposition", "value": str(product["disposition"])},
                    {"name": "lit:dependency:reason", "value": str(product["reason"])},
                    {
                        "name": "lit:dependency:provides-collections",
                        "value": ",".join(product["provides_collections"]),
                    },
                    {
                        "name": "lit:dependency:locations",
                        "value": ",".join(product["locations"]),
                    },
                    {"name": "lit:dependency:source-commit", "value": source_sha},
                ],
            },
            "external_product",
        )

    dependency_files = sorted(
        path for path in dependencies_root.rglob("*") if path.is_file() and "dependencies" in path.parts
    )
    if len(dependency_files) > 2_048:
        raise SbomError("dependency inventory exceeds the SBOM file limit")
    for dependency in dependency_files:
        if dependency.stat().st_size > 16 * 1024 * 1024:
            raise SbomError(f"oversized dependency inventory: {dependency}")
        filename = dependency.name
        if filename.startswith("python-packages") and dependency.suffix == ".json":
            python_inventory = json.loads(dependency.read_text(encoding="utf-8"))
            inventory_properties = [{"name": "lit:dependency:source", "value": "controller-python"}]
            target_cell: tuple[str, str, str] | None = None
            if isinstance(python_inventory, dict):
                expected_fields = {
                    "schema_version",
                    "source",
                    "profile",
                    "scenario",
                    "target",
                    "source_commit",
                    "packages",
                }
                profile = str(python_inventory.get("profile", ""))
                scenario = str(python_inventory.get("scenario", ""))
                target = str(python_inventory.get("target", ""))
                if (
                    set(python_inventory) != expected_fields
                    or python_inventory.get("schema_version") != 1
                    or python_inventory.get("source") != "target-venv"
                    or re.fullmatch(r"[a-z][a-z0-9-]{0,62}", profile) is None
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", scenario) is None
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", target) is None
                    or python_inventory.get("source_commit") != source_sha
                ):
                    raise SbomError(f"malformed or unbound target Python dependency inventory: {dependency}")
                packages = python_inventory.get("packages")
                target_cell = (profile, scenario, target)
                if target_cell[:2] == (
                    "application-acceptance",
                    "keycloak-application-acceptance",
                ):
                    target_python_cells.add(target_cell)
                inventory_properties = [
                    {"name": "lit:dependency:source", "value": "target-python"},
                    {"name": "lit:dependency:profile", "value": profile},
                    {"name": "lit:dependency:scenario", "value": scenario},
                    {"name": "lit:dependency:target", "value": target},
                    {"name": "lit:dependency:source-commit", "value": source_sha},
                ]
            else:
                packages = python_inventory
            if not isinstance(packages, list):
                raise SbomError(f"malformed Python dependency inventory: {dependency}")
            if target_cell is not None and target_cell[:2] == (
                "application-acceptance",
                "keycloak-application-acceptance",
            ):
                playwright_packages = [
                    package
                    for package in packages
                    if isinstance(package, dict) and str(package.get("name", "")).casefold() == "playwright"
                ]
                if len(playwright_packages) != 1 or target_cell in target_playwright_versions:
                    raise SbomError(f"target Python inventory lacks one unique Playwright identity: {dependency}")
                target_playwright_versions[target_cell] = str(playwright_packages[0].get("version", ""))
            for package in packages:
                if not isinstance(package, dict):
                    raise SbomError(f"malformed Python package entry: {dependency}")
                package_name = str(package.get("name", "")).strip()
                package_version = str(package.get("version", "")).strip()
                if not package_name or not package_version:
                    raise SbomError(f"incomplete Python package entry: {dependency}")
                purl = f"pkg:pypi/{quote(package_name.lower(), safe='._-')}@{quote(package_version, safe='._-')}"
                reference = purl
                if target_cell is not None:
                    cell_identity = hashlib.sha256(
                        ("\0".join((*target_cell, package_name.lower(), package_version, source_sha))).encode()
                    ).hexdigest()
                    reference = f"urn:lit:target-python-package:sha256:{cell_identity}"
                add_component(
                    {
                        "type": "library",
                        "name": package_name,
                        "version": package_version,
                        "bom-ref": reference,
                        "purl": purl,
                        "properties": inventory_properties,
                    },
                    "python",
                )
        elif filename.startswith("browser-runtime") and dependency.suffix == ".json":
            inventory = _json_object(dependency)
            expected_fields = {
                "schema_version",
                "source",
                "profile",
                "scenario",
                "target",
                "source_commit",
                "playwright_version",
                "chromium",
                "operating_system",
                "os_packages",
            }
            profile = str(inventory.get("profile", ""))
            scenario = str(inventory.get("scenario", ""))
            target = str(inventory.get("target", ""))
            cell = (profile, scenario, target)
            chromium = inventory.get("chromium")
            operating_system = inventory.get("operating_system")
            packages = inventory.get("os_packages")
            if (
                set(inventory) != expected_fields
                or inventory.get("schema_version") != 1
                or inventory.get("source") != "playwright-target-runtime"
                or cell[:2] != ("application-acceptance", "keycloak-application-acceptance")
                or target not in {"ubuntu-24.04", "rhel-9", "rhel-10"}
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", target) is None
                or inventory.get("source_commit") != source_sha
                or re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", str(inventory.get("playwright_version", ""))) is None
                or not isinstance(chromium, dict)
                or not isinstance(operating_system, dict)
                or not isinstance(packages, list)
                or not packages
            ):
                raise SbomError(f"malformed or unbound browser runtime inventory: {dependency}")
            if cell in target_browser_cells:
                raise SbomError(f"duplicate browser runtime inventory cell: {dependency}")
            assert isinstance(chromium, dict)
            assert isinstance(operating_system, dict)
            if (
                set(operating_system) != {"id", "version_id", "distro"}
                or operating_system.get("distro") != target
                or (
                    target == "ubuntu-24.04"
                    and (operating_system.get("id") != "ubuntu" or operating_system.get("version_id") != "24.04")
                )
                or (
                    target in {"rhel-9", "rhel-10"}
                    and (
                        operating_system.get("id") != "rhel"
                        or re.fullmatch(
                            target.removeprefix("rhel-") + r"(?:\.[0-9]+)*",
                            str(operating_system.get("version_id", "")),
                        )
                        is None
                    )
                )
            ):
                raise SbomError(f"browser operating system differs from target: {dependency}")
            if set(chromium) != {"name", "revision", "version", "executable", "sha256"}:
                raise SbomError(f"malformed Chromium runtime identity: {dependency}")
            revision = str(chromium.get("revision", ""))
            browser_version = str(chromium.get("version", ""))
            executable = Path(str(chromium.get("executable", "")))
            executable_digest = str(chromium.get("sha256", ""))
            if (
                chromium.get("name") != "chromium"
                or re.fullmatch(r"[0-9]+", revision) is None
                or re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", browser_version) is None
                or not executable.is_absolute()
                or not (
                    f"chromium-{revision}" in executable.parts
                    or f"chromium_headless_shell-{revision}" in executable.parts
                )
                or re.fullmatch(r"[0-9a-f]{64}", executable_digest) is None
            ):
                raise SbomError(f"malformed Chromium runtime identity: {dependency}")
            cell_identity = "\0".join((*cell, source_sha))
            browser_reference = f"urn:lit:target-browser:sha256:{hashlib.sha256(cell_identity.encode()).hexdigest()}"
            common_properties = [
                {"name": "lit:dependency:source", "value": "target-browser-runtime"},
                {"name": "lit:dependency:profile", "value": profile},
                {"name": "lit:dependency:scenario", "value": scenario},
                {"name": "lit:dependency:target", "value": target},
                {"name": "lit:dependency:distro", "value": str(operating_system["distro"])},
                {"name": "lit:dependency:source-commit", "value": source_sha},
            ]
            add_component(
                {
                    "type": "application",
                    "name": "chromium",
                    "version": browser_version,
                    "bom-ref": browser_reference,
                    "cpe": f"cpe:2.3:a:google:chrome:{browser_version}:*:*:*:*:*:*:*",
                    "hashes": [{"alg": "SHA-256", "content": executable_digest}],
                    "properties": common_properties
                    + [
                        {"name": "lit:dependency:playwright-version", "value": str(inventory["playwright_version"])},
                        {"name": "lit:dependency:browser-revision", "value": revision},
                        {"name": "lit:dependency:executable", "value": executable.as_posix()},
                        {
                            "name": "lit:dependency:scanner-cpe-rationale",
                            "value": "NVD maps Chromium security advisories to the Google Chrome CPE",
                        },
                    ],
                },
                "browser",
            )
            seen_os_packages: set[tuple[str, str, str]] = set()
            for package in packages:
                if not isinstance(package, dict) or set(package) != {
                    "name",
                    "version",
                    "architecture",
                    "source_name",
                    "source_version",
                }:
                    raise SbomError(f"malformed browser OS package inventory: {dependency}")
                package_name = str(package.get("name", ""))
                package_version = str(package.get("version", ""))
                architecture = str(package.get("architecture", ""))
                source_name = str(package.get("source_name", ""))
                source_version = str(package.get("source_version", ""))
                package_identity = (package_name, package_version, architecture)
                if (
                    package_identity in seen_os_packages
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+._-]{0,127}", package_name) is None
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+._-]{0,127}", source_name) is None
                    or not package_version
                    or not source_version
                    or len(package_version) > 256
                    or len(source_version) > 256
                    or any(ord(character) < 32 for character in package_version)
                    or any(ord(character) < 32 for character in source_version)
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", architecture) is None
                ):
                    raise SbomError(f"malformed browser OS package inventory: {dependency}")
                seen_os_packages.add(package_identity)
                purl = _os_package_purl(
                    os_id=str(operating_system["id"]),
                    distro=str(operating_system["distro"]),
                    name=package_name,
                    version=package_version,
                    architecture=architecture,
                    source_name=source_name,
                    source_version=source_version,
                )
                reference_identity = "\0".join((*cell, package_name, package_version, architecture, source_sha))
                reference = (
                    "urn:lit:target-os-package:sha256:" + hashlib.sha256(reference_identity.encode()).hexdigest()
                )
                add_component(
                    {
                        "type": "library",
                        "name": package_name,
                        "version": package_version,
                        "bom-ref": reference,
                        "purl": purl,
                        "properties": common_properties
                        + [
                            {"name": "lit:dependency:architecture", "value": architecture},
                            {"name": "lit:dependency:source-package", "value": source_name},
                            {"name": "lit:dependency:source-version", "value": source_version},
                        ],
                    },
                    "os_package",
                )
            target_browser_cells.add(cell)
            target_browser_playwright_versions[cell] = str(inventory["playwright_version"])
        elif filename.startswith("collection-dependencies") and dependency.suffix == ".json":
            collections = _json_object(dependency)
            for installed in collections.values():
                if not isinstance(installed, dict):
                    continue
                for fqcn, details in installed.items():
                    if not isinstance(details, dict) or "." not in str(fqcn):
                        continue
                    dependency_namespace, dependency_name = str(fqcn).split(".", 1)
                    dependency_version = str(details.get("version", "")).strip()
                    if not dependency_version:
                        raise SbomError(f"collection dependency has no version: {fqcn}")
                    if str(fqcn) == f"{namespace}.{name}":
                        if dependency_version != version:
                            raise SbomError("installed candidate version differs from the SBOM root")
                        continue
                    purl = (
                        f"pkg:ansible/{quote(dependency_namespace, safe='_-')}/"
                        f"{quote(dependency_name, safe='_-')}@"
                        f"{quote(dependency_version, safe='._-')}"
                    )
                    add_component(
                        {
                            "type": "library",
                            "group": dependency_namespace,
                            "name": dependency_name,
                            "version": dependency_version,
                            "bom-ref": purl,
                            "purl": purl,
                            "properties": [
                                {
                                    "name": "lit:dependency:source",
                                    "value": "ansible-collection",
                                }
                            ],
                        },
                        "collection",
                    )
        elif "container-image-digests" in filename and dependency.suffix == ".json":
            inventory = _json_object(dependency)
            if inventory.get("container_inventory_available") is not True:
                continue
            images = inventory.get("images", [])
            if not isinstance(images, list):
                raise SbomError(f"malformed container image inventory: {dependency}")
            for image in images:
                if not isinstance(image, dict):
                    raise SbomError(f"malformed container image entry: {dependency}")
                image_digest = str(image.get("Digest") or image.get("digest") or "")
                image_id = str(image.get("Id") or image.get("ID") or image.get("id") or "")
                immutable = (
                    image_digest if re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest) else image_id
                ).removeprefix("sha256:")
                if re.fullmatch(r"[0-9a-f]{64}", immutable) is None:
                    continue
                names = image.get("Names") or image.get("names") or []
                image_name = str(names[0]) if isinstance(names, list) and names else f"image-{immutable[:12]}"
                reference = f"urn:lit:container-image:sha256:{immutable}"
                add_component(
                    {
                        "type": "container",
                        "name": image_name,
                        "version": f"sha256:{immutable}",
                        "bom-ref": reference,
                        "hashes": [{"alg": "SHA-256", "content": immutable}],
                        "properties": [{"name": "lit:dependency:source", "value": "target-container"}],
                    },
                    "container",
                )
        elif filename.startswith("incus-base-image") and dependency.suffix == ".json":
            image = _json_object(dependency)
            fingerprint = str(image.get("fingerprint", ""))
            if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
                continue
            reference = f"urn:lit:incus-image:sha256:{fingerprint}"
            add_component(
                {
                    "type": "operating-system",
                    "name": "incus-base-image",
                    "version": fingerprint,
                    "bom-ref": reference,
                    "hashes": [{"alg": "SHA-256", "content": fingerprint}],
                    "properties": [{"name": "lit:dependency:source", "value": "incus-base-image"}],
                },
                "incus",
            )
        elif filename.startswith("test-application-dependencies") and dependency.suffix == ".json":
            inventory = _json_object(dependency)
            profile = str(inventory.get("profile", "")).strip()
            scenario = str(inventory.get("scenario", "")).strip()
            target = str(inventory.get("target", "")).strip()
            inventory_commit = str(inventory.get("source_commit", "")).strip()
            scenario_config = inventory.get("scenario_config")
            applications = inventory.get("applications")
            disposition = inventory.get("disposition")
            descriptor = inventory.get("descriptor")
            expected_inventory_fields = {
                "schema_version",
                "profile",
                "scenario",
                "target",
                "source_commit",
                "scenario_config",
                "registry_policy",
                "test_application_policy",
                "applications",
                "disposition",
                "descriptor",
            }
            if (
                set(inventory) != expected_inventory_fields
                or inventory.get("schema_version") != 2
                or profile not in {"tiny", "heavy", "application-acceptance"}
                or re.fullmatch(r"[A-Za-z0-9._-]+", scenario) is None
                or re.fullmatch(r"[A-Za-z0-9._-]+", target) is None
                or inventory_commit != source_sha
                or not isinstance(scenario_config, dict)
                or not isinstance(applications, list)
            ):
                raise SbomError(f"malformed test-application identity: {dependency}")
            config_path = Path(str(scenario_config.get("path", "")))
            evidence_file = Path(str(scenario_config.get("evidence_file", "")))
            config_digest = str(scenario_config.get("sha256", ""))
            expected_config = Path("molecule") / scenario / "molecule.yml"
            if (
                config_path != expected_config
                or config_path.is_absolute()
                or ".." in config_path.parts
                or evidence_file.is_absolute()
                or ".." in evidence_file.parts
                or len(evidence_file.parts) != 1
                or re.fullmatch(r"[0-9a-f]{64}", config_digest) is None
            ):
                raise SbomError(f"unsafe test-application scenario config: {dependency}")
            evidence_config = dependency.parent / evidence_file
            source_config = galaxy_path.parent / config_path
            try:
                evidence_config_digest = hashlib.sha256(evidence_config.read_bytes()).hexdigest()
                source_config_digest = hashlib.sha256(source_config.read_bytes()).hexdigest()
            except OSError as error:
                raise SbomError(f"cannot bind test-application scenario config: {error}") from error
            if config_digest not in {evidence_config_digest, source_config_digest} or (
                evidence_config_digest != source_config_digest
            ):
                raise SbomError(f"test-application scenario config differs from exact source: {dependency}")

            policy = _registry_test_application_policy(
                dependency=dependency,
                galaxy_path=galaxy_path,
                inventory=inventory,
                scenario=scenario,
                target=target,
            )
            declared_policy_claims = _declared_policy_claims(policy, dependency, scenario)
            policy_mode = str(policy["mode"])
            policy_reason = str(policy["reason"])
            if descriptor is not None:
                raise SbomError(f"test-application descriptor cannot override registry policy: {dependency}")
            if policy_mode == "runtime-container":
                if not applications or disposition is not None:
                    raise SbomError(f"runtime-container policy requires runtime applications: {dependency}")
                runtime_application_required = True
            elif policy_mode == "declared-evidence":
                if not applications or disposition is not None:
                    raise SbomError(f"declared-evidence policy requires declared applications: {dependency}")
            else:
                expected_disposition = {
                    "status": "not-applicable",
                    "reason": policy_reason,
                }
                if applications or disposition != expected_disposition:
                    raise SbomError(f"not-applicable disposition differs from registry policy: {dependency}")
                root_properties = metadata["component"].setdefault("properties", [])
                root_properties.append(
                    {
                        "name": f"lit:test-application:{scenario}:{target}:disposition",
                        "value": policy_reason,
                    }
                )
                counts["test_application"] += 1

            declared_inventory_claims: list[dict[str, str]] = []
            seen_inventory_claims: set[str] = set()
            seen_application_refs: set[str] = set()
            for application in applications:
                if not isinstance(application, dict):
                    raise SbomError(f"malformed test-application entry: {dependency}")
                application_type = str(application.get("type", "")).strip()
                application_name = str(application.get("name", "")).strip()
                application_version = str(application.get("version", "")).strip()
                application_source = str(application.get("source", "")).strip()
                application_digest = str(application.get("digest", "")).strip()
                evidence_digest = str(application.get("evidence_sha256", "")).strip()
                if (
                    not application_name
                    or not application_version
                    or re.fullmatch(r"[0-9a-f]{64}", evidence_digest) is None
                ):
                    raise SbomError(f"mutable or incomplete test application: {dependency}")
                if policy_mode == "runtime-container":
                    required_keys = {
                        "type",
                        "name",
                        "version",
                        "digest",
                        "source",
                        "source_inventory",
                        "evidence_sha256",
                    }
                    source_inventory_value = str(application.get("source_inventory", ""))
                    source_inventory_path = Path(source_inventory_value)
                    if (
                        set(application) != required_keys
                        or application_source != "runtime-container"
                        or application_type != "container"
                        or re.fullmatch(r"sha256:[0-9a-f]{64}", application_digest) is None
                        or application_version != application_digest
                        or not source_inventory_value
                        or source_inventory_path.is_absolute()
                        or ".." in source_inventory_path.parts
                        or source_inventory_path.as_posix() != source_inventory_value
                    ):
                        raise SbomError(f"application differs from runtime-container registry policy: {dependency}")
                    evidence_path = dependency.parent / source_inventory_path
                elif policy_mode == "declared-evidence":
                    required_keys = {
                        "type",
                        "name",
                        "version",
                        "source",
                        "evidence_path",
                        "evidence_sha256",
                    }
                    if not required_keys.issubset(application) or not set(application).issubset(
                        required_keys | {"digest"}
                    ):
                        raise SbomError(f"application differs from declared-evidence registry policy: {dependency}")
                    evidence_path_string = str(application.get("evidence_path", ""))
                    evidence_path_value = Path(evidence_path_string)
                    if (
                        application_source != "declared-evidence"
                        or application_type not in DECLARED_APPLICATION_TYPES
                        or application_version.lower() in MUTABLE_APPLICATION_VERSIONS
                        or not evidence_path_string
                        or evidence_path_value.is_absolute()
                        or ".." in evidence_path_value.parts
                        or evidence_path_value.as_posix() != evidence_path_string
                        or (
                            "digest" in application and re.fullmatch(r"sha256:[0-9a-f]{64}", application_digest) is None
                        )
                    ):
                        raise SbomError(f"application differs from declared-evidence registry policy: {dependency}")
                    evidence_path = dependency.parent.parent / evidence_path_value
                    claim = {
                        "type": application_type,
                        "name": application_name,
                        "version": application_version,
                        "evidence_path": evidence_path_string,
                    }
                    if "digest" in application:
                        claim["digest"] = application_digest
                    serialized_claim = json.dumps(claim, sort_keys=True)
                    if serialized_claim in seen_inventory_claims:
                        raise SbomError(f"duplicate declared test application: {dependency}")
                    seen_inventory_claims.add(serialized_claim)
                    declared_inventory_claims.append(claim)
                else:
                    raise SbomError(f"not-applicable policy contains test applications: {dependency}")
                try:
                    if evidence_path.is_symlink() or not 0 < evidence_path.stat().st_size <= 16 * 1024 * 1024:
                        raise OSError("test-application evidence is empty, oversized, or a symlink")
                    actual_evidence_digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
                except OSError as error:
                    raise SbomError(f"cannot read test-application evidence: {error}") from error
                if actual_evidence_digest != evidence_digest:
                    raise SbomError(f"test-application evidence digest differs: {dependency}")

                identity_digest = application_digest.removeprefix("sha256:") if application_digest else evidence_digest
                reference = (
                    "urn:lit:test-application:"
                    f"{quote(scenario, safe='._-')}:"
                    f"{quote(target, safe='._-')}:"
                    f"{quote(application_type, safe='._-')}:"
                    f"{quote(application_name, safe='._-')}:sha256:{identity_digest}"
                )
                if reference in seen_application_refs:
                    raise SbomError(f"duplicate test-application identity: {dependency}")
                seen_application_refs.add(reference)
                test_component: dict[str, Any] = {
                    "type": "library" if application_type == "host-package" else "application",
                    "name": application_name,
                    "version": application_version,
                    "bom-ref": reference,
                    "properties": [
                        {
                            "name": "lit:dependency:source",
                            "value": "test-application",
                        },
                        {"name": "lit:test:dependency-type", "value": application_type},
                        {"name": "lit:test:scenario", "value": scenario},
                        {"name": "lit:test:target", "value": target},
                        {"name": "lit:test:evidence-sha256", "value": evidence_digest},
                    ],
                }
                if application_digest:
                    test_component["hashes"] = [
                        {
                            "alg": "SHA-256",
                            "content": application_digest.removeprefix("sha256:"),
                        }
                    ]
                add_component(
                    test_component,
                    "test_application",
                )
            if policy_mode == "declared-evidence":
                serialized_policy_claims = sorted(json.dumps(claim, sort_keys=True) for claim in declared_policy_claims)
                serialized_inventory_claims = sorted(
                    json.dumps(claim, sort_keys=True) for claim in declared_inventory_claims
                )
                if serialized_inventory_claims != serialized_policy_claims:
                    raise SbomError(f"test applications differ from the bound registry policy: {dependency}")

    missing_browser_cells = sorted(target_python_cells - target_browser_cells)
    unexpected_browser_cells = sorted(target_browser_cells - target_python_cells)
    if missing_browser_cells or unexpected_browser_cells:
        details = ["/".join(cell) for cell in (*missing_browser_cells, *unexpected_browser_cells)]
        raise SbomError("browser runtime inventories differ from target Python cells: " + ", ".join(details))
    if target_browser_playwright_versions != target_playwright_versions:
        raise SbomError("browser runtime Playwright versions differ from target Python inventories")

    required_categories = {
        "python",
        "collection",
        "incus",
        "test_application",
        "source_container",
        "source_collection",
        "external_product",
    }
    if runtime_application_required:
        required_categories.add("container")
    if target_python_cells:
        required_categories.update({"browser", "os_package"})
    if source_inventory["derived_images"]:
        required_categories.add("derived_container")
    missing = sorted(category for category in required_categories if counts[category] == 0)
    if missing:
        raise SbomError(f"SBOM lacks required dependency classes: {', '.join(missing)}")
    if root_ref in added_refs:
        raise SbomError("SBOM root cannot depend on itself")
    payload["components"] = components
    relationships = payload.get("dependencies", [])
    if not isinstance(relationships, list):
        raise SbomError("CycloneDX dependencies must be an array")
    relationships = [
        relation for relation in relationships if not (isinstance(relation, dict) and relation.get("ref") == root_ref)
    ]
    relationships.append({"ref": root_ref, "dependsOn": sorted(added_refs)})
    payload["dependencies"] = relationships
    sbom_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--galaxy", type=Path, default=Path("galaxy.yml"))
    parser.add_argument("--dependencies-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    try:
        enrich_sbom(
            candidate=args.candidate,
            sbom_path=args.sbom,
            galaxy_path=args.galaxy,
            dependencies_root=args.dependencies_root,
            source_sha=args.source_sha,
        )
    except (OSError, json.JSONDecodeError, SbomError) as error:
        print(f"SBOM enrichment failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
