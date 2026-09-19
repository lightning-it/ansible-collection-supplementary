"""Regression tests for the recovered LI-139 v3.4.0 release metadata."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_V340_FRAGMENTS = {
    "li-139-atomic-path.yml",
    "li-139-forward-proxy-boolean-prechecks.yml",
    "li-139-forward-proxy.yml",
    "li-139-guacamole-session-timeout.yml",
    "li-139-push-ready-canonical-state-path.yml",
    "li-139-push-ready-runner-temp.yml",
    "li139-final-main-review-convergence.yml",
    "li139-final-promotion-review.yml",
    "li139-forward-proxy-runtime-convergence.yml",
    "li139-promotion-evidence-terminal.yml",
    "li139-promotion-final-findings.yml",
    "li139-promotion-review-gaps.yml",
    "li139-promotion-runtime-terminal.yml",
    "li139-terminal-runtime-boundaries.yml",
    "shared-assets-sync-34738379162.yml",
    "shared-assets-sync-34765679169.yml",
    "shared-assets-sync-34778441533.yml",
}


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"{path} is not a YAML mapping")
    return payload


def module_documentation(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "DOCUMENTATION" for target in node.targets):
            payload = yaml.safe_load(ast.literal_eval(node.value))
            if not isinstance(payload, dict):
                raise AssertionError(f"{path} DOCUMENTATION is not a YAML mapping")
            return payload
    raise AssertionError(f"{path} has no DOCUMENTATION assignment")


class Li139ReleaseMetadataTests(unittest.TestCase):
    def test_v340_contains_only_post_v330_fragments(self) -> None:
        changelog = load_yaml(ROOT / "changelogs" / "changelog.yaml")
        releases = changelog["releases"]
        self.assertIsInstance(releases, dict)
        v330 = set(releases["3.3.0"]["fragments"])
        v340 = set(releases["3.4.0"]["fragments"])
        self.assertEqual(EXPECTED_V340_FRAGMENTS, v340)
        self.assertTrue(v330.isdisjoint(v340))

    def test_atomic_modules_and_plugin_cache_start_at_v340(self) -> None:
        cache = load_yaml(ROOT / "changelogs" / ".plugin-cache.yaml")
        modules = cache["plugins"]["module"]
        for module in ("atomic_path", "atomic_unlink"):
            with self.subTest(module=module):
                documentation = module_documentation(ROOT / "plugins" / "modules" / f"{module}.py")
                self.assertEqual("3.4.0", documentation["version_added"])
                self.assertEqual("3.4.0", modules[module]["version_added"])


if __name__ == "__main__":
    unittest.main()
