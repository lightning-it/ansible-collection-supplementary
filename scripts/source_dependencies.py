"""Validate the complete dependency inventory shipped in the collection."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

INVENTORY_PATH = PurePosixPath("meta/source-dependencies.yml")
OCI_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:(?:[a-z0-9][a-z0-9.-]*\.[a-z]{2,})|localhost)(?::[0-9]+)?/"
    r"[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+"
    r"(?:@sha256:[0-9a-f]{64})?)"
)
IMMUTABLE_OCI_REFERENCE = re.compile(
    r"(?:(?:[a-z0-9][a-z0-9.-]*\.[a-z]{2,})|localhost)(?::[0-9]+)?/"
    r"[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}"
)
COLLECTION_NAME = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")
FQCN_PREFIX = re.compile(r"^([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)\.[A-Za-z0-9_{]")
FQCN_ACTION = re.compile(r"([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)\.[a-z][a-z0-9_]*")
PLUGIN_REFERENCE = re.compile(
    r"(?:lookup|query)\(\s*['\"]"
    r"([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)\.[a-z][a-z0-9_]*"
)
SAFE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")
SAFE_REQUIREMENT = re.compile(r"[A-Za-z0-9<>=!~][A-Za-z0-9._+<>=,!~-]{0,127}")
DEPENDENCY_TEXT_SUFFIXES = {".json", ".j2", ".py", ".sh", ".toml", ".yaml", ".yml"}
NON_SHIPPED_ROOTS = {
    ".ansible",
    ".cache",
    ".git",
    ".github",
    ".lit",
    ".molecule",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "ansible_collections",
    "artifacts",
    "build",
    "dist",
    "extensions",
    "infra",
    "molecule",
    "node_modules",
    "tests",
}


class SourceDependencyError(ValueError):
    """Raised when the shipped dependency inventory is incomplete or unsafe."""


def _is_shipped_source_path(path: PurePosixPath) -> bool:
    return bool(path.parts) and path.parts[0] not in NON_SHIPPED_ROOTS and ".forgejo" not in path.parts


def _safe_relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str):
        raise SourceDependencyError("dependency location must be a string")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise SourceDependencyError(f"unsafe dependency location: {value!r}")
    return path


def _source_files(root: Path) -> dict[PurePosixPath, bytes]:
    files: dict[PurePosixPath, bytes] = {}
    total_bytes = 0
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if not _is_shipped_source_path(relative):
            continue
        if path.is_symlink():
            raise SourceDependencyError(f"source dependency file cannot be a symlink: {relative}")
        content = path.read_bytes()
        total_bytes += len(content)
        if len(files) >= 10_000 or total_bytes > 512 * 1024 * 1024:
            raise SourceDependencyError("shipped source exceeds dependency validation limits")
        files[relative] = content
    return files


def _candidate_files(candidate: Path) -> dict[PurePosixPath, bytes]:
    files: dict[PurePosixPath, bytes] = {}
    try:
        compressed_bytes = candidate.stat().st_size
        if not 0 < compressed_bytes <= 512 * 1024 * 1024:
            raise SourceDependencyError("collection candidate has an unsafe compressed size")
        with tarfile.open(candidate, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > 10_000:
                raise SourceDependencyError("collection candidate exceeds the file-count limit")
            total_bytes = 0
            for member in members:
                path = _safe_relative_path(member.name)
                if member.issym() or member.islnk():
                    raise SourceDependencyError(f"collection candidate contains a link: {path}")
                if member.isdir():
                    continue
                if not member.isfile() or member.size > 32 * 1024 * 1024:
                    raise SourceDependencyError(f"unsafe collection candidate member: {path}")
                total_bytes += member.size
                if total_bytes > 512 * 1024 * 1024:
                    raise SourceDependencyError("collection candidate exceeds the expansion limit")
                if path in files:
                    raise SourceDependencyError(f"duplicate collection candidate member: {path}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise SourceDependencyError(f"cannot read collection candidate member: {path}")
                files[path] = extracted.read()
            if total_bytes > compressed_bytes * 1_000:
                raise SourceDependencyError("collection candidate exceeds the compression-ratio limit")
    except (OSError, tarfile.TarError) as error:
        raise SourceDependencyError(f"cannot read collection candidate: {error}") from error
    return files


def _yaml_mapping(content: bytes, path: PurePosixPath) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(content) or {}
    except yaml.YAMLError as error:
        raise SourceDependencyError(f"cannot parse {path}: {error}") from error
    if not isinstance(payload, dict):
        raise SourceDependencyError(f"expected a mapping in {path}")
    return payload


def _required_file(files: dict[PurePosixPath, bytes], path: PurePosixPath) -> bytes:
    try:
        return files[path]
    except KeyError as error:
        raise SourceDependencyError(f"required shipped dependency source is absent: {path}") from error


def _declared_images(inventory: dict[str, Any]) -> set[tuple[str, PurePosixPath]]:
    raw_images = inventory.get("container_images")
    if not isinstance(raw_images, list) or not raw_images:
        raise SourceDependencyError("container_images must be a non-empty list")
    declared: set[tuple[str, PurePosixPath]] = set()
    seen_references: set[str] = set()
    for item in raw_images:
        if not isinstance(item, dict) or set(item) != {"reference", "locations"}:
            raise SourceDependencyError("malformed container image inventory entry")
        reference = item.get("reference")
        locations = item.get("locations")
        if (
            not isinstance(reference, str)
            or IMMUTABLE_OCI_REFERENCE.fullmatch(reference) is None
            or reference in seen_references
            or not isinstance(locations, list)
            or not locations
        ):
            raise SourceDependencyError(f"mutable or duplicate container image inventory: {reference!r}")
        seen_references.add(reference)
        parsed_locations = [_safe_relative_path(location) for location in locations]
        if parsed_locations != sorted(set(parsed_locations)):
            raise SourceDependencyError(f"container image locations are duplicate or unsorted: {reference}")
        for location in parsed_locations:
            declared.add((reference, location))
    return declared


def _actual_images(files: dict[PurePosixPath, bytes]) -> set[tuple[str, PurePosixPath]]:
    actual: set[tuple[str, PurePosixPath]] = set()
    for path, content in files.items():
        if (
            path == INVENTORY_PATH
            or not _is_shipped_source_path(path)
            or (
                path.suffix.lower() not in DEPENDENCY_TEXT_SUFFIXES and path.name not in {"Containerfile", "Dockerfile"}
            )
            or path.parts[:1] == ("docs",)
        ):
            continue
        text = content.decode("utf-8", errors="strict")
        for reference in OCI_REFERENCE.findall(text):
            actual.add((reference, path))
    return actual


def _declared_derived_images(
    inventory: dict[str, Any],
    immutable_references: set[str],
) -> tuple[set[tuple[str, PurePosixPath]], list[dict[str, Any]]]:
    raw_images = inventory.get("derived_images")
    if not isinstance(raw_images, list):
        raise SourceDependencyError("derived_images must be a list")
    declared: set[tuple[str, PurePosixPath]] = set()
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    required_keys = {
        "reference",
        "disposition",
        "build_file",
        "base_reference",
        "locations",
    }
    for item in raw_images:
        if not isinstance(item, dict) or set(item) != required_keys:
            raise SourceDependencyError("malformed derived image inventory entry")
        reference = item.get("reference")
        base_reference = item.get("base_reference")
        locations = item.get("locations")
        if (
            not isinstance(reference, str)
            or OCI_REFERENCE.fullmatch(reference) is None
            or IMMUTABLE_OCI_REFERENCE.fullmatch(reference) is not None
            or reference in seen
            or item.get("disposition") != "local-build-output"
            or not isinstance(base_reference, str)
            or base_reference not in immutable_references
            or not isinstance(locations, list)
            or not locations
        ):
            raise SourceDependencyError(f"unsafe derived container image inventory: {reference!r}")
        build_file = _safe_relative_path(item.get("build_file"))
        parsed_locations = [_safe_relative_path(location) for location in locations]
        if parsed_locations != sorted(set(parsed_locations)):
            raise SourceDependencyError(f"derived image locations are duplicate or unsorted: {reference}")
        normalized = dict(item)
        normalized["build_file"] = build_file.as_posix()
        validated.append(normalized)
        seen.add(reference)
        declared.update((reference, location) for location in parsed_locations)
    return declared, validated


def _source_collections(files: dict[PurePosixPath, bytes]) -> set[tuple[str, str, str]]:
    galaxy_path = PurePosixPath("galaxy.yml")
    if galaxy_path in files:
        galaxy = _yaml_mapping(_required_file(files, galaxy_path), galaxy_path)
        raw_galaxy = galaxy.get("dependencies")
    else:
        manifest_path = PurePosixPath("MANIFEST.json")
        try:
            manifest = json.loads(_required_file(files, manifest_path))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise SourceDependencyError(f"cannot parse {manifest_path}: {error}") from error
        collection_info = manifest.get("collection_info") if isinstance(manifest, dict) else None
        raw_galaxy = collection_info.get("dependencies") if isinstance(collection_info, dict) else None
    if not isinstance(raw_galaxy, dict) or not raw_galaxy:
        raise SourceDependencyError("galaxy.yml dependencies must be a non-empty mapping")
    source: set[tuple[str, str, str]] = set()
    for name, requirement in raw_galaxy.items():
        source.add((str(name), str(requirement), galaxy_path.as_posix()))

    requirements_path = PurePosixPath("collections/requirements-rh.yml")
    requirements = _yaml_mapping(_required_file(files, requirements_path), requirements_path)
    raw_collections = requirements.get("collections")
    if not isinstance(raw_collections, list) or not raw_collections:
        raise SourceDependencyError("AAP collection requirements must be a non-empty list")
    for item in raw_collections:
        if not isinstance(item, dict) or set(item) != {"name", "version"}:
            raise SourceDependencyError("AAP collection requirements must contain only name and version")
        source.add((str(item["name"]), str(item["version"]), requirements_path.as_posix()))
    return source


def _declared_collections(inventory: dict[str, Any]) -> set[tuple[str, str, str]]:
    raw_collections = inventory.get("collections")
    if not isinstance(raw_collections, list) or not raw_collections:
        raise SourceDependencyError("collections must be a non-empty list")
    declared: set[tuple[str, str, str]] = set()
    names: set[str] = set()
    for item in raw_collections:
        if not isinstance(item, dict) or set(item) != {"name", "requirement", "source"}:
            raise SourceDependencyError("malformed collection dependency inventory entry")
        name = item.get("name")
        requirement = item.get("requirement")
        source = item.get("source")
        if (
            not isinstance(name, str)
            or COLLECTION_NAME.fullmatch(name) is None
            or name in names
            or not isinstance(requirement, str)
            or SAFE_REQUIREMENT.fullmatch(requirement) is None
            or not isinstance(source, str)
        ):
            raise SourceDependencyError(f"unsafe or duplicate collection dependency: {name!r}")
        names.add(name)
        source_path = _safe_relative_path(source)
        declared.add((name, requirement, source_path.as_posix()))
    return declared


def _external_products(inventory: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    raw_products = inventory.get("external_products")
    if not isinstance(raw_products, list) or not raw_products:
        raise SourceDependencyError("external_products must be a non-empty list")
    products: list[dict[str, Any]] = []
    provided: set[str] = set()
    names: set[str] = set()
    required_keys = {
        "name",
        "version",
        "type",
        "disposition",
        "reason",
        "provides_collections",
        "locations",
    }
    for item in raw_products:
        if not isinstance(item, dict) or set(item) != required_keys:
            raise SourceDependencyError("malformed external product inventory entry")
        name = item.get("name")
        version = item.get("version")
        reason = item.get("reason")
        collections = item.get("provides_collections")
        locations = item.get("locations")
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z][a-z0-9-]{2,63}", name) is None
            or name in names
            or not isinstance(version, str)
            or SAFE_VERSION.fullmatch(version) is None
            or item.get("type") not in {"application", "framework"}
            or item.get("disposition") != "blocked-external-license"
            or not isinstance(reason, str)
            or reason != reason.strip()
            or not 80 <= len(reason) <= 500
            or not isinstance(collections, list)
            or not collections
            or not isinstance(locations, list)
            or not locations
        ):
            raise SourceDependencyError(f"unsafe external product dependency: {name!r}")
        parsed_collections = [str(value) for value in collections]
        if any(
            COLLECTION_NAME.fullmatch(value) is None for value in parsed_collections
        ) or parsed_collections != sorted(set(parsed_collections)):
            raise SourceDependencyError(f"unsafe provided collection list: {name}")
        parsed_locations = [_safe_relative_path(value) for value in locations]
        if parsed_locations != sorted(set(parsed_locations)):
            raise SourceDependencyError(f"external product locations are duplicate or unsorted: {name}")
        names.add(name)
        provided.update(parsed_collections)
        products.append(item)
    return products, provided


def _task_collections(payload: object, path: PurePosixPath) -> set[str]:
    if payload is None:
        return set()
    if not isinstance(payload, list):
        raise SourceDependencyError(f"shipped task file must contain a task list: {path}")
    collections: set[str] = set()
    for task in payload:
        if not isinstance(task, dict):
            raise SourceDependencyError(f"shipped task file contains a non-mapping task: {path}")
        for key, value in task.items():
            if key in {"always", "block", "rescue"}:
                collections.update(_task_collections(value, path))
                continue
            if not isinstance(key, str):
                continue
            action = FQCN_ACTION.fullmatch(key)
            if action is None:
                continue
            collections.add(action.group(1))
            if key.endswith((".import_role", ".include_role")) and isinstance(value, dict):
                role_name = value.get("name")
                match = FQCN_PREFIX.match(role_name) if isinstance(role_name, str) else None
                if match is not None:
                    collections.add(match.group(1))
    return collections


def _used_collections(files: dict[PurePosixPath, bytes]) -> set[str]:
    used: set[str] = set()
    for path, content in files.items():
        if path.parts[:1] != ("roles",) or not _is_shipped_source_path(path):
            continue
        text = content.decode("utf-8", errors="strict") if path.suffix.lower() in DEPENDENCY_TEXT_SUFFIXES else ""
        used.update(PLUGIN_REFERENCE.findall(text))
        if len(path.parts) >= 3 and path.parts[2] in {"handlers", "tasks"} and path.suffix in {".yaml", ".yml"}:
            try:
                payload = yaml.safe_load(content)
            except yaml.YAMLError as error:
                raise SourceDependencyError(f"cannot parse shipped task file {path}: {error}") from error
            used.update(_task_collections(payload, path))
    return used


def validate_source_dependencies(
    *,
    root: Path,
    candidate: Path | None = None,
    inventory_path: PurePosixPath = INVENTORY_PATH,
) -> dict[str, Any]:
    """Validate source and optional collection-candidate dependency coverage."""

    source_files = _source_files(root)
    inventory_bytes = _required_file(source_files, inventory_path)
    if len(inventory_bytes) > 2 * 1024 * 1024:
        raise SourceDependencyError("source dependency inventory exceeds the size limit")
    inventory = _yaml_mapping(inventory_bytes, inventory_path)
    if (
        set(inventory)
        != {
            "schema_version",
            "container_images",
            "derived_images",
            "collections",
            "external_products",
        }
        or inventory.get("schema_version") != 1
    ):
        raise SourceDependencyError("source dependency inventory schema is malformed")

    files = source_files if candidate is None else _candidate_files(candidate)
    if candidate is not None:
        if _required_file(files, inventory_path) != inventory_bytes:
            raise SourceDependencyError("candidate dependency inventory differs from exact source")

    declared_images = _declared_images(inventory)
    immutable_references = {reference for reference, _location in declared_images}
    declared_derived, derived_images = _declared_derived_images(inventory, immutable_references)
    actual_images = _actual_images(files)
    all_declared_images = declared_images | declared_derived
    undeclared_mutable = sorted(
        f"{path}: {reference}"
        for reference, path in actual_images - declared_derived
        if IMMUTABLE_OCI_REFERENCE.fullmatch(reference) is None
    )
    if undeclared_mutable:
        raise SourceDependencyError(f"mutable shipped container images are undeclared: {undeclared_mutable!r}")
    if actual_images != all_declared_images:
        missing = sorted(f"{path}: {reference}" for reference, path in actual_images - all_declared_images)
        stale = sorted(f"{path}: {reference}" for reference, path in all_declared_images - actual_images)
        raise SourceDependencyError(
            f"container dependency inventory differs from shipped source; missing={missing!r}, stale={stale!r}"
        )
    for image in derived_images:
        build_file = PurePosixPath(image["build_file"])
        build_content = _required_file(files, build_file).decode("utf-8", errors="strict")
        if str(image["base_reference"]) not in build_content:
            raise SourceDependencyError(f"derived image base differs from its build file: {image['reference']}")

    source_collections = _source_collections(files)
    declared_collections = _declared_collections(inventory)
    if source_collections != declared_collections:
        raise SourceDependencyError("collection dependency inventory differs from shipped requirements")

    products, provided_collections = _external_products(inventory)
    product_locations = {_safe_relative_path(location) for product in products for location in product["locations"]}
    for location in product_locations:
        _required_file(files, location)
    for product in products:
        product_content = "\n".join(
            _required_file(files, _safe_relative_path(location)).decode("utf-8", errors="strict")
            for location in product["locations"]
        )
        for provided in product["provides_collections"]:
            if f"{provided}." not in product_content:
                raise SourceDependencyError(f"external product provides an unreferenced collection: {provided}")
    aap_default = _required_file(files, PurePosixPath("roles/aap_deploy/defaults/main.yml")).decode()
    if re.search(r'(?m)^aap_deploy_setup_download_version:\s*["\']?2\.7["\']?\s*$', aap_default) is None:
        raise SourceDependencyError("AAP product inventory differs from the shipped role version")

    accounted = {name for name, _requirement, _source in declared_collections}
    accounted.update(provided_collections)
    ignored = {"ansible.builtin", "lit.supplementary"}
    used = _used_collections(files)
    unresolved = sorted(used - accounted - ignored)
    if unresolved:
        raise SourceDependencyError(f"shipped role source has unaccounted collections: {unresolved!r}")

    if candidate is not None:
        bound_paths = {
            inventory_path,
            PurePosixPath("collections/requirements-rh.yml"),
            *(path for _reference, path in declared_images),
            *(path for _reference, path in declared_derived),
            *(PurePosixPath(image["build_file"]) for image in derived_images),
            *product_locations,
        }
        for path in bound_paths:
            if _required_file(files, path) != _required_file(source_files, path):
                raise SourceDependencyError(f"candidate dependency source differs from exact source: {path}")

    return {
        "inventory": inventory,
        "sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "container_count": len(inventory["container_images"]),
        "derived_container_count": len(derived_images),
        "collection_count": len(inventory["collections"]),
        "external_product_count": len(products),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--candidate", type=Path)
    args = parser.parse_args()
    try:
        result = validate_source_dependencies(root=args.root.resolve(), candidate=args.candidate)
    except (OSError, UnicodeDecodeError, SourceDependencyError) as error:
        print(f"Source dependency validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({key: value for key, value in result.items() if key != "inventory"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
