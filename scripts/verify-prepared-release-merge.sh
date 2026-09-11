#!/usr/bin/env bash
set -euo pipefail

# Emit a release version only for a protected merge commit that is bound to the
# release-automation preparation commit and its generated preparation record.
# A human-controlled merge title is intentionally insufficient evidence.

readonly RELEASE_BOT_EMAIL='307565056+lightning-it-release-automation[bot]@users.noreply.github.com'
readonly RELEASE_BOT_LOGIN='lightning-it-release-automation[bot]'

fail_closed() {
  exit 1
}

mapfile -t merge_parents < <(git show -s --format=%P HEAD)
if [ "${#merge_parents[@]}" -ne 1 ]; then
  fail_closed
fi

read -r release_base release_parent <<<"${merge_parents[0]}"
if [ -z "${release_base:-}" ] || [ -z "${release_parent:-}" ]; then
  fail_closed
fi
if [ ! -f galaxy.yml ] || [ ! -f changelogs/release-preparation.json ]; then
  fail_closed
fi

release_version="$(sed -nE 's/^version:[[:space:]]*([^[:space:]]+)[[:space:]]*$/\\1/p' galaxy.yml | head -n 1)"
release_version="$(awk '/^version:/ { print $2; exit }' galaxy.yml)"
[[ "${release_version:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail_closed

parent_version="$(git show "${release_parent}:galaxy.yml" 2>/dev/null | sed -nE 's/^version:[[:space:]]*([^[:space:]]+)[[:space:]]*$/\\1/p' | head -n 1 || true)"
parent_version="$(git show "${release_parent}:galaxy.yml" 2>/dev/null | awk '/^version:/ { print $2; exit }' || true)"
parent_subject="$(git show -s --format=%s "${release_parent}")"
parent_email="$(git show -s --format=%ae "${release_parent}")"
parent_parent="$(git show -s --format=%P "${release_parent}")"
merge_subject="$(git show -s --format=%s HEAD)"
prepared_base="$(jq -r '.base_sha // empty' changelogs/release-preparation.json)"
prepared_version="$(jq -r '.next_version // empty' changelogs/release-preparation.json)"
prepared_by="$(jq -r '.preparer.login // empty' changelogs/release-preparation.json)"

[ "${parent_parent}" = "${release_base}" ] || fail_closed
[ "${merge_subject}" = "Release v${release_version}" ] || fail_closed
[ "${parent_subject}" = "chore(release): prepare v${release_version}" ] || fail_closed
[ "${parent_email}" = "${RELEASE_BOT_EMAIL}" ] || fail_closed
[ "${prepared_by}" = "${RELEASE_BOT_LOGIN}" ] || fail_closed
[ "${prepared_base}" = "${release_base}" ] || fail_closed
[ "${prepared_version}" = "${release_version}" ] || fail_closed
[ "${parent_version}" = "${release_version}" ] || fail_closed
git diff --quiet "${release_base}" "${release_parent}" -- galaxy.yml changelogs/release-preparation.json && fail_closed

printf '%s\n' "${release_version}"
