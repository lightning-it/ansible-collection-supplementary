"""Execute the actual pre-mutation promoter guard against temporary Git histories."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/promote-develop-to-main.yml"
GENERATED = (
    "CHANGELOG.rst",
    "changelogs/.plugin-cache.yaml",
    "changelogs/changelog.yaml",
    "changelogs/release-preparation.json",
)
RECEIPT = {
    "schema_version": 2,
    "next_version": "4.0.0",
    "fragments": [{"path": "consumed.yml", "sha256": "1" * 64}],
}


class PromotionReleaseStateGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.script = workflow["jobs"]["promote"]["steps"][-1]["run"]
        self.guard = self.script.split("# LI-139 release-state guard:start\n", 1)[1].split(
            "# LI-139 release-state guard:end", 1
        )[0]

    def run_case(
        self,
        changes: dict[str, str | None],
        base_overrides: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            environment = {
                "PATH": os.environ["PATH"],
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            }

            def git(*arguments: str) -> str:
                return subprocess.run(  # noqa: S603 -- fixed fixture operations in a private temporary repository.
                    ["/usr/bin/git", *arguments],
                    cwd=repository,
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                ).stdout.strip()

            def materialize(files: dict[str, str | None]) -> None:
                for name, content in files.items():
                    path = repository / name
                    if content is None:
                        path.unlink()
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(content, encoding="utf-8")

            git("init", "--quiet")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.com")
            baseline: dict[str, str | None] = {name: "generated state\n" for name in GENERATED}
            baseline["galaxy.yml"] = "---\nnamespace: lit\nname: supplementary\nversion: 4.0.0\n"
            baseline["changelogs/release-preparation.json"] = json.dumps(RECEIPT)
            baseline.update(base_overrides or {})
            materialize(baseline)
            git("add", ".")
            git("commit", "--quiet", "-m", "base")
            environment["expected_base"] = git("rev-parse", "HEAD")
            materialize(changes)
            git("add", "--all")
            git("commit", "--quiet", "--allow-empty", "-m", "head")
            environment["expected_head"] = git("rev-parse", "HEAD")
            return subprocess.run(  # noqa: S603 -- execute the repository-owned guard under test, without credentials.
                ["/bin/bash", "-euo", "pipefail", "-c", self.guard],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )

    def test_preserved_release_state_and_new_work_are_allowed(self) -> None:
        for changes in (
            {},
            {"changelogs/fragments/new-fix.yml": "bugfixes: [new fix]\n"},
            {"galaxy.yml": "version: 4.0.0\ndependencies: {example.other: 1.2.3}\n"},
        ):
            with self.subTest(changes=changes):
                result = self.run_case(changes)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_promotion_cannot_change_or_malform_the_release_version(self) -> None:
        for version in ("3.6.1", "4.0.1", "04.0.0", "4.0.0\nversion: 4.0.0", "", "4.0.0 # extra"):
            with self.subTest(version=version):
                self.assertNotEqual(self.run_case({"galaxy.yml": f"version: {version}\n"}).returncode, 0)

    def test_every_generated_file_must_be_preserved(self) -> None:
        for name in GENERATED:
            for content in (None, "changed\n"):
                with self.subTest(path=name, content=content):
                    self.assertNotEqual(self.run_case({name: content}).returncode, 0)

    def test_consumed_fragments_cannot_be_restored(self) -> None:
        self.assertNotEqual(
            self.run_case({"changelogs/fragments/consumed.yml": "major_changes: [old change]\n"}).returncode,
            0,
        )

    def test_inconsistent_or_unsafe_receipts_fail_closed(self) -> None:
        for receipt in (
            {**RECEIPT, "next_version": "3.6.1"},
            {**RECEIPT, "fragments": []},
            {**RECEIPT, "fragments": [{"path": "../escape.yml", "sha256": "1" * 64}]},
            {**RECEIPT, "fragments": RECEIPT["fragments"] * 2},
            {**RECEIPT, "fragments": [{"path": "consumed.yml", "sha256": "invalid"}]},
        ):
            with self.subTest(receipt=receipt):
                self.assertNotEqual(
                    self.run_case({}, {"changelogs/release-preparation.json": json.dumps(receipt)}).returncode,
                    0,
                )

    def test_guard_precedes_every_promotion_creation(self) -> None:
        self.assertLess(
            self.script.index("# LI-139 release-state guard:end"),
            self.script.index("create_promotion_pr()"),
        )


if __name__ == "__main__":
    unittest.main()
