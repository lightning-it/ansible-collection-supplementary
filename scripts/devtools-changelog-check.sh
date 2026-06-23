#!/usr/bin/env bash
set -euo pipefail

# Run the same changelog policy used by GitHub PR checks inside the devtools
# container. In GitHub, BASE_SHA/HEAD_SHA come from the PR event. Locally, the
# script compares the current branch with origin/develop when possible and adds
# staged changes so pre-commit can catch missing fragments before commit.

bash scripts/wunder-devtools-ee.sh bash -lc '
  set -euo pipefail

  cd /workspace
  git config --global --add safe.directory /workspace >/dev/null 2>&1 || true

  antsibull-changelog lint

  diff_names() {
    git diff --name-only "$@" 2>/dev/null || true
  }

  changed=""
  if [ -n "${BASE_SHA:-}" ] && [ -n "${HEAD_SHA:-}" ]; then
    changed="$(diff_names "$BASE_SHA" "$HEAD_SHA")"
  elif [ -n "${PRE_COMMIT_FROM_REF:-}" ] && [ -n "${PRE_COMMIT_TO_REF:-}" ]; then
    changed="$(diff_names "$PRE_COMMIT_FROM_REF" "$PRE_COMMIT_TO_REF")"
  else
    base_ref="${CHANGELOG_BASE_REF:-origin/develop}"
    if git rev-parse --verify "$base_ref" >/dev/null 2>&1; then
      merge_base="$(git merge-base "$base_ref" HEAD 2>/dev/null || true)"
      if [ -n "${merge_base:-}" ]; then
        changed="$(diff_names "$merge_base" HEAD)"
      fi
    fi

    staged="$(diff_names --cached)"
    unstaged="$(diff_names)"
    changed="$(printf "%s\n%s\n%s\n" "$changed" "$staged" "$unstaged" | sed "/^$/d" | sort -u)"
  fi

  changed="$(printf "%s\n" "$changed" | sed "/^$/d" | sort -u)"
  if [ -z "$changed" ]; then
    echo "No changed files detected for changelog policy."
    exit 0
  fi

  echo "$changed"

  labels="$(jq -r ".[]" <<<"${LABELS_JSON:-[]}")"
  has_label() {
    grep -Fxq "$1" <<<"$labels"
  }

  if has_label skip-changelog || has_label documentation || has_label ci || has_label tests; then
    echo "Changelog fragment requirement skipped by PR label."
    exit 0
  fi

  generated_re="^(CHANGELOG\\.(md|rst)|changelogs/(changelog|\\.plugin-cache)\\.yaml)$"
  is_release_branch=false
  is_release_promotion=false
  head_ref="${GITHUB_HEAD_REF:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)}"
  base_ref="${GITHUB_BASE_REF:-}"

  if [[ "$head_ref" == release/v* || "$head_ref" == backsync/release-* ]]; then
    is_release_branch=true
  fi
  if [[ "$head_ref" == develop && "$base_ref" == main ]]; then
    is_release_promotion=true
  fi

  if grep -E "$generated_re" <<<"$changed"; then
    if [ "$is_release_branch" != "true" ] && [ "$is_release_promotion" != "true" ]; then
      echo "::error::Generated changelog files may only be changed by release/vX.Y.Z or release back-sync PRs."
      exit 1
    fi
  fi

  if [ "$is_release_branch" = "true" ]; then
    echo "Release and release back-sync PRs manage generated changelog files."
    exit 0
  fi

  if [ "${REQUIRE_FRAGMENT:-true}" != "true" ]; then
    exit 0
  fi

  non_user_visible_re="^(\\.github/|\\.releaserc|\\.pre-commit-config\\.yaml|\\.ansible-lint|"
  non_user_visible_re+="\\.yamllint|renovate|README\\.md|docs/|molecule/|tests/|scripts/|"
  non_user_visible_re+="CHANGELOG\\.(md|rst)|changelogs/config\\.yaml|"
  non_user_visible_re+="changelogs/changelog\\.yaml|changelogs/fragments/|"
  non_user_visible_re+="package(-lock)?\\.json|AGENTS\\.md|CONTRIBUTING\\.md|SECURITY\\.md)"
  user_visible="$(grep -Ev "$non_user_visible_re" <<<"$changed" || true)"

  if [ "$is_release_promotion" = "true" ]; then
    promotion_metadata_re="^(galaxy\\.yml|CHANGELOG\\.(md|rst)|"
    promotion_metadata_re+="changelogs/(changelog|\\.plugin-cache)\\.yaml)$"
    user_visible="$(grep -Ev "$non_user_visible_re|$promotion_metadata_re" <<<"$changed" || true)"
  fi

  if [ -z "$user_visible" ]; then
    echo "Only documentation, CI, tests, metadata, or changelog files changed."
    exit 0
  fi

  if ! grep -Eq "^changelogs/fragments/[^/]+\\.ya?ml$" <<<"$changed"; then
    echo "::error::User-visible collection changes require a changelog fragment under changelogs/fragments/."
    exit 1
  fi
'
