"""Security-boundary tests for atomic_unlink."""

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

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location("atomic_unlink_test", ROOT / "plugins/modules/atomic_unlink.py")
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("cannot load atomic_unlink")
MODULE = importlib.util.module_from_spec(SPEC)
BASIC = types.ModuleType("ansible.module_utils.basic")
BASIC.AnsibleModule = object
with mock.patch.dict(
    sys.modules,
    {
        "ansible": types.ModuleType("ansible"),
        "ansible.module_utils": types.ModuleType("ansible.module_utils"),
        "ansible.module_utils.basic": BASIC,
    },
):
    SPEC.loader.exec_module(MODULE)


class Exit(Exception):
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result


class Failure(Exit):
    pass


class FakeModule:
    params: dict[str, object] = {}
    requested_check_mode = False

    def __init__(self, **_: object) -> None:
        self.params = dict(type(self).params)
        self.check_mode = type(self).requested_check_mode

    def exit_json(self, **result: object) -> None:
        raise Exit(result)

    def fail_json(self, **result: object) -> None:
        raise Failure(result)


class AtomicUnlinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=os.path.realpath(tempfile.gettempdir()))
        self.root = Path(self.temporary.name)
        self.target = self.root / "owned.conf"
        self.target.write_text("owned\n", encoding="utf-8")
        details = self.target.stat()
        self.parameters: dict[str, object] = {
            "path": str(self.target),
            "checksum": hashlib.sha256(self.target.read_bytes()).hexdigest(),
            "mode": f"{details.st_mode & 0o777:04o}",
            "owner": str(details.st_uid),
            "group": str(details.st_gid),
            "allow_absent": False,
            "parent_identities": {str(self.root): {"device": details.st_dev, "inode": self.root.stat().st_ino}},
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def preserve(self, _file_fd: int, quarantine_fd: int, expected: os.stat_result) -> None:
        os.link(self.target, "verified", dst_dir_fd=quarantine_fd, follow_symlinks=False)
        self.assertTrue(MODULE._same_identity(expected, os.stat("verified", dir_fd=quarantine_fd)))

    def execute(
        self,
        *,
        check_mode: bool = False,
        failure: bool = False,
        preserve_real: bool = False,
    ) -> dict[str, object]:
        FakeModule.params = self.parameters
        FakeModule.requested_check_mode = check_mode
        expected = Failure if failure else Exit
        preservation = (
            mock.patch.object(MODULE, "_preserve_open_file", side_effect=self.preserve)
            if not preserve_real
            else mock.patch.object(MODULE, "_preserve_open_file", wraps=MODULE._preserve_open_file)
        )
        with mock.patch.object(MODULE, "AnsibleModule", FakeModule), preservation:
            with self.assertRaises(expected) as result:
                MODULE.main()
        return result.exception.result

    def test_check_mode_keeps_the_bound_file(self) -> None:
        self.assertTrue(self.execute(check_mode=True)["changed"])
        self.assertTrue(self.target.exists())

    def test_unlinks_the_exact_bound_file(self) -> None:
        self.assertTrue(self.execute()["changed"])
        self.assertFalse(self.target.exists())

    def test_rejects_checksum_and_metadata_changes(self) -> None:
        self.parameters["checksum"] = "0" * 64
        self.assertIn("checksum changed", str(self.execute(failure=True)["msg"]))
        self.assertTrue(self.target.exists())

    def test_rejects_symlink_and_changed_parent_identity(self) -> None:
        link = self.root / "linked.conf"
        link.symlink_to(self.target.name)
        self.parameters["path"] = str(link)
        self.assertIn("not a regular file", str(self.execute(failure=True)["msg"]))
        self.parameters["path"] = str(self.target)
        identities = self.parameters["parent_identities"]
        self.assertIsInstance(identities, dict)
        identities[str(self.root)]["inode"] = self.root.stat().st_ino + 1
        self.assertIn("trusted parent identity changed", str(self.execute(failure=True)["msg"]))

    def test_rejects_malformed_parent_identity(self) -> None:
        self.parameters["parent_identities"] = {str(self.root): {"device": self.root.stat().st_dev}}
        self.assertIn("cannot bind trusted parent chain", str(self.execute(failure=True)["msg"]))

    def test_rejects_boolean_float_and_negative_identity_inputs(self) -> None:
        for field, value in (("inode", True), ("device", 1.9)):
            with self.subTest(field=field):
                details = self.root.stat()
                self.parameters["parent_identities"] = {
                    str(self.root): {"device": details.st_dev, "inode": details.st_ino}
                }
                self.parameters["parent_identities"][str(self.root)][field] = value
                self.assertIn("cannot bind trusted parent chain", str(self.execute(failure=True)["msg"]))
        details = self.root.stat()
        self.parameters["parent_identities"] = {str(self.root): {"device": details.st_dev, "inode": details.st_ino}}
        for field in ("owner", "group"):
            with self.subTest(field=field):
                self.parameters["owner"] = str(details.st_uid)
                self.parameters["group"] = str(details.st_gid)
                self.parameters[field] = "-1"
                self.assertIn("cannot bind trusted parent chain", str(self.execute(failure=True)["msg"]))

    @unittest.skipUnless(Path("/proc/self/fd").is_dir(), "descriptor linking requires procfs")
    def test_real_descriptor_preservation_helper(self) -> None:
        self.assertTrue(self.execute(preserve_real=True)["changed"])
        self.assertFalse(self.target.exists())

    def test_rename_failure_preserves_verified_inode_for_recovery(self) -> None:
        with mock.patch.object(MODULE.os, "rename", side_effect=OSError("rename denied")):
            result = self.execute(failure=True)

        recovery = Path(str(result["recovery_path"]))
        self.assertIn("verified inode preserved", str(result["msg"]))
        self.assertEqual("owned\n", self.target.read_text(encoding="utf-8"))
        self.assertEqual("owned\n", recovery.read_text(encoding="utf-8"))

    def test_race_restores_foreign_path_and_preserves_verified_inode(self) -> None:
        replacement = self.root / "replacement.conf"
        replacement.write_text("foreign\n", encoding="utf-8")
        real_rename = os.rename

        def replace_then_rename(*args: object, **kwargs: object) -> None:
            os.replace(replacement, self.target)
            real_rename(*args, **kwargs)

        with mock.patch.object(MODULE.os, "rename", replace_then_rename):
            result = self.execute(failure=True)

        recovery = Path(str(result["recovery_path"]))
        self.assertIn("atomic quarantine boundary", str(result["msg"]))
        self.assertEqual("foreign\n", self.target.read_text(encoding="utf-8"))
        self.assertEqual("owned\n", recovery.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
