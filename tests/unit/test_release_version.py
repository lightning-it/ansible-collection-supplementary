"""Tests for reviewed changelog impact and stable release version selection."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release-version.py"
SPEC = importlib.util.spec_from_file_location("release_version", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError(f"unable to import {SCRIPT}")
VERSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERSION)


class ReleaseVersionTests(unittest.TestCase):
    def _fixture(self, category: str, *, version: str = "1.40.0", root: Path | None = None) -> tuple[Path, Path]:
        root = root or Path(self.temporary.name)
        galaxy = root / "galaxy.yml"
        galaxy.write_text(f"---\nnamespace: lit\nname: supplementary\nversion: {version}\n", encoding="utf-8")
        fragments = root / "fragments"
        fragments.mkdir()
        (fragments / "change.yml").write_text(
            f"---\n{category}:\n  - Reviewed compatibility impact.\n",
            encoding="utf-8",
        )
        return galaxy, fragments

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def test_highest_reviewed_impact_selects_exact_next_stable_version(self) -> None:
        cases = (
            ("bugfixes", "patch", "1.40.1"),
            ("minor_changes", "minor", "1.41.0"),
            ("major_changes", "major", "2.0.0"),
        )
        for category, impact, expected in cases:
            with self.subTest(category=category), tempfile.TemporaryDirectory() as directory:
                galaxy, fragments = self._fixture(category, root=Path(directory))
                resolved = VERSION.resolve_version(galaxy, fragments)
                self.assertEqual(impact, resolved["impact"])
                self.assertEqual(expected, resolved["version"])
                self.assertEqual(["change.yml"], resolved["fragments"])
                self.assertRegex(resolved["fragment_sha256"][0]["sha256"], r"^[0-9a-f]{64}$")

    def test_preparation_receipt_binds_fragments_version_and_workflow(self) -> None:
        galaxy, fragments = self._fixture("minor_changes")
        resolution = VERSION.resolve_version(galaxy, fragments)
        repository = "lightning-it/ansible-collection-supplementary"
        repository_id = "123456"
        base_sha = "a" * 40
        receipt = VERSION.build_preparation_receipt(
            resolution,
            repository=repository,
            repository_id=repository_id,
            base_sha=base_sha,
            workflow_run_id="98765",
            workflow_attempt="2",
            workflow_ref=(
                f"{repository}/.github/workflows/release-prepare.yml@refs/heads/main"
            ),
            workflow_event="workflow_dispatch",
            workflow_actor="release-operator",
        )
        VERSION.verify_preparation_receipt(
            receipt,
            expected_repository=repository,
            expected_repository_id=repository_id,
            expected_base_sha=base_sha,
            expected_version="1.41.0",
        )
        fragment = fragments / "change.yml"
        self.assertEqual("change.yml", receipt["fragments"][0]["path"])
        self.assertEqual(
            hashlib.sha256(fragment.read_bytes()).hexdigest(),
            receipt["fragments"][0]["sha256"],
        )

        for label, mutate in (
            ("version", lambda value: value.__setitem__("next_version", "1.41.1")),
            ("digest", lambda value: value["fragments"][0].__setitem__("sha256", "z" * 64)),
            ("workflow", lambda value: value["workflow"].__setitem__("path", ".github/workflows/other.yml")),
        ):
            with self.subTest(label=label):
                tampered = json.loads(json.dumps(receipt))
                mutate(tampered)
                with self.assertRaises(VERSION.VersionError):
                    VERSION.verify_preparation_receipt(
                        tampered,
                        expected_repository=repository,
                        expected_repository_id=repository_id,
                        expected_base_sha=base_sha,
                        expected_version="1.41.0",
                    )

    def test_manual_version_must_equal_reviewed_impact(self) -> None:
        galaxy, fragments = self._fixture("major_changes")
        self.assertEqual("2.0.0", VERSION.resolve_version(galaxy, fragments, "2.0.0")["version"])
        for requested in ("1.41.0", "2.0.1", "2.0.0-rc.1", "v2.0.0", "02.0.0"):
            with self.subTest(requested=requested), self.assertRaises(VERSION.VersionError):
                VERSION.resolve_version(galaxy, fragments, requested)

    def test_unknown_empty_neutral_only_and_duplicate_categories_fail_closed(self) -> None:
        cases = {
            "unknown": "---\nfeatures:\n  - change\n",
            "empty": "---\nminor_changes: []\n",
            "neutral": "---\nknown_issues:\n  - issue\n",
            "duplicate": "---\nminor_changes:\n  - one\nminor_changes:\n  - two\n",
        }
        for label, content in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                galaxy, fragments = self._fixture("bugfixes", root=Path(directory))
                (fragments / "change.yml").write_text(content, encoding="utf-8")
                with self.assertRaises(VERSION.VersionError):
                    VERSION.resolve_version(galaxy, fragments)

    def test_repository_fragments_require_the_next_major_release(self) -> None:
        resolved = VERSION.resolve_version(ROOT / "galaxy.yml", ROOT / "changelogs" / "fragments")
        self.assertEqual("major", resolved["impact"])
        self.assertEqual("2.0.0", resolved["version"])


if __name__ == "__main__":
    unittest.main()
