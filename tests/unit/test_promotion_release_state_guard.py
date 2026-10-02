"""Execute the actual pre-mutation promoter guard against temporary Git histories."""

from __future__ import annotations

import hashlib
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
    "release_mode": "normal",
    "security": None,
    "chain_id": None,
    "next_version": "4.0.0",
    "fragments": [{"path": "consumed.yml", "sha256": "1" * 64}],
}
SECURITY_FILES = {
    ".lit/security-releases/4.0.0.json": '{"evidenceId":"fixture"}\n',
    ".lit/security-release-intakes/4.0.0.json": '{"request":{"evidenceId":"fixture"}}\n',
}
SECURITY_RECEIPT = {
    **RECEIPT,
    "release_mode": "security",
    "chain_id": "sha256:" + "2" * 64,
    "security": {
        "metadata_path": ".lit/security-releases/4.0.0.json",
        "metadata_sha256": "sha256:"
        + hashlib.sha256(SECURITY_FILES[".lit/security-releases/4.0.0.json"].encode()).hexdigest(),
        "intake_receipt_path": ".lit/security-release-intakes/4.0.0.json",
        "intake_receipt_sha256": "sha256:"
        + hashlib.sha256(SECURITY_FILES[".lit/security-release-intakes/4.0.0.json"].encode()).hexdigest(),
    },
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
                check=False,
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

    def test_preserved_security_release_state_is_allowed(self) -> None:
        base = {**SECURITY_FILES, "changelogs/release-preparation.json": json.dumps(SECURITY_RECEIPT)}
        result = self.run_case({}, base)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_security_files_cannot_be_changed_or_deleted(self) -> None:
        base = {**SECURITY_FILES, "changelogs/release-preparation.json": json.dumps(SECURITY_RECEIPT)}
        for path in SECURITY_FILES:
            for content in (None, "changed\n"):
                with self.subTest(path=path, content=content):
                    self.assertNotEqual(self.run_case({path: content}, base).returncode, 0)

    def test_security_paths_and_digests_are_strictly_version_bound(self) -> None:
        for field, value in (
            ("metadata_path", ".lit/security-releases/3.6.1.json"),
            ("intake_receipt_path", "../outside.json"),
            ("metadata_sha256", "sha256:" + "0" * 64),
            ("intake_receipt_sha256", "sha256:" + "0" * 64),
            ("metadata_sha256", "invalid"),
            ("intake_receipt_sha256", None),
        ):
            with self.subTest(field=field, value=value):
                receipt = json.loads(json.dumps(SECURITY_RECEIPT))
                receipt["security"][field] = value
                base = {**SECURITY_FILES, "changelogs/release-preparation.json": json.dumps(receipt)}
                self.assertNotEqual(self.run_case({}, base).returncode, 0)

    def test_release_mode_must_be_explicit_and_consistent(self) -> None:
        for receipt in (
            {key: value for key, value in RECEIPT.items() if key != "release_mode"},
            {**RECEIPT, "release_mode": "unknown"},
            {**RECEIPT, "release_mode": "security"},
            {**RECEIPT, "security": {}},
            {**RECEIPT, "chain_id": "sha256:" + "0" * 64},
            {**SECURITY_RECEIPT, "chain_id": None},
        ):
            with self.subTest(receipt=receipt):
                self.assertNotEqual(
                    self.run_case({}, {"changelogs/release-preparation.json": json.dumps(receipt)}).returncode, 0
                )

    def test_normal_release_cannot_acquire_current_version_security_markers(self) -> None:
        for path, content in SECURITY_FILES.items():
            with self.subTest(path=path):
                self.assertNotEqual(self.run_case({path: content}).returncode, 0)
                self.assertNotEqual(self.run_case({}, {path: content}).returncode, 0)


if __name__ == "__main__":
    unittest.main()
