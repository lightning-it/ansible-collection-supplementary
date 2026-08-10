#!/usr/bin/env python3
"""Verify one immutable App-authored release back-sync head."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import NoReturn, cast

SHA = re.compile(r"^[0-9a-f]{40}$")
SEMVER = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
EVIDENCE_ID = re.compile(r"^MLX90-[A-Z0-9][A-Z0-9._-]{2,127}$")
APP_IDENTITY = (
    "lightning-it-release-automation[bot] <307565056+lightning-it-release-automation[bot]@users.noreply.github.com>"
)
GENERATED_PATHS = {
    "CHANGELOG.rst",
    "changelogs/.plugin-cache.yaml",
    "changelogs/changelog.yaml",
    "changelogs/release-preparation.json",
    "galaxy.yml",
}


class BackSyncError(ValueError):
    """Raised when a back-sync head differs from the immutable contract."""


def fail(message: str) -> NoReturn:
    raise BackSyncError(message)


def git_binary() -> str:
    executable = shutil.which("git")
    if executable is None:
        fail("git executable is unavailable")
    return executable


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(variable, None)
    return environment


def git(root: Path, *arguments: str, text: bool = True) -> str | bytes:
    try:
        result = subprocess.run(  # noqa: S603 -- revisions are validated exact SHAs.
            [git_binary(), *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=text,
            env=git_environment(),
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode(errors="replace")
        raise BackSyncError(f"git {' '.join(arguments)} failed: {stderr.strip()}") from exc
    return cast("str | bytes", result.stdout)


def git_text(root: Path, *arguments: str) -> str:
    value = git(root, *arguments)
    assert isinstance(value, str)
    return value.strip()


def git_bytes(root: Path, *arguments: str) -> bytes:
    value = git(root, *arguments, text=False)
    assert isinstance(value, bytes)
    return value


def require_sha(root: Path, value: str, label: str) -> None:
    if SHA.fullmatch(value) is None or git_text(root, "cat-file", "-t", value) != "commit":
        fail(f"{label} is not an exact commit SHA")


def changes(root: Path, base: str, head: str) -> list[tuple[str, str]]:
    raw = git_bytes(root, "diff", "--name-status", "-z", "--no-renames", base, head, "--", ".")
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        fail("back-sync diff returned malformed path status data")
    result: list[tuple[str, str]] = []
    for index in range(0, len(fields), 2):
        try:
            status = fields[index].decode("ascii")
            path = fields[index + 1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BackSyncError("back-sync diff contains a non-UTF-8 path") from exc
        if status not in {"A", "D", "M", "T"} or not path or path.startswith("/"):
            fail("back-sync diff contains an unsupported path transition")
        result.append((status, path))
    if not result:
        fail("back-sync diff is empty")
    return result


def object_bytes(root: Path, revision: str, path: str) -> bytes | None:
    result = subprocess.run(  # noqa: S603 -- exact validated SHA and controlled path.
        [git_binary(), "show", f"{revision}:{path}"],
        cwd=root,
        check=False,
        capture_output=True,
        env=git_environment(),
        timeout=30,
    )
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 128:
        return None
    fail(f"cannot read {path} from {revision}")


def require_same_path(root: Path, release_sha: str, head_sha: str, path: str) -> None:
    if object_bytes(root, release_sha, path) != object_bytes(root, head_sha, path):
        fail(f"back-sync path differs from the exact release: {path}")


def load_object(root: Path, revision: str, path: str, label: str) -> dict[str, object]:
    raw = object_bytes(root, revision, path)
    if raw is None:
        fail(f"{label} is missing")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BackSyncError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        fail(f"{label} must be a JSON object")
    return value


def verify(
    *,
    root: Path,
    develop_tip: str,
    release_sha: str,
    head_sha: str,
    tag: str,
    security_version: str = "",
    evidence_id: str = "",
) -> None:
    if root.is_symlink() or not root.is_dir():
        fail("repository root must be a regular directory")
    for value, label in (
        (develop_tip, "develop tip"),
        (release_sha, "release SHA"),
        (head_sha, "back-sync head SHA"),
    ):
        require_sha(root, value, label)
    version = tag.removeprefix("v")
    if tag != f"v{version}" or SEMVER.fullmatch(version) is None:
        fail("release tag must contain stable SemVer")

    parents = git_text(root, "show", "-s", "--format=%P", head_sha).split()
    if len(parents) != 2 or parents[1] != release_sha:
        fail("back-sync head must merge the exact release as its second parent")
    develop_base = parents[0]
    if (
        subprocess.run(  # noqa: S603 -- exact validated commits.
            [git_binary(), "merge-base", "--is-ancestor", develop_base, develop_tip],
            cwd=root,
            check=False,
            env=git_environment(),
            timeout=30,
        ).returncode
        != 0
    ):
        fail("back-sync first parent is not an ancestor of current develop")
    for field, label in (("%an <%ae>", "author"), ("%cn <%ce>", "committer")):
        if git_text(root, "show", "-s", f"--format={field}", head_sha) != APP_IDENTITY:
            fail(f"back-sync commit {label} is not the release App")
    if git_text(root, "show", "-s", "--format=%B", head_sha) != f"chore: sync {tag} release back to develop":
        fail("back-sync commit message differs from the deterministic contract")

    release_parents = git_text(root, "show", "-s", "--format=%P", release_sha).split()
    if len(release_parents) != 2:
        fail("release SHA must be a normal two-parent merge commit")
    released_fragment_changes = changes(root, release_parents[0], release_sha)
    deleted_fragments = {
        path for status, path in released_fragment_changes if status == "D" and path.startswith("changelogs/fragments/")
    }

    allowed = set(GENERATED_PATHS)
    if security_version:
        if security_version != version or EVIDENCE_ID.fullmatch(evidence_id) is None:
            fail("Security back-sync identity is invalid")
        metadata = f".lit/security-releases/{version}.json"
        intake = f".lit/security-release-intakes/{version}.json"
        allowed.update({metadata, intake})
        metadata_payload = load_object(root, release_sha, metadata, "Security metadata")
        intake_payload = load_object(root, release_sha, intake, "Security intake receipt")
        if metadata_payload.get("evidenceId") != evidence_id:
            fail("Security metadata evidenceId differs from the classified release")
        request = intake_payload.get("request")
        if not isinstance(request, dict) or request.get("evidenceId") != evidence_id:
            fail("Security intake receipt differs from the classified release")
    elif evidence_id:
        fail("normal back-sync may not carry a Security evidenceId")

    for status, path in changes(root, develop_base, head_sha):
        if path.startswith("changelogs/fragments/"):
            if status != "D" or path not in deleted_fragments:
                fail(f"back-sync contains an unauthorized fragment transition: {path}")
        elif path not in allowed:
            fail(f"back-sync contains a non-release path: {path}")

    for path in sorted(allowed):
        require_same_path(root, release_sha, head_sha, path)
    for path in deleted_fragments:
        if object_bytes(root, head_sha, path) is not None:
            fail(f"released changelog fragment remains in back-sync head: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--develop-tip", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--security-version", default="")
    parser.add_argument("--evidence-id", default="")
    args = parser.parse_args()
    try:
        verify(
            root=args.root.resolve(),
            develop_tip=args.develop_tip,
            release_sha=args.release_sha,
            head_sha=args.head_sha,
            tag=args.tag,
            security_version=args.security_version,
            evidence_id=args.evidence_id,
        )
    except (BackSyncError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
