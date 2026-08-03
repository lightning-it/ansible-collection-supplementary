"""Verify the packaged Forgejo manifest secret-permission contract offline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TASK_NAME = "Render Forgejo Pod manifest"
MANIFEST_DESTINATION = "{{ forgejo_deploy_pod_manifest_path }}"
MAX_SOURCE_BYTES = 1024 * 1024
SECRET_BINDING = (
    "        - name: FORGEJO__database__PASSWD\n"
    '          value: "{{ forgejo_deploy_db_password_effective }}"'
)


def fail(message: str) -> None:
    raise SystemExit(f"Forgejo manifest security verification failed: {message}")


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
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")


def load_yaml(collection_root: Path, path: Path) -> Any:
    try:
        return yaml.load(read_bounded_file(collection_root, path), Loader=UniqueKeyLoader)
    except yaml.YAMLError as exc:
        fail(f"cannot parse {path}: {exc}")


def verify(collection_root: Path) -> None:
    task_path = collection_root / "roles" / "forgejo_deploy" / "tasks" / "deploy_pod.yml"
    template_path = (
        collection_root
        / "roles"
        / "forgejo_deploy"
        / "templates"
        / "forgejo-pod.yml.j2"
    )

    tasks = load_yaml(collection_root, task_path)
    if not isinstance(tasks, list):
        fail("Forgejo deployment task file is not a list")
    matches = [
        task
        for task in tasks
        if isinstance(task, dict) and task.get("name") == TASK_NAME
    ]
    if len(matches) != 1:
        fail(f"expected exactly one {TASK_NAME!r} task")

    task = matches[0]
    template = task.get("ansible.builtin.template")
    if not isinstance(template, dict):
        fail("Forgejo manifest task does not use ansible.builtin.template")
    if template.get("src") != "forgejo-pod.yml.j2":
        fail("Forgejo manifest task uses an unexpected template source")
    if template.get("dest") != MANIFEST_DESTINATION:
        fail("Forgejo manifest task uses an unexpected destination")
    expected = {"owner": "root", "group": "root", "mode": "0600"}
    observed = {key: template.get(key) for key in expected}
    if observed != expected:
        fail("Forgejo manifest must be written as root:root with mode 0600")
    if task.get("no_log") is not True:
        fail("Forgejo manifest render task must set no_log to true")

    writers = []
    for candidate in tasks:
        if not isinstance(candidate, dict):
            continue
        for module_name, arguments in candidate.items():
            if (
                isinstance(module_name, str)
                and module_name.startswith("ansible.builtin.")
                and isinstance(arguments, dict)
                and arguments.get("dest") == MANIFEST_DESTINATION
            ):
                writers.append((candidate.get("name"), module_name))
    if writers != [(TASK_NAME, "ansible.builtin.template")]:
        fail("Forgejo manifest destination must have exactly one protected writer")

    template_text = read_bounded_file(collection_root, template_path)
    if template_text.count(SECRET_BINDING) != 1:
        fail("Forgejo manifest no longer has the exact fix-specific password binding")


def main() -> None:
    verify(Path(__file__).resolve().parent.parent)
    print("Forgejo manifest security contract verified")


if __name__ == "__main__":
    main()
