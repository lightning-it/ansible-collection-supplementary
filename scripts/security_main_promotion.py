from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, cast

sys.path.insert(0, str(Path(__file__).resolve().parent))

import security_release_contract as CONTRACT  # noqa: E402

SHA = re.compile(r"^[0-9a-f]{40}$")
SECURITY_BRANCH = re.compile(r"^security-release/(MLX90-[A-Z0-9][A-Z0-9._-]{2,127})$")
RELEASE_BRANCH = re.compile(r"^release/v((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))$")
INTAKE_RECEIPT = re.compile(
    r"^\.lit/security-release-intakes/((?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\.json$"
)
PREPARATION_RECEIPT = Path("changelogs/release-preparation.json")
RELEASE_GENERATED_PATHS = {
    "CHANGELOG.rst",
    "changelogs/.plugin-cache.yaml",
    "changelogs/changelog.yaml",
    PREPARATION_RECEIPT.as_posix(),
    "galaxy.yml",
}


class PromotionError(ValueError):
    pass


@dataclass(frozen=True)
class Promotion:
    mode: str
    head_ref: str
    head_sha: str
    chain_id: str | None = None
    evidence_id: str | None = None
    version: str | None = None


def fail(message: str) -> NoReturn:
    raise PromotionError(message)


def git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_WORK_TREE"):
        environment.pop(variable, None)
    return environment


def git_binary() -> str:
    executable = shutil.which("git")
    if executable is None:
        fail("git unavailable")
    return executable


def run_git(root: Path, *args: str, text: bool = False) -> bytes | str:
    try:
        result = subprocess.run(  # noqa: S603 -- all revisions are exact validated SHAs.
            [git_binary(), *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=text,
            env=git_environment(),
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode("utf-8", errors="replace")
        raise PromotionError(f"git {' '.join(args)} failed: {stderr.strip()}") from exc
    return cast("bytes | str", result.stdout)


def git_text(root: Path, *args: str) -> str:
    value = run_git(root, *args, text=True)
    assert isinstance(value, str)
    return value.strip()


def git_bytes(root: Path, *args: str) -> bytes:
    value = run_git(root, *args)
    assert isinstance(value, bytes)
    return value


def require_checkout(root: Path, expected_sha: str, label: str) -> None:
    if root.is_symlink() or not root.is_dir():
        fail(f"{label} checkout invalid")
    if SHA.fullmatch(expected_sha) is None:
        fail(f"{label} SHA is invalid")
    if git_text(root, "rev-parse", "HEAD") != expected_sha:
        fail(f"{label} checkout mismatch")
    if git_text(root, "cat-file", "-t", expected_sha) != "commit":
        fail(f"{label} is not a commit")


def require_app_commit(head_root: Path, base_sha: str, head_sha: str, message: str) -> None:
    parents = git_text(head_root, "show", "-s", "--format=%P", head_sha).split()
    if parents != [base_sha]:
        fail("parent mismatch")
    expected_identity = f"{CONTRACT.RELEASE_APP_LOGIN} <{CONTRACT.RELEASE_APP_EMAIL}>"
    for field, label in (("%an <%ae>", "author"), ("%cn <%ce>", "committer")):
        if git_text(head_root, "show", "-s", f"--format={field}", head_sha) != expected_identity:
            fail(f"{label} is not the release App")
    if git_text(head_root, "show", "-s", "--format=%B", head_sha) != message:
        fail("message mismatch")


def changed_paths(root: Path, base_sha: str, head_sha: str) -> list[tuple[str, str]]:
    raw = git_bytes(
        root,
        "diff",
        "--name-status",
        "-z",
        "--no-renames",
        base_sha,
        head_sha,
        "--",
        ".",
    )
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
            raise PromotionError("non-UTF-8 promotion path") from exc
        if status not in {"A", "D", "M", "T"} or not path or path.startswith("/"):
            fail("unsupported path")
        result.append((status, path))
    if not result:
        fail("empty diff")
    return result


def candidate_diff_without_receipt(
    root: Path,
    base_sha: str,
    head_sha: str,
    receipt_path: str,
) -> bytes:
    value = git_bytes(
        root,
        "-c",
        "core.safecrlf=false",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "diff.renames=false",
        "-c",
        "diff.algorithm=myers",
        "-c",
        "diff.indentHeuristic=false",
        "diff",
        "--binary",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--diff-algorithm=myers",
        "--no-indent-heuristic",
        "--unified=3",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        base_sha,
        head_sha,
        "--",
        ".",
        f":(exclude){receipt_path}",
    )
    if not value:
        fail("candidate diff empty")
    return value


def load_release_version_module(base_root: Path) -> ModuleType:
    path = base_root / "scripts" / "release-version.py"
    if path.is_symlink() or not path.is_file():
        fail("policy unavailable")
    spec = importlib.util.spec_from_file_location("mlx90_release_version", path)
    if spec is None or spec.loader is None:
        fail("invalid policy")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_canonical_document(
    root: Path,
    relative_path: Path,
    label: str,
) -> dict[str, Any]:
    raw = CONTRACT.read_bounded_regular_file(
        root,
        relative_path,
        label,
        CONTRACT.MAX_JSON_BYTES,
    )
    payload = CONTRACT.load_json_bytes(raw, label)
    if raw != CONTRACT.canonical_document_bytes(payload):
        fail(f"{label} not canonical")
    return payload


def verify_intake_promotion(
    base_root: Path,
    head_root: Path,
    base_sha: str,
    head_sha: str,
    head_ref: str,
    checked_at: datetime,
) -> Promotion:
    match = SECURITY_BRANCH.fullmatch(head_ref)
    if match is None:
        fail("Security intake branch malformed")
    changes = changed_paths(head_root, base_sha, head_sha)
    receipts = [
        (status, path, INTAKE_RECEIPT.fullmatch(path))
        for status, path in changes
        if INTAKE_RECEIPT.fullmatch(path) is not None
    ]
    if len(receipts) != 1 or receipts[0][0] != "A" or receipts[0][2] is None:
        fail("receipt count mismatch")
    receipt_path = receipts[0][1]
    receipt = load_canonical_document(
        head_root,
        Path(receipt_path),
        "Security intake receipt",
    )
    try:
        CONTRACT.verify_intake_receipt(receipt, checked_at=checked_at)
    except CONTRACT.ContractError as exc:
        raise PromotionError(str(exc)) from exc
    request = receipt["request"]
    verified = receipt["verified"]
    if (
        request["baseSha"] != base_sha
        or request["candidateBaseSha"] != base_sha
        or verified["baseSha"] != base_sha
        or request["evidenceId"] != match.group(1)
        or verified["evidenceId"] != match.group(1)
        or verified["branch"] != head_ref
        or request["fixedVersion"] != receipts[0][2].group(1)
    ):
        fail("branch/base mismatch")
    CONTRACT.validate_request(request, CONTRACT.PRODUCER_REPOSITORY, checked_at)
    non_receipt_paths = sorted(path for _status, path in changes if path != receipt_path)
    if non_receipt_paths != verified["changedPaths"]:
        fail("paths differ from the verified candidate")
    materialized = candidate_diff_without_receipt(head_root, base_sha, head_sha, receipt_path)
    if CONTRACT.sha256_bytes(materialized) != request["candidateDiffSha256"]:
        fail("diff mismatch")
    require_app_commit(
        head_root,
        base_sha,
        head_sha,
        f"fix(security): {request['evidenceId']}",
    )
    return Promotion(
        mode="security",
        head_ref=head_ref,
        head_sha=head_sha,
        chain_id=request["chainId"],
        evidence_id=request["evidenceId"],
        version=request["fixedVersion"],
    )


def galaxy_version(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        fail("galaxy.yml invalid")
    matches: list[str] = re.findall(
        r"(?m)^version:\s*[\"']?([^\s\"']+)[\"']?\s*$",
        path.read_text(encoding="utf-8"),
    )
    if len(matches) != 1:
        fail("ambiguous galaxy version")
    return matches[0]


def verify_release_promotion(
    base_root: Path,
    head_root: Path,
    base_sha: str,
    head_sha: str,
    head_ref: str,
    checked_at: datetime,
) -> Promotion:
    match = RELEASE_BRANCH.fullmatch(head_ref)
    if match is None:
        fail("branch malformed")
    version = match.group(1)
    receipt = load_canonical_document(
        head_root,
        PREPARATION_RECEIPT,
        "release preparation receipt",
    )
    module = load_release_version_module(base_root)
    try:
        module.verify_preparation_receipt(
            receipt,
            expected_repository=CONTRACT.PRODUCER_REPOSITORY,
            expected_repository_id=CONTRACT.PRODUCER_REPOSITORY_ID,
            expected_base_sha=base_sha,
            expected_version=version,
            root=base_root,
            checked_at=checked_at,
        )
    except (ValueError, CONTRACT.ContractError) as exc:
        raise PromotionError(str(exc)) from exc
    mode = receipt.get("release_mode")
    if mode not in {"normal", "security"}:
        fail("unsupported mode")
    if galaxy_version(head_root / "galaxy.yml") != version:
        fail("branch/version mismatch")

    changes = changed_paths(head_root, base_sha, head_sha)
    changed = {path: status for status, path in changes}
    if PREPARATION_RECEIPT.as_posix() not in changed or "galaxy.yml" not in changed:
        fail("generated state missing")
    fragment_paths = {
        f"changelogs/fragments/{fragment['path']}"
        for fragment in receipt.get("fragments", [])
        if isinstance(fragment, dict) and isinstance(fragment.get("path"), str)
    }
    allowed = RELEASE_GENERATED_PATHS | fragment_paths
    unexpected = sorted(set(changed) - allowed)
    if unexpected:
        fail(f"non-generated release paths: {unexpected}")
    if any(changed.get(path) != "D" for path in fragment_paths):
        fail("fragments not consumed")
    if any(path.startswith(".lit/security-") for path in changed):
        fail("Security bindings changed")
    require_app_commit(
        head_root,
        base_sha,
        head_sha,
        f"chore(release): prepare v{version}",
    )
    if mode == "normal":
        if receipt.get("chain_id") is not None or receipt.get("security") is not None:
            fail("partial Security binding")
        return Promotion(mode="normal", head_ref=head_ref, head_sha=head_sha, version=version)
    security = receipt.get("security")
    if not isinstance(security, dict):
        fail("Security binding missing")
    return Promotion(
        mode="security",
        head_ref=head_ref,
        head_sha=head_sha,
        chain_id=receipt.get("chain_id"),
        evidence_id=security.get("evidence_id"),
        version=version,
    )


def verify_promotion(
    *,
    base_root: Path,
    head_root: Path,
    base_sha: str,
    head_sha: str,
    head_ref: str,
    checked_at: datetime | None = None,
) -> Promotion:
    checked_at = checked_at or datetime.now(UTC)
    require_checkout(base_root, base_sha, "protected-main base")
    require_checkout(head_root, head_sha, "promotion head")
    if SECURITY_BRANCH.fullmatch(head_ref) is not None or head_ref.startswith("security-release/"):
        return verify_intake_promotion(
            base_root,
            head_root,
            base_sha,
            head_sha,
            head_ref,
            checked_at,
        )
    if RELEASE_BRANCH.fullmatch(head_ref) is not None or head_ref.startswith("release/"):
        return verify_release_promotion(
            base_root,
            head_root,
            base_sha,
            head_sha,
            head_ref,
            checked_at,
        )
    fail("unsupported head")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--head-root", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--checked-at", default="")
    args = parser.parse_args()
    try:
        checked_at = CONTRACT.timestamp(args.checked_at, "--checked-at") if args.checked_at else datetime.now(UTC)
        result = verify_promotion(
            base_root=args.base_root.resolve(),
            head_root=args.head_root.resolve(),
            base_sha=args.base_sha,
            head_sha=args.head_sha,
            head_ref=args.head_ref,
            checked_at=checked_at,
        )
    except (PromotionError, CONTRACT.ContractError, OSError, UnicodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result.__dict__, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
