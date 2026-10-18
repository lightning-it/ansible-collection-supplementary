# Import an already published release baseline

An ordinary personal `litroc` pull request from the same Supplementary repository
may use `reconcile/release-v<VERSION>-to-develop` to import an existing published
Main baseline into Develop. This is a read-only source check, not a Release-App
identity, an ancestry-only exception, review acceptance, or permission to merge.
The protected current-head human Copilot review and all product gates still apply
to the complete PR, including ordinary code changes accompanying the import.

The additional mode of `scripts/verify_release_back_sync.py` requires fetched
`origin/main`, `origin/develop`, and tag `v<VERSION>`: the tag must resolve exactly
to Main, its version must advance Develop, and both protected tips must remain
ancestors. The existing two-parent release and its App-authored preparation,
repository-bound receipt, consumed fragment digests, and exact five published
file modes/blob IDs are checked. Unconsumed Develop fragments must remain byte
identical; new unreleased fragments may be added. The default verifier remains
App-only. No release receipt or generated content is invented by this mode.

The changelog guard runs this proof before label handling. Native events require
the real same-repository personal PR to Develop; offline checks make no native
identity assertion. After merge the existing CI associated-PR read must find
exactly one actual merged same-repository `litroc` PR. It binds the PR base to
the push-before SHA and merge first parent, its head to the second parent, and
the result tree to the reviewed head tree. The current protected Develop ref
must be this merge commit. Only these bound facts enable the same Git proof
against the old Develop baseline; a branch name alone grants no push exception.

Canonical source handoff: the adopted generic guard also exists in
`lightning-it/shared-assets-lit/ansible-collection/base/scripts/devtools-changelog-check.sh`.
The release back-sync verifier is currently Supplementary-owned. Shared changes
must be coordinated separately; repository-local enterprise scripts are preserved
by the existing allowlist-only synchronizer.
