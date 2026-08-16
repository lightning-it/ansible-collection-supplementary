"""Verify Base-bound evidence for a reviewed Trust-Root engine update.

This controller is deliberately separate from ``lit-push-ready.py``.  It loads
the immutable engine blob from the authoritative Base, verifies that the Base
did not move during preparation, and delegates advisory evidence validation to
that Base code. The candidate engine therefore never validates its own evidence.

The controller has no bootstrap mode. Its first introduction is reviewed by
the existing protected Current-Head path and merged through protected server
gates. Only then may ``install`` cache that
now-Base controller from an unchanged authoritative Base checkout. This means
that a controller absent from Base cannot create evidence, seed the cache, or
authorize a push. This controller never invokes an external reviewer and never
installs or replaces a Git hook.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

git_binary = shutil.which("git")
if not git_binary:
    raise RuntimeError("git executable is unavailable")
GIT_BINARY: str = git_binary

ROOT = Path(
    os.environ.get("LIT_TRUST_ROOT_REPOSITORY")
    or subprocess.run(  # noqa: S603, S607
        [GIT_BINARY, "rev-parse", "--show-toplevel"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()
).resolve()
BASE_REF = "refs/remotes/origin/develop"
ENGINE_PATH = "scripts/lit-push-ready.py"
CONTROLLER_PATH = "scripts/lit-trust-root-base-verifier.py"
CACHE_NAME = "lit-trust-root-base-verifier.py"
PUBLIC_ORIGIN = "https://github.com/lightning-it/ansible-collection-supplementary.git"
MAX_CONTROLLER_BYTES = 1_000_000
SAFE_LOCAL_CONFIG_KEYS = frozenset(
    {
        "core.bare",
        "core.filemode",
        "core.ignorecase",
        "core.logallrefupdates",
        "core.precomposeunicode",
        "core.repositoryformatversion",
        "remote.origin.fetch",
        "remote.origin.url",
    }
)
SAFE_LOCAL_BRANCH_CONFIG = re.compile(r"branch\..+\.(?:merge|remote)\Z")


def run_git(*args: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(  # noqa: S603, S607, UP022
        [GIT_BINARY, *args],
        cwd=ROOT,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "Git command failed")
    return result.stdout


def git_text(*args: str, input_bytes: bytes | None = None) -> str:
    return run_git(*args, input_bytes=input_bytes).decode("utf-8", errors="strict").strip()


def require_full_object_id(value: str, description: str) -> str:
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise RuntimeError(f"{description} is not a full Git object ID")
    return value


def candidate_engine_path() -> Path:
    authorized_root = ROOT.resolve(strict=True)
    candidate = authorized_root / ENGINE_PATH
    try:
        candidate.lstat()
    except OSError as exc:
        raise RuntimeError("candidate engine is unavailable") from exc
    if candidate.is_symlink():
        raise RuntimeError("candidate engine must not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("candidate engine is unavailable") from exc
    try:
        resolved.relative_to(authorized_root)
    except ValueError as exc:
        raise RuntimeError("candidate engine escapes the authorized repository") from exc
    return candidate


def load_base_engine() -> tuple[dict[str, Any], str, str]:
    base_commit = require_full_object_id(git_text("rev-parse", "--verify", f"{BASE_REF}^{{commit}}"), "base commit")
    blob = require_full_object_id(
        git_text("rev-parse", "--verify", f"{base_commit}:{ENGINE_PATH}"),
        "base engine blob",
    )
    source = run_git("cat-file", "blob", blob)
    if git_text("hash-object", "--stdin", input_bytes=source) != blob:
        raise RuntimeError("base engine blob digest changed while reading")
    candidate_engine = candidate_engine_path()
    scope: dict[str, Any] = {
        "__name__": "lit_trust_root_base_engine",
        "__file__": str(candidate_engine),
    }
    exec(compile(source, f"<{BASE_REF}:{ENGINE_PATH}@{blob}>", "exec"), scope)  # noqa: S102
    scope["ROOT"] = ROOT
    return scope, base_commit, blob


def require_unchanged_base(expected: str) -> None:
    actual = require_full_object_id(
        git_text("rev-parse", "--verify", f"{BASE_REF}^{{commit}}"),
        "refreshed base commit",
    )
    if actual != expected:
        raise RuntimeError("authoritative Base advanced during Trust-Root preparation")


def public_git_environment() -> dict[str, str]:
    """Return the complete, deliberately tiny environment for public Git reads."""
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "PATH": os.defpath,
    }


def public_git_output(*args: str) -> str:
    result = subprocess.run(  # noqa: S603
        [GIT_BINARY, *args],
        cwd=ROOT,
        env=public_git_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("anonymous Base configuration inspection failed")
    return result.stdout.decode("utf-8", errors="strict").strip()


def require_safe_fetch_configuration() -> None:
    names = public_git_output("config", "--local", "--no-includes", "--name-only", "--list").splitlines()
    unsafe = sorted(
        name
        for raw_name in names
        if (name := raw_name.casefold())
        and name not in SAFE_LOCAL_CONFIG_KEYS
        and SAFE_LOCAL_BRANCH_CONFIG.fullmatch(name) is None
    )
    if unsafe:
        raise RuntimeError(f"anonymous Base refresh rejects local Git configuration: {', '.join(unsafe)}")
    origins = public_git_output(
        "config",
        "--local",
        "--no-includes",
        "--get-all",
        "remote.origin.url",
    ).splitlines()
    if origins != [PUBLIC_ORIGIN]:
        raise RuntimeError("anonymous Base refresh requires exactly one canonical public origin")


def refresh_public_base() -> None:
    require_safe_fetch_configuration()
    result = subprocess.run(  # noqa: S603
        [
            GIT_BINARY,
            "-c",
            "credential.helper=",
            "-c",
            "core.askPass=",
            "-c",
            "http.extraHeader=",
            "-c",
            "http.proxy=",
            "-c",
            "https.proxy=",
            "-c",
            "core.hooksPath=/dev/null",
            "fetch",
            "--no-tags",
            PUBLIC_ORIGIN,
            "refs/heads/develop:refs/remotes/origin/develop",
        ],
        cwd=ROOT,
        env=public_git_environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("anonymous authoritative Base refresh failed")


def git_directory() -> Path:
    value = Path(git_text("rev-parse", "--git-dir"))
    return value if value.is_absolute() else (ROOT / value).resolve()


def cached_controller_path() -> Path:
    return git_directory() / CACHE_NAME


def write_owned_regular_file(path: Path, payload: bytes, *, mode: int) -> None:
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    directory = os.open(path.parent, directory_flags)
    temporary = f".{path.name}.{secrets.token_hex(16)}.tmp"
    descriptor = -1
    try:
        try:
            existing = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(existing.st_mode) or existing.st_uid != os.geteuid():
                raise RuntimeError("Trust-Root verifier target is unsafe")
        descriptor = os.open(temporary, file_flags, mode, dir_fd=directory)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise RuntimeError("Trust-Root verifier write stalled")
            written += count
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        temporary = ""
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=directory,
        )
        installed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(installed.st_mode)
            or installed.st_uid != os.geteuid()
            or stat.S_IMODE(installed.st_mode) != mode
        ):
            raise RuntimeError("Trust-Root verifier installation is unsafe")
        verified = bytearray()
        while True:
            chunk = os.read(descriptor, 65_536)
            if not chunk:
                break
            verified.extend(chunk)
        if bytes(verified) != payload:
            raise RuntimeError("Trust-Root verifier installation changed while reading")
        os.close(descriptor)
        descriptor = -1
        os.fsync(directory)
    except OSError as exc:
        raise RuntimeError("Trust-Root verifier write failed") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)


def base_controller_source(base_commit: str) -> tuple[bytes, str]:
    blob = require_full_object_id(
        git_text("rev-parse", "--verify", f"{base_commit}:{CONTROLLER_PATH}"),
        "base verifier blob",
    )
    source = run_git("cat-file", "blob", blob)
    if len(source) > MAX_CONTROLLER_BYTES:
        raise RuntimeError("base verifier blob is oversized")
    if git_text("hash-object", "--stdin", input_bytes=source) != blob:
        raise RuntimeError("base verifier blob digest changed while reading")
    return source, blob


def install_cached_base_controller(base_commit: str) -> None:
    source, _blob = base_controller_source(base_commit)
    write_owned_regular_file(cached_controller_path(), source, mode=0o700)


def read_cached_controller() -> bytes:
    cached = cached_controller_path()
    descriptor = -1
    try:
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise RuntimeError("cached Trust-Root verifier cannot be opened safely")
        descriptor = os.open(cached, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK | no_follow)
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.geteuid()
            or stat.S_IMODE(details.st_mode) != 0o700
            or details.st_size > MAX_CONTROLLER_BYTES
        ):
            raise RuntimeError("cached Trust-Root verifier is unsafe")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            source = handle.read(MAX_CONTROLLER_BYTES + 1)
        if len(source) > MAX_CONTROLLER_BYTES:
            raise RuntimeError("cached Trust-Root verifier is oversized")
    except OSError as exc:
        raise RuntimeError("cached Trust-Root verifier is unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return source


def require_cached_base_controller(base_commit: str) -> None:
    source = read_cached_controller()
    _base_source, base_blob = base_controller_source(base_commit)
    if git_text("hash-object", "--stdin", input_bytes=source) != base_blob:
        raise RuntimeError("cached Trust-Root verifier differs from pinned Base")


def require_controller_binding(engine: dict[str, Any], change: Any) -> None:
    base_controller = engine["git_tree_entry"](change.base_tip, CONTROLLER_PATH)
    head_controller = engine["git_tree_entry"](change.head_commit, CONTROLLER_PATH)
    if not base_controller:
        raise RuntimeError(
            "Trust-Root controller is absent from the pinned Base; use the Base engine trust-root-update review"
        )
    if not head_controller:
        raise RuntimeError("Trust-Root controller is missing from the candidate")
    if base_controller != head_controller:
        raise RuntimeError("Trust-Root base verifier differs from the pinned Base")


def require_base_checkout(base_commit: str) -> None:
    head_commit = require_full_object_id(git_text("rev-parse", "--verify", "HEAD^{commit}"), "HEAD commit")
    if head_commit != base_commit:
        raise RuntimeError("Trust-Root verifier may only be installed from the unchanged Base")
    base_blob = require_full_object_id(
        git_text("rev-parse", "--verify", f"{base_commit}:{CONTROLLER_PATH}"),
        "base verifier blob",
    )
    head_blob = require_full_object_id(
        git_text("rev-parse", "--verify", f"HEAD:{CONTROLLER_PATH}"),
        "HEAD verifier blob",
    )
    if head_blob != base_blob:
        raise RuntimeError("Trust-Root verifier installation differs from the pinned Base")


def trust_root_verify_policy(engine: dict[str, Any], expected_change: Any):
    def verifier(change: Any, **_kwargs: Any) -> None:
        if change != expected_change:
            raise RuntimeError("Trust-Root evidence change binding drifted")
        require_controller_binding(engine, change)
        engine["require_trust_root_update_contract"](change)

    return verifier


def verify_trust_root_evidence(engine: dict[str, Any], config: dict[str, Any], base_commit: str) -> dict[str, Any]:
    engine["require_clean_head"]()
    refresh_public_base()
    require_unchanged_base(base_commit)
    change = engine["planned_change"](config)
    if change.base_ref != BASE_REF or change.base_tip != base_commit:
        raise RuntimeError("Trust-Root candidate is not bound to the pinned Base verifier")
    require_controller_binding(engine, change)
    require_cached_base_controller(base_commit)
    engine["require_trust_root_update_contract"](change)
    original = engine["require_trusted_check_policy"]
    engine["require_trusted_check_policy"] = trust_root_verify_policy(engine, change)
    try:
        payload = engine["verify_evidence"](config)
    finally:
        engine["require_trusted_check_policy"] = original
    require_unchanged_base(base_commit)
    if payload.get("fixture_manifest_bootstrap") is not False:
        raise RuntimeError("Trust-Root evidence cannot bootstrap fixtures")
    return payload


def install() -> None:
    refresh_public_base()
    engine, base_commit, _blob = load_base_engine()
    engine["require_clean_head"]()
    require_unchanged_base(base_commit)
    require_base_checkout(base_commit)
    install_cached_base_controller(base_commit)
    require_cached_base_controller(base_commit)
    require_unchanged_base(base_commit)
    print(f"Installed pinned Trust-Root verifier for Base {base_commit}")


def verify() -> None:
    refresh_public_base()
    engine, base_commit, _blob = load_base_engine()
    config = engine["load_config"]()
    verify_trust_root_evidence(engine, config, base_commit)
    print("Pinned Trust-Root advisory evidence: PASS; protected server gates remain required")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "verify"))
    args = parser.parse_args(argv)
    if args.command == "install":
        install()
    elif args.command == "verify":
        verify()
    else:  # pragma: no cover - argparse enforces the only values.
        raise RuntimeError("unsupported Trust-Root verifier command")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"trust-root-base-verifier: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
