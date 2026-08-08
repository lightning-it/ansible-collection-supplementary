"""Verify the packaged Keycloak 26.7.1 Security-patch contract offline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

IMAGE = (
    "quay.io/keycloak/"
    "keycloak:26.7.1@"
    "sha256:f1f1f01e472c8a78df40d8f2a49a925274eda4d3d80d5f6edbb5c880ee3c01c6"
)
LOCATIONS = [
    "manifests/identity-stack.pod.yaml",
    "roles/keycloak_deploy/defaults/main.yml",
]
MAX_SOURCE_BYTES = 1024 * 1024


def fail(message: str) -> None:
    raise SystemExit(f"Keycloak 26.7.1 security verification failed: {message}")


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def construct_unique_mapping(
    loader: UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            fail(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    construct_unique_mapping,
)


def read_bounded_file(collection_root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(collection_root)
    except ValueError:
        fail(f"path escapes the collection root: {path}")
    if any(component in {"", ".", ".."} for component in relative.parts):
        fail(f"path escapes the collection root: {path}")
    current = collection_root
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            fail(f"expected a non-symlink path: {path}")
    if not path.is_file():
        fail(f"expected a regular non-symlink file: {path}")
    try:
        if path.stat().st_size > MAX_SOURCE_BYTES:
            fail(f"source exceeds the {MAX_SOURCE_BYTES}-byte limit: {path}")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(f"cannot read {path}: {exc}")


def load_yaml(collection_root: Path, relative_path: str) -> Any:
    path = collection_root / relative_path
    try:
        return yaml.load(
            read_bounded_file(collection_root, path),
            Loader=UniqueKeyLoader,
        )
    except yaml.YAMLError as exc:
        fail(f"cannot parse {path}: {exc}")


def verify(collection_root: Path) -> None:
    defaults = load_yaml(collection_root, "roles/keycloak_deploy/defaults/main.yml")
    if not isinstance(defaults, dict) or defaults.get("keycloak_deploy_image") != IMAGE:
        fail("Keycloak role default does not use the approved immutable image")

    manifest = load_yaml(collection_root, "manifests/identity-stack.pod.yaml")
    spec = manifest.get("spec") if isinstance(manifest, dict) else None
    containers = spec.get("containers") if isinstance(spec, dict) else None
    if not isinstance(containers, list):
        fail("identity-stack Pod manifest has no container list")
    keycloak = [
        container
        for container in containers
        if isinstance(container, dict) and container.get("name") == "keycloak"
    ]
    if len(keycloak) != 1 or keycloak[0].get("image") != IMAGE:
        fail("identity-stack Keycloak container does not use the approved immutable image")

    inventory = load_yaml(collection_root, "meta/source-dependencies.yml")
    images = inventory.get("container_images") if isinstance(inventory, dict) else None
    matches = [
        item
        for item in images or []
        if isinstance(item, dict) and item.get("reference") == IMAGE
    ]
    if len(matches) != 1 or matches[0].get("locations") != LOCATIONS:
        fail("source dependency inventory does not bind the approved Keycloak image")


def main() -> None:
    verify(Path(__file__).resolve().parent.parent)
    print("Keycloak 26.7.1 security contract verified")


if __name__ == "__main__":
    main()
