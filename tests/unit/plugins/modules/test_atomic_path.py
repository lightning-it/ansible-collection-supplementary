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
        if not failure:
            self.assertNotIsInstance(result.exception, Failure)
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

    def test_only_the_exact_parent_identity_is_mandatory(self) -> None:
        target = self.root / "policy"
        parameters = self.common(target, "file")
        details = self.root.stat()
        parameters["parent_identities"] = {str(self.root): {"device": details.st_dev, "inode": details.st_ino}}
        parameters["content"] = "safe\n"
        self.assertTrue(self.execute(parameters)["changed"])
        parameters["parent_identities"] = {}
        self.assertIn("exact parent identity is missing", str(self.execute(parameters, failure=True)["msg"]))

    def test_root_parent_identity_is_validated(self) -> None:
        parameters = self.common(Path("/policy"), "directory")
        root = Path("/").stat()
        parameters["parent_identities"] = {"/": {"device": root.st_dev, "inode": root.st_ino + 1}}
        self.assertIn("parent identity changed", str(self.execute(parameters, check=True, failure=True)["msg"]))

    def test_atomic_file_create_update_and_checksum_binding(self) -> None:
        target = self.root / "policy.conf"
        parameters = self.common(target, "file")
        parameters["content"] = "first\n"
        parameters["expected_checksum"] = "abc"
        self.assertIn("lowercase SHA-256", str(self.execute(parameters, failure=True)["msg"]))
        self.assertFalse(target.exists())
        parameters["expected_checksum"] = None
        self.execute(parameters)
        first = hashlib.sha256(b"first\n").hexdigest()
        parameters.update(content="second\n", allow_absent=False, expected_checksum=first)
        result = self.execute(parameters)
        self.assertTrue(result["changed"])
        self.assertEqual("second\n", target.read_text(encoding="utf-8"))
        parameters["expected_checksum"] = "0" * 64
        self.assertIn("checksum changed", str(self.execute(parameters, failure=True)["msg"]))
        parameters["expected_checksum"] = "abc"
        self.assertIn("lowercase SHA-256", str(self.execute(parameters, check=True, failure=True)["msg"]))

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

    def test_boolean_and_float_parent_identities_fail_closed(self) -> None:
        for malformed in (True, 1.9, None):
            with self.subTest(malformed=malformed):
                target = self.root / f"blocked-{malformed}"
                parameters = self.common(target, "file")
                parameters["content"] = "blocked\n"
                parameters["parent_identities"][str(self.root)]["inode"] = malformed
                self.assertIn("malformed", str(self.execute(parameters, failure=True)["msg"]))
                self.assertFalse(target.exists())

    def test_invalid_mode_and_negative_identity_never_mutate(self) -> None:
        for field, value in (
            ("mode", "10000"),
            ("owner", "-1"),
            ("group", "-1"),
            ("owner", str(2**32)),
        ):
            with self.subTest(field=field):
                target = self.root / f"blocked-{field}"
                parameters = self.common(target, "directory")
                parameters[field] = value
                self.assertIn("atomic path mutation failed", str(self.execute(parameters, failure=True)["msg"]))
                self.assertFalse(target.exists())

    def test_group_or_world_writable_parent_is_rejected(self) -> None:
        target = self.root / "blocked"
        parameters = self.common(target, "directory")
        self.root.chmod(0o777)
        try:
            self.assertIn("not group/world writable", str(self.execute(parameters, check=True, failure=True)["msg"]))
            self.assertFalse(target.exists())
        finally:
            self.root.chmod(0o700)

    def test_directory_metadata_failure_cleans_private_creation(self) -> None:
        target = self.root / "managed"
        parameters = self.common(target, "directory")
        with mock.patch.object(MODULE.os, "fchown", side_effect=OSError("denied")):
            self.assertIn("denied", str(self.execute(parameters, failure=True)["msg"]))
        self.assertFalse(target.exists())
        self.assertEqual([], list(self.root.glob(".atomic-path-*")))

    def test_file_metadata_failure_cleans_private_creation(self) -> None:
        target = self.root / "policy"
        parameters = self.common(target, "file")
        parameters["content"] = "blocked\n"
        with mock.patch.object(MODULE.os, "fchown", side_effect=OSError("denied")):
            self.assertIn("denied", str(self.execute(parameters, failure=True)["msg"]))
        self.assertFalse(target.exists())
        self.assertEqual([], list(self.root.glob(".atomic-path-*")))

    def test_file_metadata_failure_preserves_uncleanable_private_creation(self) -> None:
        target = self.root / "policy"
        parameters = self.common(target, "file")
        parameters["content"] = "blocked\n"
        with (
            mock.patch.object(MODULE.os, "fchown", side_effect=OSError("denied")),
            mock.patch.object(MODULE, "_remove_private_if_same", return_value=False),
        ):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertIn("recovery workspace preserved", str(result["msg"]))
        self.assertEqual("", recovery.read_text(encoding="utf-8"))
        self.assertFalse(target.exists())

    def test_directory_metadata_failure_preserves_uncleanable_private_creation(self) -> None:
        target = self.root / "managed"
        parameters = self.common(target, "directory")
        with (
            mock.patch.object(MODULE.os, "fchown", side_effect=OSError("denied")),
            mock.patch.object(MODULE, "_remove_private_if_same", return_value=False),
        ):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertIn("recovery workspace preserved", str(result["msg"]))
        self.assertTrue(recovery.is_dir())
        self.assertFalse(target.exists())

    def test_successful_file_write_reports_workspace_cleanup_failure(self) -> None:
        target = self.root / "policy"
        parameters = self.common(target, "file")
        parameters["content"] = "managed\n"
        with mock.patch.object(MODULE, "_remove_private_if_same", return_value=False):
            result = self.execute(parameters, failure=True)
        self.assertIn("workspace cleanup failed", str(result["msg"]))
        self.assertTrue(Path(str(result["recovery_path"])).is_dir())
        self.assertEqual("managed\n", target.read_text(encoding="utf-8"))

    def test_capture_never_restores_changed_content_to_public_path(self) -> None:
        target = self.root / "policy"
        target.write_text("managed\n", encoding="utf-8")
        expected = target.stat()
        expected_checksum = hashlib.sha256(b"managed\n").hexdigest()
        target.write_text("foreign\n", encoding="utf-8")
        os.utime(target, ns=(expected.st_atime_ns, expected.st_mtime_ns))
        workspace_path = self.root / "workspace"
        workspace_path.mkdir()
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        workspace = os.open(workspace_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with self.assertRaises(MODULE._PreservedRecovery):
                MODULE._capture_and_remove(
                    parent,
                    target.name,
                    expected,
                    workspace,
                    "failed",
                    checksum=expected_checksum,
                )
        finally:
            os.close(workspace)
            os.close(parent)
        self.assertFalse(target.exists())
        self.assertEqual("foreign\n", (workspace_path / "failed").read_text(encoding="utf-8"))

    def test_workspace_probe_failure_preserves_uncertain_creation(self) -> None:
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        real_stat = os.stat
        failed = False

        def fail_first_probe(path: object, *args: object, **kwargs: object) -> os.stat_result:
            nonlocal failed
            if not failed and str(path).startswith(".atomic-path-"):
                failed = True
                raise OSError("probe denied")
            return real_stat(path, *args, **kwargs)

        try:
            with mock.patch.object(MODULE.os, "stat", side_effect=fail_first_probe):
                with self.assertRaisesRegex(OSError, "preserved as"):
                    MODULE._private_workspace(parent)
        finally:
            os.close(parent)
        self.assertEqual(1, len(list(self.root.glob(".atomic-path-*"))))

    def test_workspace_open_failure_reports_uncertain_cleanup_path(self) -> None:
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        real_open = os.open

        def fail_workspace_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            if str(path).startswith(".atomic-path-"):
                raise OSError("open denied")
            return real_open(path, flags, *args, **kwargs)

        try:
            with (
                mock.patch.object(MODULE.os, "open", side_effect=fail_workspace_open),
                mock.patch.object(MODULE, "_remove_private_if_same", return_value=False),
            ):
                with self.assertRaises(MODULE._PreservedWorkspace) as result:
                    MODULE._private_workspace(parent)
        finally:
            os.close(parent)
        self.assertTrue(Path(result.exception.path).is_dir())

    def test_raced_fifo_open_is_nonblocking(self) -> None:
        target = self.root / "policy"
        target.write_text("owned\n", encoding="utf-8")
        parameters = self.common(target, "file")
        parameters.update(
            content="new\n",
            allow_absent=False,
            expected_checksum=hashlib.sha256(b"owned\n").hexdigest(),
        )
        real_open = os.open
        observed = 0

        def reject_raced_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal observed
            if path == target.name:
                observed = flags
                raise OSError("raced FIFO")
            return real_open(path, flags, *args, **kwargs)

        with (
            mock.patch.object(MODULE, "_require_capabilities"),
            mock.patch.object(MODULE.os, "open", side_effect=reject_raced_open),
        ):
            self.assertIn("raced FIFO", str(self.execute(parameters, failure=True)["msg"]))
        self.assertTrue(observed & os.O_NONBLOCK)

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
        self.assertFalse((self.root / "detached/policy").exists())

    def test_concurrent_target_replacement_is_preserved_without_data_loss(self) -> None:
        target = self.root / "policy"
        target.write_text("owned\n", encoding="utf-8")
        parameters = self.common(target, "file")
        parameters.update(
            content="new\n",
            allow_absent=False,
            expected_checksum=hashlib.sha256(b"owned\n").hexdigest(),
        )
        replacement = self.root / "replacement"
        replacement.write_text("other\n", encoding="utf-8")
        before = target.stat()
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        real_rename = MODULE._renameat
        replaced = False

        def replace_before_commit(
            source_fd: int,
            source: str,
            target_fd: int,
            target_name: str,
            operation: str,
        ) -> None:
            nonlocal replaced
            if operation == "exchange" and not replaced:
                replaced = True
                os.replace(replacement, target)
            real_rename(source_fd, source, target_fd, target_name, operation)

        with mock.patch.object(MODULE, "_renameat", side_effect=replace_before_commit):
            result = self.execute(parameters, failure=True)
        self.assertIn("both entries were preserved", str(result["msg"]))
        self.assertEqual("new\n", target.read_text(encoding="utf-8"))
        workspaces = list(self.root.glob(".atomic-path-*"))
        self.assertEqual(1, len(workspaces))
        self.assertEqual("other\n", (workspaces[0] / "payload").read_text(encoding="utf-8"))

    def test_noop_revalidates_the_canonical_file_path(self) -> None:
        target = self.root / "policy"
        target.write_text("same\n", encoding="utf-8")
        parameters = self.common(target, "file")
        parameters.update(
            content="same\n",
            allow_absent=False,
            expected_checksum=hashlib.sha256(b"same\n").hexdigest(),
        )
        replacement = self.root / "replacement"
        replacement.write_text("foreign\n", encoding="utf-8")

        real_revalidated_entry = MODULE._revalidated_entry

        def replace_during_parent_check(module: object, parent: int, name: str) -> os.stat_result | None:
            os.replace(replacement, target)
            return real_revalidated_entry(module, parent, name)

        with mock.patch.object(MODULE, "_revalidated_entry", side_effect=replace_during_parent_check):
            result = self.execute(parameters, failure=True)
        self.assertIn("changed before no-op completion", str(result["msg"]))
        self.assertEqual("foreign\n", target.read_text(encoding="utf-8"))

    def test_noop_revalidates_the_canonical_directory_path(self) -> None:
        target = self.root / "managed"
        parameters = self.common(target, "directory")
        self.execute(parameters)
        foreign = self.root / "foreign"
        foreign.mkdir(mode=0o755)

        real_revalidated_entry = MODULE._revalidated_entry

        def replace_during_parent_check(module: object, parent: int, name: str) -> os.stat_result | None:
            target.rename(self.root / "detached")
            foreign.rename(target)
            return real_revalidated_entry(module, parent, name)

        with mock.patch.object(MODULE, "_revalidated_entry", side_effect=replace_during_parent_check):
            result = self.execute(parameters, failure=True)
        self.assertIn("changed before no-op completion", str(result["msg"]))
        self.assertTrue(target.is_dir())

    def test_create_revalidates_the_final_canonical_file(self) -> None:
        target = self.root / "policy"
        detached = self.root / "detached"
        foreign = self.root / "foreign"
        foreign.write_text("foreign\n", encoding="utf-8")
        parameters = self.common(target, "file")
        parameters["content"] = "managed\n"

        real_revalidated_entry = MODULE._revalidated_entry

        def replace_during_parent_check(module: object, parent: int, name: str) -> os.stat_result | None:
            target.rename(detached)
            foreign.rename(target)
            return real_revalidated_entry(module, parent, name)

        with mock.patch.object(MODULE, "_revalidated_entry", side_effect=replace_during_parent_check):
            result = self.execute(parameters, failure=True)
        self.assertIn("identity changed at the canonical boundary", str(result["msg"]))
        self.assertFalse(target.exists())
        self.assertEqual("foreign\n", Path(str(result["recovery_path"])).read_text(encoding="utf-8"))
        self.assertEqual("managed\n", detached.read_text(encoding="utf-8"))

    def test_directory_creation_tolerates_first_consumer_child(self) -> None:
        target = self.root / "managed"
        parameters = self.common(target, "directory")
        real_revalidated_entry = MODULE._revalidated_entry

        def add_first_child(module: object, parent: int, name: str) -> os.stat_result | None:
            (target / "consumer").write_text("ready\n", encoding="utf-8")
            return real_revalidated_entry(module, parent, name)

        with mock.patch.object(MODULE, "_revalidated_entry", side_effect=add_first_child):
            result = self.execute(parameters)
        self.assertTrue(result["changed"])
        self.assertEqual("ready\n", (target / "consumer").read_text(encoding="utf-8"))

    def test_canonical_revalidation_detects_parent_replacement_after_first_open(self) -> None:
        managed = self.root / "managed"
        managed.mkdir()
        target = managed / "policy"
        target.write_text("same\n", encoding="utf-8")
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "policy").write_text("foreign\n", encoding="utf-8")
        parameters = self.common(target, "file")
        parameters["parent_identities"] = self.identities(self.root, managed)
        parameters.update(
            content="same\n",
            allow_absent=False,
            expected_checksum=hashlib.sha256(b"same\n").hexdigest(),
        )
        real_open_bound = MODULE._open_bound_directory
        calls = 0

        def replace_after_first_open(path: str, identities: dict) -> int:
            nonlocal calls
            descriptor = real_open_bound(path, identities)
            calls += 1
            if calls == 2:
                managed.rename(self.root / "detached")
                foreign.rename(managed)
            return descriptor

        with mock.patch.object(MODULE, "_open_bound_directory", side_effect=replace_after_first_open):
            result = self.execute(parameters, failure=True)
        self.assertIn("parent identity changed", str(result["msg"]))
        self.assertEqual("foreign\n", (managed / "policy").read_text(encoding="utf-8"))

    def test_post_capture_inspection_failure_preserves_recovery_entry(self) -> None:
        target = self.root / "policy"
        target.write_text("managed\n", encoding="utf-8")
        expected = target.stat()
        workspace_path = self.root / "workspace"
        workspace_path.mkdir()
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        workspace = os.open(workspace_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        real_stat = os.stat

        def fail_capture_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            if path == "failed" and kwargs.get("dir_fd") == workspace:
                raise OSError("inspection denied")
            return real_stat(path, *args, **kwargs)

        try:
            with mock.patch.object(MODULE.os, "stat", side_effect=fail_capture_stat):
                with self.assertRaises(MODULE._PreservedRecovery):
                    MODULE._capture_and_remove(
                        parent,
                        target.name,
                        expected,
                        workspace,
                        "failed",
                        checksum=hashlib.sha256(b"managed\n").hexdigest(),
                    )
        finally:
            os.close(workspace)
            os.close(parent)
        self.assertFalse(target.exists())
        self.assertEqual("managed\n", (workspace_path / "failed").read_text(encoding="utf-8"))

    def test_directory_capture_preserves_metadata_drift(self) -> None:
        target = self.root / "managed"
        target.mkdir(mode=0o755)
        expected = target.stat()
        target.chmod(0o700)
        workspace_path = self.root / "workspace"
        workspace_path.mkdir()
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        workspace = os.open(workspace_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with self.assertRaises(MODULE._PreservedRecovery):
                MODULE._capture_and_remove(
                    parent,
                    target.name,
                    expected,
                    workspace,
                    "failed",
                    directory=True,
                )
        finally:
            os.close(workspace)
            os.close(parent)
        self.assertFalse(target.exists())
        self.assertEqual(0o700, (workspace_path / "failed").stat().st_mode & 0o777)

    def test_update_failure_reports_preserved_recovery_path(self) -> None:
        target = self.root / "policy"
        target.write_text("owned\n", encoding="utf-8")
        parameters = self.common(target, "file")
        parameters.update(
            content="new\n",
            allow_absent=False,
            expected_checksum=hashlib.sha256(b"owned\n").hexdigest(),
        )
        with mock.patch.object(MODULE, "_revalidated_entry", side_effect=OSError("parent moved")):
            result = self.execute(parameters, failure=True)
        self.assertIn("recovery workspace preserved", str(result["msg"]))
        self.assertEqual("new\n", target.read_text(encoding="utf-8"))
        self.assertEqual("owned\n", Path(str(result["recovery_path"])).read_text(encoding="utf-8"))

    def test_parent_replacement_reports_descriptor_stable_recovery_path(self) -> None:
        managed = self.root / "managed"
        managed.mkdir()
        target = managed / "policy"
        target.write_text("owned\n", encoding="utf-8")
        parameters = self.common(target, "file")
        parameters["parent_identities"] = self.identities(self.root, managed)
        parameters.update(
            content="new\n",
            allow_absent=False,
            expected_checksum=hashlib.sha256(b"owned\n").hexdigest(),
        )
        detached = self.root / "detached"

        def replace_parent(_module: object, _parent: int, _name: str) -> os.stat_result | None:
            managed.rename(detached)
            managed.mkdir()
            raise OSError("parent moved")

        with mock.patch.object(MODULE, "_revalidated_entry", side_effect=replace_parent):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertTrue(str(recovery).startswith(str(detached)))
        self.assertEqual("owned\n", recovery.read_text(encoding="utf-8"))

    def test_double_root_path_is_rejected(self) -> None:
        for path in ("//", "//tmp/file"):
            parameters = self.common(self.root / "unused", "directory")
            parameters["path"] = path
            self.assertIn("canonical absolute path", str(self.execute(parameters, failure=True)["msg"]))


if __name__ == "__main__":
    unittest.main()
