#!/usr/bin/env bash
set -euo pipefail

# Emit a release version only for a protected merge commit that is bound to the
# release-automation preparation commit and its generated preparation record.
# A human-controlled merge title is intentionally insufficient evidence.

readonly RELEASE_BOT_EMAIL='307565056+lightning-it-release-automation[bot]@users.noreply.github.com'
readonly RELEASE_BOT_NAME='lightning-it-release-automation[bot]'
readonly RELEASE_REPOSITORY='lightning-it/ansible-collection-supplementary'
readonly RELEASE_REPOSITORY_ID='1103407173'
HELPER_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly HELPER_ROOT

fail_closed() {
  exit 1
}

mapfile -t merge_parents < <(git show -s --format=%P HEAD | tr ' ' '\n')
if [ "${#merge_parents[@]}" -ne 2 ]; then
  fail_closed
fi

release_base="${merge_parents[0]:-}"
release_parent="${merge_parents[1]:-}"
if [ -z "${release_base}" ] || [ -z "${release_parent}" ]; then
  fail_closed
fi
if [ -L galaxy.yml ] || [ -L changelogs/release-preparation.json ]; then
  fail_closed
fi
if [ ! -f galaxy.yml ] || [ ! -f changelogs/release-preparation.json ]; then
  fail_closed
fi

release_version="$(awk '/^version:/ { print $2; exit }' galaxy.yml)"
[[ "${release_version:-}" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || fail_closed

parent_version="$(git show "${release_parent}:galaxy.yml" 2>/dev/null | awk '/^version:/ { print $2; exit }' || true)"
parent_subject="$(git show -s --format=%s "${release_parent}")"
parent_author="$(git show -s --format='%an <%ae>' "${release_parent}")"
parent_committer="$(git show -s --format='%cn <%ce>' "${release_parent}")"
parent_parent="$(git show -s --format=%P "${release_parent}")"

[ "${parent_parent}" = "${release_base}" ] || fail_closed
[ "${parent_subject}" = "chore(release): prepare v${release_version}" ] || fail_closed
[ "${parent_author}" = "${RELEASE_BOT_NAME} <${RELEASE_BOT_EMAIL}>" ] || fail_closed
[ "${parent_committer}" = "${RELEASE_BOT_NAME} <${RELEASE_BOT_EMAIL}>" ] || fail_closed
[ "${parent_version}" = "${release_version}" ] || fail_closed
git diff --quiet "${release_base}" "${release_parent}" -- galaxy.yml changelogs/release-preparation.json && fail_closed
git diff --quiet "${release_parent}" HEAD -- . || fail_closed
python3 "${HELPER_ROOT}/scripts/release-version.py" \
  --verify-preparation-receipt changelogs/release-preparation.json \
  --repository "${RELEASE_REPOSITORY}" \
  --repository-id "${RELEASE_REPOSITORY_ID}" \
  --base-sha "${release_base}" \
  --expected-version "${release_version}" \
  --root . >/dev/null || fail_closed

printf '%s\n' "${release_version}"
