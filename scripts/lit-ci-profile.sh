#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE_NAME="repository-quality"
readonly BASE_REF="refs/remotes/origin/develop"
readonly PRE_COMMIT_VERSION="4.3.0"
readonly PRE_COMMIT_SHA256="f1d50b97e9ca9167aceb76c14e90b07cde8b6789bc199d5005cfd817a718878c"
readonly PRE_COMMIT_URL="https://github.com/pre-commit/pre-commit/releases/download/v${PRE_COMMIT_VERSION}/pre-commit-${PRE_COMMIT_VERSION}.pyz"

fail_closed() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

if [ "$#" -ne 1 ] || [ "$1" != "$PROFILE_NAME" ]; then
  printf 'Usage: %s %s\n' "${0##*/}" "$PROFILE_NAME" >&2
  exit 2
fi

export LC_ALL=C
umask 077

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) fail_closed "repository-quality supports only macOS and Linux hosts" ;;
esac
case "$(uname -m)" in
  x86_64|amd64|arm64|aarch64) ;;
  *) fail_closed "unsupported host architecture: $(uname -m)" ;;
esac

repository_root="$(git rev-parse --show-toplevel 2>/dev/null)" \
  || fail_closed "run the profile from a Git worktree"
repository_root="$(cd "$repository_root" && pwd -P)"
cd "$repository_root"

for required_path in \
  ".pre-commit-config.yaml" \
  ".lit/repository.yml" \
  "scripts/lit-push-ready.py" \
  "scripts/lit-repository-quality.py"
do
  if [ ! -f "$required_path" ] || [ -L "$required_path" ]; then
    fail_closed "required regular profile input is missing: $required_path"
  fi
done

[ -z "$(git status --porcelain=v1 --untracked-files=all)" ] \
  || fail_closed "repository-quality requires a clean committed worktree"
git show-ref --verify --quiet "$BASE_REF" \
  || fail_closed "missing authoritative base ref: $BASE_REF"
merge_base="$(git merge-base "$BASE_REF" HEAD)" \
  || fail_closed "cannot resolve authoritative merge base"
[ -n "$merge_base" ] || fail_closed "authoritative merge base is empty"

fingerprint() {
  {
    git rev-parse HEAD
    git write-tree
    git status --porcelain=v1 --untracked-files=all -z
    git diff --no-ext-diff --no-textconv --binary HEAD --
  } | git hash-object --stdin
}

initial_fingerprint="$(fingerprint)" \
  || fail_closed "cannot fingerprint initial worktree"

printf '==> Run complete repository pre-commit gates\n'
pre_commit_temp_root="${TMPDIR:-/tmp}"
case "$pre_commit_temp_root" in
  /*) ;;
  *) fail_closed "TMPDIR must be an absolute path" ;;
esac
if [ ! -d "$pre_commit_temp_root" ] || [ -L "$pre_commit_temp_root" ]; then
  fail_closed "TMPDIR must be a non-symlink directory"
fi
pre_commit_temp_root="$(cd "$pre_commit_temp_root" && pwd -P)"
pre_commit_venv="$(mktemp -d "${pre_commit_temp_root%/}/lit-pre-commit.XXXXXXXX")" \
  || fail_closed "cannot create the isolated pre-commit environment"
cleanup_pre_commit_venv() {
  trap - EXIT
  case "$pre_commit_venv" in
    "$pre_commit_temp_root"/lit-pre-commit.*) rm -rf -- "$pre_commit_venv" ;;
    *) fail_closed "refusing to remove an unsafe pre-commit environment" ;;
  esac
}
trap cleanup_pre_commit_venv EXIT
pre_commit_zipapp="$pre_commit_venv/pre-commit.pyz"
curl \
  --fail \
  --location \
  --proto '=https' \
  --tlsv1.2 \
  --max-time 300 \
  --retry 3 \
  --retry-all-errors \
  --silent \
  --show-error \
  --output "$pre_commit_zipapp" \
  "$PRE_COMMIT_URL"
actual_sha256="$(
  python3 -c \
    'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' \
    "$pre_commit_zipapp"
)" || fail_closed "cannot hash the pre-commit Zipapp"
[ "$actual_sha256" = "$PRE_COMMIT_SHA256" ] \
  || fail_closed "pre-commit Zipapp checksum mismatch"
mkdir -p "$pre_commit_venv/home"
export PRE_COMMIT_HOME="$pre_commit_venv/home"
BASE_SHA="$merge_base" \
HEAD_SHA="$(git rev-parse HEAD)" \
LABELS_JSON='[]' \
REQUIRE_FRAGMENT=true \
python3 "$pre_commit_zipapp" run --all-files

printf '==> Run supplemental rootless Molecule parity gate\n'
bash scripts/devtools-molecule.sh artifacts-basic

printf '==> Verify Codex and Copilot instruction binding\n'
python3 scripts/lit-push-ready.py instructions

printf '==> Validate committed and local diffs\n'
git diff --check "$merge_base"...HEAD --
git diff --check
git diff --cached --check

final_fingerprint="$(fingerprint)" \
  || fail_closed "cannot fingerprint final worktree"
[ "$initial_fingerprint" = "$final_fingerprint" ] \
  || fail_closed "repository-quality profile changed the Git worktree"

printf 'Repository-quality profile passed.\n'
