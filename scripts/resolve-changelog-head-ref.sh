#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "usage: resolve-changelog-head-ref.sh HEAD_REF" >&2
  exit 2
fi

head_ref="$1"
release_ref_pattern='^(release/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)|backsync/release-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-to-develop)$'
merge_subject_pattern='^Merge pull request #[0-9]+ from [^/]+/(release/v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)|backsync/release-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-to-develop)$'

# Push CI checks out the reviewed merge commit in detached-HEAD mode. Recover
# the reviewed release branch from the GitHub merge subject so the same
# generated-changelog policy applies before and after the PR merge. Local
# push-ready uses a deterministic two-parent synthetic integration commit;
# accept its candidate parent only when exactly one local release ref points
# at that exact object.
if [[ "$head_ref" == HEAD ]]; then
  merge_subject="$(git log -1 --format=%s HEAD)"
  if [[ "$merge_subject" =~ $merge_subject_pattern ]]; then
    head_ref="${BASH_REMATCH[1]}"
  elif [ "$merge_subject" = "Synthetic pull-request integration" ]; then
    read -r -a integration_commit <<<"$(git rev-list --parents -n 1 HEAD)"
    if [ "${#integration_commit[@]}" -eq 3 ]; then
      integration_tree="$(git rev-parse "${integration_commit[0]}^{tree}")"
      candidate_tree="$(git rev-parse "${integration_commit[2]}^{tree}")"
      if [ "$integration_tree" = "$candidate_tree" ]; then
        release_refs=()
        while IFS= read -r release_ref; do
          if [[ "$release_ref" =~ $release_ref_pattern ]]; then
            release_refs+=("$release_ref")
          fi
        done < <(
          git for-each-ref \
            --format="%(refname:short)" \
            --points-at "${integration_commit[2]}" \
            "refs/heads/release/v*" \
            "refs/heads/backsync/release-*"
        )
        if [ "${#release_refs[@]}" -eq 1 ]; then
          head_ref="${release_refs[0]}"
        fi
      fi
    fi
  fi
elif [[ "$head_ref" == release/v* || "$head_ref" == backsync/release-* ]] &&
  [[ ! "$head_ref" =~ $release_ref_pattern ]]; then
  echo "invalid non-canonical release head ref: $head_ref" >&2
  exit 1
fi

printf "%s\n" "$head_ref"
