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
SPEC = importlib.util.spec_from_file_location("atomic_path_test", ROOT / "plugins/modules/atomic_path.py")
if SPEC is None or SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("cannot load atomic_path")
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


class Result(Exception):
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value


class Failure(Result):
    pass


class FakeModule:
    params: dict[str, object] = {}
    check = False

    def __init__(self, **_: object) -> None:
        self.params = dict(type(self).params)
        self.check_mode = type(self).check

    def exit_json(self, **value: object) -> None:
        raise Result(value)

    def fail_json(self, **value: object) -> None:
        raise Failure(value)


class AtomicPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=os.path.realpath(tempfile.gettempdir()))
        self.root = Path(self.temporary.name)
        self.mode = f"{self.root.stat().st_mode & 0o777:04o}"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def identities(self, *paths: Path) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for path in paths:
            current = Path(path.anchor)
            for component in path.parts[1:]:
                current /= component
                details = current.stat()
                result[str(current)] = {"device": details.st_dev, "inode": details.st_ino}
        return result

    def execute(
        self,
        parameters: dict[str, object],
        *,
        check: bool = False,
        failure: bool = False,
    ) -> dict[str, object]:
        FakeModule.params = parameters
        FakeModule.check = check
        with (
            mock.patch.object(MODULE, "AnsibleModule", FakeModule),
            self.assertRaises(Failure if failure else Result) as result,
        ):
            MODULE.main()
        return result.exception.value

    def common(self, path: Path, state: str) -> dict[str, object]:
        return {
            "path": str(path),
            "state": state,
            "content": None,
            "mode": "0755" if state == "directory" else "0644",
            "owner": str(os.getuid()),
            "group": str(os.getgid()),
            "parent_identities": self.identities(self.root),
            "expected_checksum": None,
            "allow_absent": True,
        }

    def test_descriptor_relative_directory_creation_and_check_mode(self) -> None:
        target = self.root / "managed"
        parameters = self.common(target, "directory")
        self.assertTrue(self.execute(parameters, check=True)["changed"])
        self.assertFalse(target.exists())
        self.assertTrue(self.execute(parameters)["changed"])
        self.assertTrue(target.is_dir())
        self.assertFalse(self.execute(parameters)["changed"])

    def test_atomic_file_create_update_and_checksum_binding(self) -> None:
        target = self.root / "policy.conf"
        parameters = self.common(target, "file")
        parameters["content"] = "first\n"
        self.execute(parameters)
        first = hashlib.sha256(b"first\n").hexdigest()
        parameters.update(content="second\n", allow_absent=False, expected_checksum=first)
        result = self.execute(parameters)
        self.assertTrue(result["changed"])
        self.assertEqual("second\n", target.read_text(encoding="utf-8"))
        parameters["expected_checksum"] = "0" * 64
        self.assertIn("checksum changed", str(self.execute(parameters, failure=True)["msg"]))

    def test_symlink_parent_and_malformed_identity_fail_closed(self) -> None:
        foreign = self.root / "foreign"
        foreign.mkdir()
        link = self.root / "link"
        link.symlink_to(foreign, target_is_directory=True)
        parameters = self.common(link / "file", "file")
        parameters["content"] = "blocked\n"
        parameters["parent_identities"][str(link)] = self.identities(foreign)[str(foreign)]
        self.assertIn("atomic path mutation failed", str(self.execute(parameters, failure=True)["msg"]))
        self.assertFalse((foreign / "file").exists())
        parameters = self.common(self.root / "file", "file")
        parameters["content"] = "blocked\n"
        parameters["parent_identities"][str(self.root)] = {"device": self.root.stat().st_dev}
        self.assertIn("malformed", str(self.execute(parameters, failure=True)["msg"]))

    def test_replaced_parent_never_redirects_write_to_foreign_directory(self) -> None:
        managed = self.root / "managed"
        managed.mkdir()
        foreign = self.root / "foreign"
        foreign.mkdir()
        target = managed / "policy"
        parameters = self.common(target, "file")
        parameters["content"] = "safe\n"
        parameters["parent_identities"] = self.identities(self.root, managed)
        real_open = MODULE._open_bound_directory
        replaced = False

        def replace_after_open(path: str, identities: dict) -> int:
            nonlocal replaced
            descriptor = real_open(path, identities)
            if not replaced:
                replaced = True
                managed.rename(self.root / "detached")
                foreign.rename(managed)
            return descriptor

        with mock.patch.object(MODULE, "_open_bound_directory", side_effect=replace_after_open):
            result = self.execute(parameters, failure=True)
        self.assertIn("identity changed", str(result["msg"]))
        self.assertFalse((managed / "policy").exists())
        self.assertEqual("safe\n", (self.root / "detached/policy").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
