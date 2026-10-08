#!/usr/bin/env bash
# Re-prove the exact Collection CI producer immediately before consuming or publishing its artifacts.
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo 'usage: verify-release-ci-run.sh <release-sha> <ci-run-id> <ci-run-attempt>' >&2
  exit 2
fi
release_sha="$1"
ci_run_id="$2"
ci_run_attempt="$3"
[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$ci_run_id" =~ ^[1-9][0-9]*$ ]]
[[ "$ci_run_attempt" =~ ^[1-9][0-9]*$ ]]
test -n "${GH_TOKEN:-}"
test -n "${GITHUB_REPOSITORY:-}"

runs="$(
  gh api --method GET \
    "repos/${GITHUB_REPOSITORY}/actions/workflows/collection-ci.yml/runs" \
    -f branch=main -f event=push -f head_sha="$release_sha" -f per_page=100
)"
jq -e --arg sha "$release_sha" --arg id "$ci_run_id" --arg attempt "$ci_run_attempt" '
  [.workflow_runs[] | select(
    .event == "push" and .head_branch == "main" and .head_sha == $sha
  )] as $matches |
  .total_count == 1 and ($matches | length) == 1 and
  ($matches[0].id | tostring) == $id and
  ($matches[0].run_attempt | tostring) == $attempt
' <<< "$runs" >/dev/null

run="$(gh api --method GET "repos/${GITHUB_REPOSITORY}/actions/runs/${ci_run_id}")"
jq -e --arg sha "$release_sha" --arg id "$ci_run_id" --arg attempt "$ci_run_attempt" '
  (.id | tostring) == $id and (.run_attempt | tostring) == $attempt and
  .event == "push" and .head_branch == "main" and .head_sha == $sha and
  .status == "completed" and .conclusion == "success"
' <<< "$run" >/dev/null

jobs="$(
  gh api --method GET --paginate --slurp \
    "repos/${GITHUB_REPOSITORY}/actions/runs/${ci_run_id}/jobs" \
    -f filter=all -f per_page=100
)"
jq -e --arg attempt "$ci_run_attempt" '
  [.[].jobs[] | select(
    .name == "Collection / Release Validation" and
    (.run_attempt | tostring) == $attempt and
    .status == "completed" and .conclusion == "success"
  )] | length == 1
' <<< "$jobs" >/dev/null
