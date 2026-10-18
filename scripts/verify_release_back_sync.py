from __future__ import annotations

import argparse
import hashlib
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
REPOSITORY = "lightning-it/ansible-collection-supplementary"
IMPORT_BRANCH = re.compile(r"^reconcile/release-v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))-to-develop$")
FRAGMENT_PATH = re.compile(r"^changelogs/fragments/[A-Za-z0-9][A-Za-z0-9._-]*\.ya?ml$")


class BackSyncError(ValueError):
    pass


def fail(message: str) -> NoReturn:
    raise BackSyncError(message)


def git_binary() -> str:
    executable = shutil.which("git")
    if executable is None:
        fail("git unavailable")
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
        fail(f"{label} is not a commit SHA")


def changes(root: Path, base: str, head: str) -> list[tuple[str, str]]:
    raw = git_bytes(root, "diff", "--name-status", "-z", "--no-renames", base, head, "--", ".")
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    if len(fields) % 2:
        fail("malformed diff")
    result: list[tuple[str, str]] = []
    for index in range(0, len(fields), 2):
        try:
            status = fields[index].decode("ascii")
            path = fields[index + 1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BackSyncError("non-UTF-8 back-sync path") from exc
        if status not in {"A", "D", "M", "T"} or not path or path.startswith("/"):
            fail("unsupported path")
        result.append((status, path))
    if not result:
        fail("empty diff")
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
    fail(f"cannot read {revision}:{path}")


def stable_version(value: str, label: str) -> tuple[int, int, int]:
    if SEMVER.fullmatch(value) is None:
        fail(f"{label} is not a stable semantic version")
    return cast("tuple[int, int, int]", tuple(int(part) for part in value.split(".")))


def collection_version(root: Path, revision: str, label: str) -> tuple[int, int, int]:
    raw = object_bytes(root, revision, "galaxy.yml")
    if raw is None:
        fail(f"{label} galaxy.yml is missing")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BackSyncError(f"{label} galaxy.yml is not UTF-8") from exc
    match = re.search(r"(?m)^version:\s*[\"']?([^\s\"']+)", text)
    if match is None:
        fail(f"{label} galaxy.yml has no version")
    return stable_version(match.group(1), f"{label} galaxy.yml version")


def require_same_path(root: Path, release_sha: str, head_sha: str, path: str) -> None:
    if object_bytes(root, release_sha, path) != object_bytes(root, head_sha, path):
        fail(f"back-sync/release mismatch: {path}")


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


def tree_files(root: Path, revision: str, *paths: str) -> dict[str, tuple[str, str]]:
    """Read exact regular-file modes and blob IDs, never follow a Git symlink."""
    result = {}
    for entry in git_bytes(root, "ls-tree", "-rz", revision, "--", *paths).split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        if mode != "100644" or kind != "blob":
            fail(f"published import requires regular non-executable files: {path}")
        result[path] = (mode, blob)
    return result


def unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            fail(f"duplicate release receipt key: {key}")
        result[key] = value
    return result


def verify_published_baseline_import(
    *,
    root: Path,
    develop_tip: str,
    release_sha: str,
    head_sha: str,
    tag: str,
    branch: str,
    check_worktree: bool = False,
    merged_push: bool = False,
) -> None:
    """Prove published bytes only; grant no App, review, or merge authority."""
    if root.is_symlink() or not root.is_dir():
        fail("invalid repository root")
    match = IMPORT_BRANCH.fullmatch(branch)
    if match is None or tag != f"v{match.group(1)}":
        fail("invalid published baseline import branch/tag")
    for value, label in ((develop_tip, "develop tip"), (release_sha, "release SHA"), (head_sha, "import head")):
        require_sha(root, value, label)
    for ref, expected in (
        ("refs/remotes/origin/main", release_sha),
        ("refs/remotes/origin/develop", head_sha if merged_push else develop_tip),
        (f"refs/tags/{tag}", release_sha),
    ):
        if git_text(root, "rev-parse", "--verify", f"{ref}^{{commit}}") != expected:
            fail(f"published import ref mismatch: {ref}")
    if merged_push:
        merge_parents = git_text(root, "show", "-s", "--format=%P", head_sha).split()
        if len(merge_parents) != 2 or merge_parents[0] != develop_tip:
            fail("published import push does not merge the exact previous Develop tip")
        if git_text(root, "rev-parse", f"{head_sha}^{{tree}}") != git_text(
            root, "rev-parse", f"{merge_parents[1]}^{{tree}}"
        ):
            fail("published import push differs from reviewed PR head tree")
    version = stable_version(match.group(1), "import version")
    if collection_version(root, release_sha, "Main") != version:
        fail("Main version differs from import branch")
    if collection_version(root, develop_tip, "Develop") >= version:
        fail("published import must advance the protected Develop version")
    for ancestor in (develop_tip, release_sha):
        if git_text(root, "merge-base", ancestor, head_sha) != ancestor:
            fail("published import lacks protected Main/Develop ancestry")
    parents = git_text(root, "show", "-s", "--format=%P", release_sha).split()
    if len(parents) != 2:
        fail("published Main is not a two-parent release merge")
    # The release preparation is the exact App-authored child of the release
    # base. This validates existing history; it never changes ingress policy.
    if git_text(root, "show", "-s", "--format=%P", parents[1]) != parents[0]:
        fail("published release preparation parent mismatch")
    for field in ("%an <%ae>", "%cn <%ce>"):
        if git_text(root, "show", "-s", f"--format={field}", parents[1]) != APP_IDENTITY:
            fail("published release preparation is not the release App")
    if git_text(root, "show", "-s", "--format=%B", parents[1]) != f"chore(release): prepare {tag}":
        fail("published release preparation message mismatch")
    main_files = tree_files(root, release_sha, *sorted(GENERATED_PATHS))
    if set(main_files) != GENERATED_PATHS:
        fail("published release files are missing")
    for revision in (parents[1], head_sha):
        if tree_files(root, revision, *sorted(GENERATED_PATHS)) != main_files:
            fail("published release file mode/blob mismatch")
    if any(path == "CHANGELOG.md" for _status, path in changes(root, develop_tip, head_sha)):
        fail("unpublished generated changelog path: CHANGELOG.md")
    raw = object_bytes(root, release_sha, "changelogs/release-preparation.json")
    try:
        receipt = json.loads(cast("bytes", raw).decode("utf-8"), object_pairs_hook=unique_json_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BackSyncError("invalid published release receipt") from exc
    if not isinstance(receipt, dict):
        fail("published release receipt must be an object")
    workflow = receipt.get("workflow")
    preparer = receipt.get("preparer")
    expected_workflow = {
        "event": "push",
        "git_ref": "refs/heads/main",
        "path": ".github/workflows/release-prepare.yml",
        "ref": f"{REPOSITORY}/.github/workflows/release-prepare.yml@refs/heads/main",
        "source_sha": parents[0],
        "run_attempt": "1",
    }
    if (
        receipt.get("schema_version") != 2
        or receipt.get("repository") != REPOSITORY
        or receipt.get("repository_id") != "1103407173"
        or receipt.get("base_sha") != parents[0]
        or receipt.get("next_version") != match.group(1)
        or receipt.get("release_mode") != "normal"
        or receipt.get("security") is not None
        or receipt.get("chain_id") is not None
        or not isinstance(workflow, dict)
        or any(workflow.get(key) != value for key, value in expected_workflow.items())
        or not str(workflow.get("run_id", "")).isdigit()
        or preparer
        != {
            "login": "lightning-it-release-automation[bot]",
            "account_id": "307565056",
            "email": "307565056+lightning-it-release-automation[bot]@users.noreply.github.com",
        }
    ):
        fail("foreign or inconsistent published release receipt")
    if (
        stable_version(str(receipt.get("current_version")), "receipt current version")
        != collection_version(root, parents[0], "release base")
        or collection_version(root, parents[0], "release base") >= version
    ):
        fail("published release receipt version mismatch")
    fragments = receipt.get("fragments")
    if not isinstance(fragments, list) or not fragments:
        fail("published release receipt has no consumed fragments")
    consumed: dict[str, tuple[str, str]] = {}
    for fragment in fragments:
        if not isinstance(fragment, dict) or set(fragment) != {"path", "sha256"}:
            fail("invalid consumed fragment receipt")
        path = f"changelogs/fragments/{fragment['path']}"
        if FRAGMENT_PATH.fullmatch(path) is None or path in consumed:
            fail("invalid or duplicate consumed fragment path")
        original = object_bytes(root, parents[0], path)
        if original is None or hashlib.sha256(original).hexdigest() != fragment["sha256"]:
            fail(f"consumed fragment digest mismatch: {path}")
        consumed[path] = tree_files(root, parents[0], path)[path]
    release_changes = changes(root, parents[0], release_sha)
    if {path for status, path in release_changes if status == "D"} != set(consumed) or any(
        path not in GENERATED_PATHS and (status != "D" or path not in consumed) for status, path in release_changes
    ):
        fail("published release diff differs from consumed fragment receipt")
    develop_files = tree_files(root, develop_tip, "changelogs/fragments/")
    head_files = tree_files(root, head_sha, "changelogs/fragments/")
    for path, entry in develop_files.items():
        if path in consumed:
            if entry != consumed[path]:
                fail(f"consumed fragment changed on Develop: {path}")
        elif head_files.get(path) != entry:
            fail(f"unconsumed Develop fragment changed or missing: {path}")
    if set(consumed) & set(head_files):
        fail("consumed release fragment remains in import")
    for path in set(head_files) - set(develop_files):
        if FRAGMENT_PATH.fullmatch(path) is None:
            fail(f"invalid new unreleased fragment: {path}")
    if check_worktree:
        for path in GENERATED_PATHS | set(develop_files) | set(head_files):
            local = root / path
            expected_bytes = object_bytes(root, head_sha, path)
            if any((root / part).is_symlink() for part in (Path(path), *Path(path).parents)) or (
                local.exists() and (not local.is_file() or local.stat().st_mode & 0o111)
            ):
                fail(f"unsafe import working-tree mode: {path}")
            if (local.read_bytes() if local.exists() else None) != expected_bytes:
                fail(f"uncommitted import path differs: {path}")


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
        fail("invalid repository root")
    for value, label in (
        (develop_tip, "develop tip"),
        (release_sha, "release SHA"),
        (head_sha, "back-sync head SHA"),
    ):
        require_sha(root, value, label)
    version = tag.removeprefix("v")
    if tag != f"v{version}" or SEMVER.fullmatch(version) is None:
        fail("invalid release tag")
    if collection_version(root, develop_tip, "develop") > stable_version(version, "release tag"):
        fail("develop already contains a newer release")

    parents = git_text(root, "show", "-s", "--format=%P", head_sha).split()
    if len(parents) == 2 and parents[1] == release_sha:
        develop_base = parents[0]
    elif len(parents) == 1:
        develop_base = parents[0]
        if develop_base != develop_tip:
            fail("tree-state repair is not based on the exact develop tip")
        if (
            subprocess.run(  # noqa: S603 -- exact validated commits.
                [git_binary(), "merge-base", "--is-ancestor", release_sha, develop_base],
                cwd=root,
                check=False,
                env=git_environment(),
                timeout=30,
            ).returncode
            != 0
        ):
            fail("tree-state repair lacks release ancestry")
    else:
        fail("release parent mismatch")
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
        fail("first parent is not an ancestor")
    for field, label in (("%an <%ae>", "author"), ("%cn <%ce>", "committer")):
        if git_text(root, "show", "-s", f"--format={field}", head_sha) != APP_IDENTITY:
            fail(f"{label} is not the release App")
    if git_text(root, "show", "-s", "--format=%B", head_sha) != f"chore: sync {tag} release back to develop":
        fail("message mismatch")

    release_parents = git_text(root, "show", "-s", "--format=%P", release_sha).split()
    if len(release_parents) != 2:
        fail("release is not a two-parent merge")
    released_fragment_changes = changes(root, release_parents[0], release_sha)
    deleted_fragments = {
        path for status, path in released_fragment_changes if status == "D" and path.startswith("changelogs/fragments/")
    }

    allowed = set(GENERATED_PATHS)
    if security_version:
        if security_version != version or EVIDENCE_ID.fullmatch(evidence_id) is None:
            fail("invalid identity")
        metadata = f".lit/security-releases/{version}.json"
        intake = f".lit/security-release-intakes/{version}.json"
        allowed.update({metadata, intake})
        metadata_payload = load_object(root, release_sha, metadata, "Security metadata")
        intake_payload = load_object(root, release_sha, intake, "Security intake receipt")
        if metadata_payload.get("evidenceId") != evidence_id:
            fail("Security metadata evidenceId differs")
        request = intake_payload.get("request")
        if not isinstance(request, dict) or request.get("evidenceId") != evidence_id:
            fail("intake receipt differs")
    elif evidence_id:
        fail("unexpected evidenceId")

    for status, path in changes(root, develop_base, head_sha):
        if path.startswith("changelogs/fragments/"):
            if status != "D" or path not in deleted_fragments:
                fail(f"unauthorized fragment transition: {path}")
        elif path not in allowed:
            fail(f"non-release path: {path}")

    for path in sorted(allowed):
        require_same_path(root, release_sha, head_sha, path)
    for path in deleted_fragments:
        if object_bytes(root, head_sha, path) is not None:
            fail(f"released fragment remains: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--develop-tip", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--security-version", default="")
    parser.add_argument("--evidence-id", default="")
    parser.add_argument("--published-baseline-import", action="store_true")
    parser.add_argument("--branch", default="")
    parser.add_argument("--check-worktree", action="store_true")
    parser.add_argument("--merged-push", action="store_true")
    args = parser.parse_args()
    try:
        if args.published_baseline_import:
            if args.security_version or args.evidence_id:
                fail("published baseline import grants no Security/App exception")
            verify_published_baseline_import(
                root=args.root.resolve(),
                develop_tip=args.develop_tip,
                release_sha=args.release_sha,
                head_sha=args.head_sha,
                tag=args.tag,
                branch=args.branch,
                check_worktree=args.check_worktree,
                merged_push=args.merged_push,
            )
            return 0
        if args.branch or args.check_worktree or args.merged_push:
            fail("import options require --published-baseline-import")
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
