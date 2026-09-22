"""Regression coverage for the repository-local Devtools dispatch boundary."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "scripts/devtools-local-quality.sh"
COMMANDS = {
    "role-coverage-policy": ["python3", "scripts/validate-role-coverage.py", "check"],
    "shipped-source-dependencies": ["python3", "scripts/source_dependencies.py"],
    "repository-quality": ["python3", "scripts/lit-repository-quality.py"],
    "role-quality-python-tests": ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
    "role-quality-ruff": ["ruff", "check"],
    "role-quality-ruff-format": ["ruff", "format", "--check"],
    "role-quality-mypy": ["mypy"],
    "markdownlint": ["markdownlint-cli2"],
}
BOUNDARY = {
    "WUNDER_DEVTOOLS_WORKSPACE_MODE": "ro",
    "WUNDER_DEVTOOLS_ROOTFS_MODE": "ro",
    "WUNDER_DEVTOOLS_NETWORK": "none",
    "WUNDER_DEVTOOLS_PRIVILEGED": "0",
    "WUNDER_DEVTOOLS_RUN_AS_ROOT": "0",
    "WUNDER_DEVTOOLS_RUN_AS_HOST_UID": "1",
    "WUNDER_DEVTOOLS_DOCKER_SOCKET": "disabled",
    "WUNDER_DEVTOOLS_MOUNT_SOURCE_ROOT": "disabled",
    "WUNDER_DEVTOOLS_FORWARD_VAGRANT_SSH": "disabled",
    "WUNDER_DEVTOOLS_CAP_ADD": "",
    "CONTAINER_HOME": "/tmp/wunder",  # noqa: S108 - expected private container tmpfs, not a host temp file
}


class LocalQualityDevtoolsTests(unittest.TestCase):
    def test_all_local_validators_use_the_managed_container_dispatch(self) -> None:
        text = (ROOT / ".pre-commit-config.yaml").read_text()
        config = yaml.safe_load(text)
        hooks = {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}
        for name, command in COMMANDS.items():
            with self.subTest(hook=name):
                hook = hooks[name]
                self.assertEqual(hook["language"], "system")
                self.assertEqual(shlex.split(hook["entry"]), ["bash", "scripts/devtools-local-quality.sh", *command])
                self.assertNotIn("additional_dependencies", hook)
                self.assertNotIn("language_version", hook)
        shared = text.split("# <<< END shared-assets-lit pre-commit", 1)[0]
        self.assertNotIn("devtools-local-quality.sh", shared)
        for name in ("role-coverage-policy", "shipped-source-dependencies", "repository-quality"):
            self.assertTrue(hooks[name]["always_run"])
            self.assertFalse(hooks[name]["pass_filenames"])
        self.assertFalse(hooks["role-quality-python-tests"]["pass_filenames"])
        self.assertFalse(hooks["role-quality-mypy"]["pass_filenames"])
        self.assertTrue(hooks["role-quality-mypy"]["args"])
        self.assertTrue(hooks["markdownlint"]["require_serial"])

    def probe(self, arguments: list[str], exit_code: int = 0) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory(prefix="local-quality-dispatch-") as directory:
            scripts = Path(directory) / "scripts with spaces"
            scripts.mkdir()
            dispatcher = scripts / DISPATCHER.name
            shutil.copyfile(DISPATCHER, dispatcher)
            wrapper = scripts / "wunder-devtools-ee.sh"
            boundary_output = "".join(f'printf "%s\\0" "${{{name}}}"\n' for name in BOUNDARY)
            wrapper.write_text(
                "#!/usr/bin/env bash\nset -euo pipefail\n"
                + boundary_output
                + 'printf "%s\\0" "$@"\nexit "${PROBE_EXIT:-0}"\n'
            )
            return subprocess.run(  # noqa: S603 - fixed shell and test-owned stub; no validator executes here
                ["/bin/bash", str(dispatcher), *arguments],
                env={
                    **os.environ,
                    **dict.fromkeys(BOUNDARY, "unsafe-host-override"),
                    "CONTAINER_HOME": "/workspace/tests",
                    "PROBE_EXIT": str(exit_code),
                },
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )

    def test_dispatch_is_offline_readonly_and_preserves_literal_arguments(self) -> None:
        arguments = ["python3", "two words.py", "$(never-execute)", "semi;colon", "*.py"]
        result = self.probe(arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        fields = result.stdout.split("\0")[:-1]
        self.assertEqual(fields[: len(BOUNDARY)], list(BOUNDARY.values()))
        command = fields[len(BOUNDARY) :]
        self.assertEqual(command[:2], ["bash", "-lc"])
        self.assertEqual(command[3:], ["--", *arguments])
        self.assertIn('export RUNNER_TEMP="${HOME}/runner-temp"', command[2])
        self.assertIn('export RUFF_CACHE_DIR="${HOME}/ruff-cache"', command[2])
        self.assertIn('export MYPY_CACHE_DIR="${HOME}/mypy-cache"', command[2])
        self.assertIn('exec "$@"', command[2])

    def test_failures_propagate_without_host_fallback(self) -> None:
        for exit_code in (1, 17, 127):
            with self.subTest(exit_code=exit_code):
                self.assertEqual(self.probe(["missing-validator"], exit_code).returncode, exit_code)

    def test_missing_command_fails_before_container_dispatch(self) -> None:
        result = self.probe([])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("Usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
