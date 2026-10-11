#!/usr/bin/env bash
# Protected launcher only: all validation executes in pinned Devtools.
set -euo pipefail
umask 077
retry_ref="${WORKFLOW_REF:-${GITHUB_WORKFLOW_REF}}"
retry_sha="${WORKFLOW_SHA:-${GITHUB_WORKFLOW_SHA}}"
[[ "$retry_sha" =~ ^[0-9a-f]{40}$ ]]
[[ "$retry_ref" =~ ^(lightning-it/(\.github|shared-assets-lit|ansible-collection-supplementary))/\.github/workflows/(current-revision-rerun|supplementary-current-revision-required)\.yml@refs/heads/(develop|main)$ ]]
retry_repository="${BASH_REMATCH[1]}"
retry_directory="$(mktemp -d "${RUNNER_TEMP}/li259.XXXXXX")"
trap 'rm -rf -- "$retry_directory"' EXIT
for retry_module in native_verifier_retry.py review_request_continuation.py; do
  retry_response="$(gh api "repos/${retry_repository}/contents/scripts/${retry_module}?ref=${retry_sha}")"
  jq -er --arg path "scripts/${retry_module}" '
    select(.type == "file" and .path == $path and .encoding == "base64"
      and (.size | type == "number" and . > 0 and . <= 200000)) | .content
    ' <<<"$retry_response" | base64 --decode >"${retry_directory}/${retry_module}"
  test "$(git hash-object "${retry_directory}/${retry_module}")" = \
    "$(jq -er '.sha | select(test("^[0-9a-f]{40}$"))' <<<"$retry_response")"
done
docker run --rm --read-only --network bridge \
  --cap-drop ALL --security-opt no-new-privileges=true \
  --pids-limit 128 --user "$(id -u):$(id -g)" \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
  -e GH_TOKEN -e GITHUB_REPOSITORY -e GITHUB_REPOSITORY_ID \
  -e GITHUB_RUN_ID -e GITHUB_RUN_ATTEMPT -e GITHUB_EVENT_NAME \
  -e GITHUB_REF_PROTECTED -e GITHUB_WORKFLOW_SHA \
  -e LI219_EVENT_MODE -e LI259_INFRA_RETRY \
  -e WORKFLOW_REF -e WORKFLOW_SHA -e EVENT_BASE -e EVENT_HEAD -e PR_NUMBER \
  -e PYTHONDONTWRITEBYTECODE=1 -e HOME=/tmp \
  -v "${retry_directory}:/proof:ro" -w /proof \
  quay.io/l-it/ee-wunder-devtools-ubi9:v1.16.1@sha256:c5e8707e825fcddb3e7bbc7592ebdc99a02e6ba9fa2cad71b88bcd5c71bd4d08 \
  python3 native_verifier_retry.py "$@"
