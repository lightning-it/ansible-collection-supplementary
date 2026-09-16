from __future__ import annotations

import errno
import hashlib
import importlib.util
import os
import stat
import sys
import tempfile
import types
import unittest
from collections.abc import Callable
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
    options: dict[str, object] = {}

    def __init__(self, **options: object) -> None:
        type(self).options = options
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

    def test_descriptor_path_uses_dev_fd_before_platform_fallback(self) -> None:
        descriptor = 42

        def read_descriptor_link(path: str) -> str:
            if path == f"/proc/self/fd/{descriptor}":
                raise FileNotFoundError(path)
            if path == f"/dev/fd/{descriptor}":
                return str(self.root)
            raise AssertionError(path)

        with (
            mock.patch.object(MODULE.os, "readlink", side_effect=read_descriptor_link),
            mock.patch.object(MODULE.fcntl, "fcntl") as fallback,
        ):
            self.assertEqual(str(self.root), MODULE._descriptor_path(descriptor))
        fallback.assert_not_called()

    def test_descriptor_path_accepts_existing_literal_deleted_suffix(self) -> None:
        literal = self.root / "literal (deleted)"
        literal.mkdir()
        descriptor = os.open(literal, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with mock.patch.object(MODULE.os, "readlink", return_value=str(literal)):
                self.assertEqual(str(literal), MODULE._descriptor_path(descriptor))
        finally:
            os.close(descriptor)

    def test_supplied_root_identity_is_enforced_for_deeper_parent(self) -> None:
        target = self.root / "policy"
        parameters = self.common(target, "file")
        parameters["content"] = "blocked\n"
        root = Path("/").stat()
        parameters["parent_identities"]["/"] = {
            "device": root.st_dev,
            "inode": root.st_ino + 1,
        }
        result = self.execute(parameters, failure=True)
        self.assertIn("parent identity changed: /", str(result["msg"]))
        self.assertFalse(target.exists())

    def test_macos_rename_flags_are_bound_to_the_requested_operation(self) -> None:
        renameatx_np = mock.Mock(return_value=0)
        library = types.SimpleNamespace(renameatx_np=renameatx_np)
        with mock.patch.object(MODULE.ctypes, "CDLL", return_value=library):
            MODULE._renameat(3, "source", 4, "target", "noreplace")
            MODULE._renameat(3, "source", 4, "target", "exchange")
        self.assertEqual(4, renameatx_np.call_args_list[0].args[-1])
        self.assertEqual(2, renameatx_np.call_args_list[1].args[-1])

    def test_root_parent_identity_is_validated(self) -> None:
        parameters = self.common(Path("/policy"), "directory")
        root = Path("/").stat()
        parameters["parent_identities"] = {"/": {"device": root.st_dev, "inode": root.st_ino + 1}}
        self.assertIn("parent identity changed", str(self.execute(parameters, check=True, failure=True)["msg"]))

    def test_malformed_root_parent_identity_uses_the_stable_contract(self) -> None:
        parameters = self.common(Path("/policy"), "directory")
        root = Path("/").stat()
        for identity in ({"inode": root.st_ino}, {"device": True, "inode": root.st_ino}):
            with self.subTest(identity=identity):
                parameters["parent_identities"] = {"/": identity}
                result = self.execute(parameters, check=True, failure=True)
                self.assertIn("parent identity is malformed: /", str(result["msg"]))

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

    def test_file_exchange_fsyncs_recovery_workspace_before_parent(self) -> None:
        target = self.root / "policy.conf"
        target.write_text("first\n", encoding="utf-8")
        parameters = self.common(target, "file")
        parameters.update(
            content="second\n",
            allow_absent=False,
            expected_checksum=hashlib.sha256(b"first\n").hexdigest(),
        )
        real_private_workspace = MODULE._private_workspace
        workspace_descriptor = -1
        fsync_order: list[int] = []

        def track_workspace(parent: int) -> tuple[int, str, os.stat_result]:
            nonlocal workspace_descriptor
            result = real_private_workspace(parent)
            workspace_descriptor = result[0]
            return result

        with (
            mock.patch.object(MODULE, "_private_workspace", side_effect=track_workspace),
            mock.patch.object(MODULE, "_fsync_directory", side_effect=fsync_order.append),
        ):
            result = self.execute(parameters)
        self.assertTrue(result["changed"])
        self.assertGreaterEqual(len(fsync_order), 2)
        self.assertEqual(workspace_descriptor, fsync_order[0])
        self.assertNotEqual(workspace_descriptor, fsync_order[1])
        self.assertEqual("second\n", target.read_text(encoding="utf-8"))

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

    def test_parent_walk_close_failure_closes_the_new_descriptor(self) -> None:
        real_open = os.open
        real_close = os.close
        opened: list[int] = []
        close_failed = False

        def track_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            descriptor = real_open(path, flags, *args, **kwargs)
            opened.append(descriptor)
            return descriptor

        def fail_first_close(descriptor: int) -> None:
            nonlocal close_failed
            if not close_failed:
                close_failed = True
                real_close(descriptor)
                raise OSError("parent descriptor close outcome uncertain")
            real_close(descriptor)

        with (
            mock.patch.object(MODULE.os, "open", side_effect=track_open),
            mock.patch.object(MODULE.os, "close", side_effect=fail_first_close),
        ):
            with self.assertRaisesRegex(OSError, "parent descriptor close outcome uncertain"):
                MODULE._open_bound_directory(str(self.root), self.identities(self.root))
        self.assertGreaterEqual(len(opened), 2)
        for descriptor in opened:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

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

    def test_private_workspace_accepts_inherited_setgid_without_group_access(self) -> None:
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        real_fstat = os.fstat

        def inherited_setgid(descriptor: int) -> os.stat_result:
            current = real_fstat(descriptor)
            values = list(current)
            values[stat.ST_MODE] |= stat.S_ISGID
            return os.stat_result(values)

        descriptor = -1
        name = ""
        try:
            with mock.patch.object(MODULE.os, "fstat", side_effect=inherited_setgid):
                descriptor, name, opened = MODULE._private_workspace(parent)
            self.assertEqual(0o700, stat.S_IMODE(opened.st_mode) & 0o777)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if name:
                os.rmdir(name, dir_fd=parent)
            os.close(parent)

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

    def test_file_check_mode_never_creates_or_changes_payloads(self) -> None:
        target = self.root / "policy"
        parameters = self.common(target, "file")
        parameters["content"] = "planned\n"
        self.assertTrue(self.execute(parameters, check=True)["changed"])
        self.assertFalse(target.exists())
        self.assertEqual([], list(self.root.glob(".atomic-path-*")))

        target.write_text("existing\n", encoding="utf-8")
        parameters.update(
            content="replacement\n",
            allow_absent=False,
            expected_checksum=hashlib.sha256(b"existing\n").hexdigest(),
        )
        self.assertTrue(self.execute(parameters, check=True)["changed"])
        self.assertEqual("existing\n", target.read_text(encoding="utf-8"))
        self.assertEqual([], list(self.root.glob(".atomic-path-*")))

    def test_private_cleanup_stat_error_reports_uncertain_entry(self) -> None:
        target = self.root / "payload"
        target.write_text("owned\n", encoding="utf-8")
        expected = target.stat()
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        real_stat = os.stat

        def fail_payload_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
            if path == target.name and kwargs.get("dir_fd") == parent:
                raise OSError("cleanup inspection denied")
            return real_stat(path, *args, **kwargs)

        try:
            with mock.patch.object(MODULE.os, "stat", side_effect=fail_payload_stat):
                self.assertFalse(MODULE._remove_private_if_same(parent, target.name, expected))
        finally:
            os.close(parent)
        self.assertEqual("owned\n", target.read_text(encoding="utf-8"))

    def test_post_commit_directory_fsync_is_best_effort(self) -> None:
        real_fsync = os.fsync
        real_fstat = os.fstat

        def reject_directory_fsync(descriptor: int) -> None:
            if stat.S_ISDIR(real_fstat(descriptor).st_mode):
                raise OSError(errno.EINVAL, "directory fsync unsupported")
            real_fsync(descriptor)

        for state in ("directory", "file"):
            with self.subTest(state=state):
                target = self.root / f"managed-{state}"
                parameters = self.common(target, state)
                if state == "file":
                    parameters["content"] = "durable\n"
                with mock.patch.object(MODULE.os, "fsync", side_effect=reject_directory_fsync):
                    self.assertTrue(self.execute(parameters)["changed"])
                self.assertTrue(target.exists())

    def test_post_commit_directory_fsync_io_error_fails_closed(self) -> None:
        real_fsync = os.fsync
        real_fstat = os.fstat

        def fail_directory_fsync(descriptor: int) -> None:
            if stat.S_ISDIR(real_fstat(descriptor).st_mode):
                raise OSError(errno.EIO, "directory fsync failed")
            real_fsync(descriptor)

        for state in ("directory", "file"):
            with self.subTest(state=state):
                target = self.root / f"failed-{state}"
                parameters = self.common(target, state)
                if state == "file":
                    parameters["content"] = "not-durable\n"
                with mock.patch.object(MODULE.os, "fsync", side_effect=fail_directory_fsync):
                    result = self.execute(parameters, failure=True)
                self.assertIn("directory fsync failed", str(result["msg"]))
                self.assertFalse(target.exists())
                self.assertEqual([], list(self.root.glob(".atomic-path-*")))

    def test_rollback_cleanup_failure_reports_the_captured_entry(self) -> None:
        target = self.root / "captured"
        parameters = self.common(target, "file")
        parameters["content"] = "managed\n"
        real_remove = MODULE._remove_private_if_same
        fsync_calls = 0

        def fail_parent_fsync(_descriptor: int) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == 1:
                raise OSError(errno.EIO, "parent fsync failed")

        def preserve_capture(
            parent: int,
            name: str,
            expected: os.stat_result,
            *,
            directory: bool = False,
        ) -> bool:
            if name == "failed":
                return False
            return real_remove(parent, name, expected, directory=directory)

        with (
            mock.patch.object(MODULE, "_fsync_directory", side_effect=fail_parent_fsync),
            mock.patch.object(MODULE, "_remove_private_if_same", side_effect=preserve_capture),
        ):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertEqual("failed", recovery.name)
        self.assertEqual("managed\n", recovery.read_text(encoding="utf-8"))
        self.assertFalse(target.exists())

    def test_rollback_error_preserves_uncertain_transaction_workspace(self) -> None:
        for state in ("directory", "file"):
            with self.subTest(state=state):
                target = self.root / f"rollback-error-{state}"
                parameters = self.common(target, state)
                if state == "file":
                    parameters["content"] = "managed\n"
                with (
                    mock.patch.object(MODULE, "_fsync_directory", side_effect=OSError("commit probe failed")),
                    mock.patch.object(MODULE, "_capture_and_remove", side_effect=OSError("rollback failed")),
                ):
                    result = self.execute(parameters, failure=True)
                recovery = Path(str(result["recovery_path"]))
                self.assertIn("transaction state is uncertain", str(result["msg"]))
                self.assertTrue(recovery.is_dir())
                self.assertTrue(target.exists())

    def test_target_disappearance_during_rollback_is_uncertain(self) -> None:
        for state in ("directory", "file"):
            with self.subTest(state=state):
                target = self.root / f"rollback-disappearance-{state}"
                parameters = self.common(target, state)
                if state == "file":
                    parameters["content"] = "managed\n"
                real_renameat = MODULE._renameat
                rename_calls = 0

                def remove_before_rollback(
                    source_fd: int,
                    source: str,
                    target_fd: int,
                    target_name: str,
                    operation: str,
                    real_rename: Callable[[int, str, int, str, str], None] = real_renameat,
                    managed_state: str = state,
                ) -> None:
                    nonlocal rename_calls
                    rename_calls += 1
                    if rename_calls == 2:
                        if managed_state == "directory":
                            os.rmdir(source, dir_fd=source_fd)
                        else:
                            os.unlink(source, dir_fd=source_fd)
                    real_rename(source_fd, source, target_fd, target_name, operation)

                with (
                    mock.patch.object(MODULE, "_fsync_directory", side_effect=OSError("commit probe failed")),
                    mock.patch.object(MODULE, "_renameat", side_effect=remove_before_rollback),
                ):
                    result = self.execute(parameters, failure=True)
                recovery = Path(str(result["recovery_path"]))
                self.assertIn("target disappeared", str(result["msg"]))
                self.assertIn("transaction state is uncertain", str(result["msg"]))
                self.assertTrue(recovery.is_dir())
                self.assertFalse(target.exists())

    def test_directory_payload_close_failure_reports_workspace_root(self) -> None:
        target = self.root / "managed-close"
        parameters = self.common(target, "directory")
        real_open = os.open
        real_close = os.close
        payload_descriptor = -1
        close_failed = False

        def track_payload(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal payload_descriptor
            descriptor = real_open(path, flags, *args, **kwargs)
            if path == "payload":
                payload_descriptor = descriptor
            return descriptor

        def fail_payload_close(descriptor: int) -> None:
            nonlocal close_failed
            if descriptor == payload_descriptor and not close_failed:
                close_failed = True
                real_close(descriptor)
                raise OSError("directory payload close outcome uncertain")
            real_close(descriptor)

        with (
            mock.patch.object(MODULE, "_require_capabilities"),
            mock.patch.object(MODULE.os, "open", side_effect=track_payload),
            mock.patch.object(MODULE.os, "close", side_effect=fail_payload_close),
        ):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertTrue(recovery.is_dir())
        self.assertFalse((recovery / "payload").exists())
        self.assertTrue(target.is_dir())

    def test_directory_rollback_close_failure_reports_workspace_root(self) -> None:
        target = self.root / "managed-rollback-close"
        parameters = self.common(target, "directory")
        real_open = os.open
        real_close = os.close
        real_fsync = os.fsync
        real_fstat = os.fstat
        payload_descriptor = -1
        close_failed = False

        def track_payload(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal payload_descriptor
            descriptor = real_open(path, flags, *args, **kwargs)
            if path == "payload":
                payload_descriptor = descriptor
            return descriptor

        def fail_directory_fsync(descriptor: int) -> None:
            if stat.S_ISDIR(real_fstat(descriptor).st_mode):
                raise OSError(errno.EIO, "directory fsync failed")
            real_fsync(descriptor)

        def fail_payload_close(descriptor: int) -> None:
            nonlocal close_failed
            if descriptor == payload_descriptor and not close_failed:
                close_failed = True
                real_close(descriptor)
                raise OSError("directory payload close outcome uncertain")
            real_close(descriptor)

        with (
            mock.patch.object(MODULE, "_require_capabilities"),
            mock.patch.object(MODULE.os, "open", side_effect=track_payload),
            mock.patch.object(MODULE.os, "fsync", side_effect=fail_directory_fsync),
            mock.patch.object(MODULE.os, "close", side_effect=fail_payload_close),
        ):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertTrue(recovery.is_dir())
        self.assertFalse((recovery / "payload").exists())
        self.assertFalse((recovery / "failed").exists())
        self.assertFalse(target.exists())

    def test_successful_file_close_failure_reports_workspace_root(self) -> None:
        target = self.root / "policy"
        parameters = self.common(target, "file")
        parameters["content"] = "managed\n"
        real_open = os.open
        real_close = os.close
        payload_descriptor = -1
        close_failed = False

        def track_payload(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal payload_descriptor
            descriptor = real_open(path, flags, *args, **kwargs)
            if path == "payload":
                payload_descriptor = descriptor
            return descriptor

        def fail_payload_close(descriptor: int) -> None:
            nonlocal close_failed
            if descriptor == payload_descriptor and not close_failed:
                close_failed = True
                real_close(descriptor)
                raise OSError("payload close outcome uncertain")
            real_close(descriptor)

        with (
            mock.patch.object(MODULE, "_require_capabilities"),
            mock.patch.object(MODULE.os, "open", side_effect=track_payload),
            mock.patch.object(MODULE.os, "close", side_effect=fail_payload_close),
        ):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertTrue(recovery.is_dir())
        self.assertFalse((recovery / "payload").exists())
        self.assertEqual("managed\n", target.read_text(encoding="utf-8"))

    def test_staging_failure_and_close_error_reports_workspace_root(self) -> None:
        target = self.root / "staging-close-failure"
        parameters = self.common(target, "file")
        parameters["content"] = "managed\n"
        real_open = os.open
        real_close = os.close
        payload_descriptor = -1
        close_failed = False

        def track_payload(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal payload_descriptor
            descriptor = real_open(path, flags, *args, **kwargs)
            if path == "payload":
                payload_descriptor = descriptor
            return descriptor

        def fail_payload_close(descriptor: int) -> None:
            nonlocal close_failed
            if descriptor == payload_descriptor and not close_failed:
                close_failed = True
                real_close(descriptor)
                raise OSError("payload close outcome uncertain")
            real_close(descriptor)

        with (
            mock.patch.object(MODULE, "_require_capabilities"),
            mock.patch.object(MODULE.os, "open", side_effect=track_payload),
            mock.patch.object(MODULE.os, "fchown", side_effect=OSError("staging metadata failed")),
            mock.patch.object(MODULE.os, "close", side_effect=fail_payload_close),
        ):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertIn("staging metadata failed", str(result["msg"]))
        self.assertTrue(recovery.is_dir())
        self.assertFalse((recovery / "payload").exists())
        self.assertFalse(target.exists())

    def test_successful_workspace_close_failure_reports_workspace_root(self) -> None:
        target = self.root / "policy-workspace-close"
        parameters = self.common(target, "file")
        parameters["content"] = "managed\n"
        real_private_workspace = MODULE._private_workspace
        real_close = os.close
        workspace_descriptor = -1
        close_failed = False

        def track_workspace(parent: int) -> tuple[int, str, os.stat_result]:
            nonlocal workspace_descriptor
            result = real_private_workspace(parent)
            workspace_descriptor = result[0]
            return result

        def fail_workspace_close(descriptor: int) -> None:
            nonlocal close_failed
            if descriptor == workspace_descriptor and not close_failed:
                close_failed = True
                real_close(descriptor)
                raise OSError("workspace close outcome uncertain")
            real_close(descriptor)

        with (
            mock.patch.object(MODULE, "_private_workspace", side_effect=track_workspace),
            mock.patch.object(MODULE.os, "close", side_effect=fail_workspace_close),
        ):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertTrue(recovery.is_dir())
        self.assertFalse((recovery / "payload").exists())
        self.assertEqual("managed\n", target.read_text(encoding="utf-8"))

    def test_parent_close_failure_does_not_replace_success_result(self) -> None:
        target = self.root / "policy-parent-close"
        parameters = self.common(target, "file")
        parameters["content"] = "managed\n"
        real_open_bound = MODULE._open_bound_directory
        real_close = os.close
        parent_descriptor = -1
        close_failed = False

        def track_initial_parent(path: str, identities: dict) -> int:
            nonlocal parent_descriptor
            descriptor = real_open_bound(path, identities)
            if parent_descriptor < 0:
                parent_descriptor = descriptor
            return descriptor

        def fail_parent_close(descriptor: int) -> None:
            nonlocal close_failed
            if descriptor == parent_descriptor and not close_failed:
                close_failed = True
                real_close(descriptor)
                raise OSError("parent close outcome uncertain")
            real_close(descriptor)

        with (
            mock.patch.object(MODULE, "_open_bound_directory", side_effect=track_initial_parent),
            mock.patch.object(MODULE.os, "close", side_effect=fail_parent_close),
        ):
            result = self.execute(parameters)
        self.assertTrue(result["changed"])
        self.assertEqual("managed\n", target.read_text(encoding="utf-8"))

    def test_required_no_follow_flag_must_be_nonzero(self) -> None:
        with mock.patch.object(MODULE.os, "O_NOFOLLOW", 0):
            with self.assertRaisesRegex(OSError, "descriptor-relative no-follow"):
                MODULE._require_capabilities()

    def test_private_workspace_probe_failure_closes_and_cleans_creation(self) -> None:
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        real_open = os.open
        real_fstat = os.fstat
        workspace_descriptor = -1

        def track_workspace(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal workspace_descriptor
            descriptor = real_open(path, flags, *args, **kwargs)
            if str(path).startswith(".atomic-path-"):
                workspace_descriptor = descriptor
            return descriptor

        def fail_workspace_probe(descriptor: int) -> os.stat_result:
            if descriptor == workspace_descriptor:
                raise OSError("workspace probe denied")
            return real_fstat(descriptor)

        try:
            with (
                mock.patch.object(MODULE.os, "open", side_effect=track_workspace),
                mock.patch.object(MODULE.os, "fstat", side_effect=fail_workspace_probe),
            ):
                with self.assertRaisesRegex(OSError, "workspace probe denied"):
                    MODULE._private_workspace(parent)
        finally:
            os.close(parent)
        self.assertEqual([], list(self.root.glob(".atomic-path-*")))

    def test_private_workspace_probe_and_close_failure_preserves_creation(self) -> None:
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        real_open = os.open
        real_fstat = os.fstat
        real_close = os.close
        workspace_descriptor = -1
        close_failed = False

        def track_workspace(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal workspace_descriptor
            descriptor = real_open(path, flags, *args, **kwargs)
            if str(path).startswith(".atomic-path-"):
                workspace_descriptor = descriptor
            return descriptor

        def fail_workspace_probe(descriptor: int) -> os.stat_result:
            if descriptor == workspace_descriptor:
                raise OSError("workspace probe denied")
            return real_fstat(descriptor)

        def fail_workspace_close(descriptor: int) -> None:
            nonlocal close_failed
            if descriptor == workspace_descriptor and not close_failed:
                close_failed = True
                real_close(descriptor)
                raise OSError("workspace close outcome uncertain")
            real_close(descriptor)

        try:
            with (
                mock.patch.object(MODULE.os, "open", side_effect=track_workspace),
                mock.patch.object(MODULE.os, "fstat", side_effect=fail_workspace_probe),
                mock.patch.object(MODULE.os, "close", side_effect=fail_workspace_close),
            ):
                with self.assertRaises(MODULE._PreservedWorkspace) as result:
                    MODULE._private_workspace(parent)
        finally:
            os.close(parent)
        self.assertTrue(Path(result.exception.path).is_dir())

    def test_nonreadable_file_mode_is_verified_via_bound_descriptor(self) -> None:
        target = self.root / "sealed"
        parameters = self.common(target, "file")
        parameters.update(content="sealed\n", mode="0000")
        try:
            self.assertTrue(self.execute(parameters)["changed"])
            self.assertEqual(0, target.stat().st_mode & 0o777)
        finally:
            if target.exists():
                target.chmod(0o600)
        self.assertEqual("sealed\n", target.read_text(encoding="utf-8"))

    def test_uninspectable_failed_payload_is_preserved_without_masking_failure(self) -> None:
        target = self.root / "policy"
        parameters = self.common(target, "file")
        parameters["content"] = "blocked\n"
        real_open = os.open
        real_fstat = os.fstat
        payload_descriptor = -1

        def track_payload(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal payload_descriptor
            descriptor = real_open(path, flags, *args, **kwargs)
            if path == "payload":
                payload_descriptor = descriptor
            return descriptor

        def fail_payload_probe(descriptor: int) -> os.stat_result:
            if descriptor == payload_descriptor:
                raise OSError("payload probe denied")
            return real_fstat(descriptor)

        with (
            mock.patch.object(MODULE, "_require_capabilities"),
            mock.patch.object(MODULE.os, "open", side_effect=track_payload),
            mock.patch.object(MODULE.os, "fchown", side_effect=OSError("metadata denied")),
            mock.patch.object(MODULE.os, "fstat", side_effect=fail_payload_probe),
        ):
            result = self.execute(parameters, failure=True)
        recovery = Path(str(result["recovery_path"]))
        self.assertIn("metadata denied", str(result["msg"]))
        self.assertTrue(recovery.is_file())
        self.assertFalse(target.exists())

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

    def test_capture_verification_error_preserves_recovery_entry(self) -> None:
        target = self.root / "policy"
        target.write_text("managed\n", encoding="utf-8")
        expected = target.stat()
        workspace_path = self.root / "workspace"
        workspace_path.mkdir()
        parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        workspace = os.open(workspace_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with mock.patch.object(MODULE, "_verified_file", side_effect=OSError("verification failed")):
                with self.assertRaises(MODULE._PreservedRecovery) as result:
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
        self.assertEqual("failed", result.exception.entry)
        self.assertFalse(target.exists())
        self.assertEqual("managed\n", (workspace_path / "failed").read_text(encoding="utf-8"))

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

    def test_parent_replacement_after_private_cleanup_fails_with_stable_recovery_path(self) -> None:
        for state in ("directory", "file"):
            with self.subTest(state=state):
                managed = self.root / f"managed-{state}"
                managed.mkdir()
                target = managed / "target"
                parameters = self.common(target, state)
                parameters["parent_identities"] = self.identities(self.root, managed)
                if state == "file":
                    parameters["content"] = "managed\n"
                detached = self.root / f"detached-{state}"
                real_revalidated_entry = MODULE._revalidated_entry
                calls = 0

                def replace_after_cleanup(
                    module: object,
                    parent: int,
                    name: str,
                    real_revalidate: Callable[[object, int, str], os.stat_result | None] = real_revalidated_entry,
                    managed_path: Path = managed,
                    detached_path: Path = detached,
                ) -> os.stat_result | None:
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        return real_revalidate(module, parent, name)
                    managed_path.rename(detached_path)
                    managed_path.mkdir()
                    raise OSError("parent moved after private cleanup")

                with mock.patch.object(MODULE, "_revalidated_entry", side_effect=replace_after_cleanup):
                    result = self.execute(parameters, failure=True)
                recovery = Path(str(result["recovery_path"]))
                self.assertIn("failed after commit", str(result["msg"]))
                self.assertTrue(str(recovery).startswith(str(detached)))
                self.assertTrue(recovery.exists())
                self.assertFalse(target.exists())

    def test_double_root_path_is_rejected(self) -> None:
        for path in ("//", "//tmp/file"):
            parameters = self.common(self.root / "unused", "directory")
            parameters["path"] = path
            self.assertIn("canonical absolute path", str(self.execute(parameters, failure=True)["msg"]))

    def test_path_aliases_are_rejected_before_ansible_can_expand_them(self) -> None:
        for path in ("~/managed", "$HOME/managed"):
            parameters = self.common(self.root / "unused", "directory")
            parameters["path"] = path
            self.assertIn("canonical absolute path", str(self.execute(parameters, failure=True)["msg"]))
            argument_spec = FakeModule.options["argument_spec"]
            self.assertIsInstance(argument_spec, dict)
            self.assertEqual("str", argument_spec["path"]["type"])


if __name__ == "__main__":
    unittest.main()
