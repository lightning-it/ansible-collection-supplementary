"""Executable security-boundary tests for the atomic_unlink module."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = REPOSITORY_ROOT / "plugins" / "modules" / "atomic_unlink.py"
MODULE_SPEC = importlib.util.spec_from_file_location("atomic_unlink_under_test", MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("cannot load atomic_unlink module")
ATOMIC_UNLINK = importlib.util.module_from_spec(MODULE_SPEC)
ANSIBLE_PACKAGE = types.ModuleType("ansible")
ANSIBLE_MODULE_UTILS = types.ModuleType("ansible.module_utils")
ANSIBLE_BASIC = types.ModuleType("ansible.module_utils.basic")
ANSIBLE_BASIC.AnsibleModule = object
with mock.patch.dict(
    sys.modules,
    {
        "ansible": ANSIBLE_PACKAGE,
        "ansible.module_utils": ANSIBLE_MODULE_UTILS,
        "ansible.module_utils.basic": ANSIBLE_BASIC,
    },
):
    MODULE_SPEC.loader.exec_module(ATOMIC_UNLINK)


class ModuleExit(Exception):
    """Capture Ansible module success."""

    def __init__(self, result: dict[str, object]) -> None:
        self.result = result


class ModuleFailure(Exception):
    """Capture Ansible module failure."""

    def __init__(self, result: dict[str, object]) -> None:
        self.result = result


class FakeAnsibleModule:
    """Minimal AnsibleModule double that still executes the real module main."""

    params: dict[str, object] = {}
    requested_check_mode = False

    def __init__(self, **_: object) -> None:
        self.params = dict(type(self).params)
        self.check_mode = type(self).requested_check_mode

    def exit_json(self, **result: object) -> None:
        raise ModuleExit(result)

    def fail_json(self, **result: object) -> None:
        raise ModuleFailure(result)


class AtomicUnlinkModuleTests(unittest.TestCase):
    """Execute canonical-path, identity, check-mode, and unlink boundaries."""

    def setUp(self) -> None:
        # macOS exposes /var through a symlink; use its canonical backing tree so
        # the no-follow parent walk exercises directories rather than that alias.
        self.temporary_directory = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.root = Path(self.temporary_directory.name)
        self.target = self.root / "owned.conf"
        self.target.write_text("owned\n", encoding="utf-8")
        self.parameters: dict[str, object] = {
            "path": str(self.target),
            "checksum": hashlib.sha256(self.target.read_bytes()).hexdigest(),
            "mode": f"{self.target.stat().st_mode & 0o777:04o}",
            "owner": str(self.target.stat().st_uid),
            "group": str(self.target.stat().st_gid),
            "allow_absent": False,
        }

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def execute(self, *, check_mode: bool = False) -> dict[str, object]:
        FakeAnsibleModule.params = self.parameters
        FakeAnsibleModule.requested_check_mode = check_mode
        with mock.patch.object(ATOMIC_UNLINK, "AnsibleModule", FakeAnsibleModule):
            with self.assertRaises(ModuleExit) as result:
                ATOMIC_UNLINK.main()
        return result.exception.result

    def execute_failure(self) -> dict[str, object]:
        FakeAnsibleModule.params = self.parameters
        FakeAnsibleModule.requested_check_mode = False
        with mock.patch.object(ATOMIC_UNLINK, "AnsibleModule", FakeAnsibleModule):
            with self.assertRaises(ModuleFailure) as result:
                ATOMIC_UNLINK.main()
        return result.exception.result

    def test_rejects_noncanonical_path(self) -> None:
        self.parameters["path"] = str(self.root / ".." / self.root.name / self.target.name)
        result = self.execute_failure()
        self.assertIn("canonical absolute", str(result["msg"]))
        self.assertTrue(self.target.exists())

    def test_rejects_symlink_target(self) -> None:
        link = self.root / "link.conf"
        link.symlink_to(self.target.name)
        self.parameters["path"] = str(link)
        result = self.execute_failure()
        self.assertIn("not a regular file", str(result["msg"]))
        self.assertTrue(self.target.exists())

    def test_rejects_symlink_in_parent_chain(self) -> None:
        link_parent = self.root / "linked-parent"
        link_parent.symlink_to(self.root, target_is_directory=True)
        self.parameters["path"] = str(link_parent / self.target.name)
        result = self.execute_failure()
        self.assertIn("cannot bind trusted parent chain", str(result["msg"]))
        self.assertTrue(self.target.exists())

    def test_rejects_checksum_identity_mismatch(self) -> None:
        self.parameters["checksum"] = "0" * 64
        result = self.execute_failure()
        self.assertIn("checksum changed", str(result["msg"]))
        self.assertTrue(self.target.exists())

    def test_check_mode_reports_change_without_unlinking(self) -> None:
        result = self.execute(check_mode=True)
        self.assertEqual({"changed": True, "path": str(self.target)}, result)
        self.assertTrue(self.target.exists())

    def test_unlinks_the_exact_bound_file(self) -> None:
        result = self.execute()
        self.assertEqual({"changed": True, "path": str(self.target)}, result)
        self.assertFalse(self.target.exists())

    def test_external_replacement_is_restored_instead_of_deleted(self) -> None:
        replacement = self.root / "replacement.conf"
        replacement.write_text("foreign\n", encoding="utf-8")
        real_rename = os.rename

        def replace_before_quarantine(*args: object, **kwargs: object) -> None:
            os.replace(replacement, self.target)
            real_rename(*args, **kwargs)

        with mock.patch.object(ATOMIC_UNLINK.os, "rename", replace_before_quarantine):
            result = self.execute_failure()

        self.assertIn("atomic quarantine boundary", str(result["msg"]))
        self.assertEqual("foreign\n", self.target.read_text(encoding="utf-8"))
        self.assertEqual([], list(self.root.glob(".atomic-unlink-*")))


if __name__ == "__main__":
    unittest.main()
