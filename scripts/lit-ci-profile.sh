#!/usr/bin/env bash
set -euo pipefail

readonly PROFILE_NAME="repository-quality"
readonly BASE_REF="refs/remotes/origin/develop"

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
pre_commit_venv="$TMPDIR/lit-pre-commit"
python3 -m venv "$pre_commit_venv"
"$pre_commit_venv/bin/pip" install --disable-pip-version-check --quiet pre-commit==4.3.0
BASE_SHA="$merge_base" \
HEAD_SHA="$(git rev-parse HEAD)" \
LABELS_JSON='[]' \
REQUIRE_FRAGMENT=true \
"$pre_commit_venv/bin/pre-commit" run --all-files

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
