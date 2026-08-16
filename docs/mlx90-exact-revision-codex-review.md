# MLX-90 Exact-Revision Codex review

Release-App pull requests use the protected Exact-Revision Codex exception in MLX-90 §7.2. They do not request or
claim a GitHub Copilot review. Human and external-contributor pull requests remain on their applicable Copilot path;
the Release App cannot use that path as a fallback.

Lightning-IT automation requests a paid Copilot review only for pull requests authored by the exact account
`litroc`. Every other human or external contributor must obtain a valid current-head review under their own
entitlement. The protected gate verifies that evidence but never requests or funds it, and no personal token or
personal provider key enters GitHub Actions.

## Finalization boundary

The review workflow runs only for one of these protected finalization events:

1. a same-repository pull request authored by `lightning-it-release-automation[bot]` changes from draft to ready; or
2. that App dispatches the workflow with the exact pull-request number, base ref, base SHA, and head SHA while the
   workflow itself executes from the protected base ref.

Release-App workflows therefore create pull requests as drafts, re-read the live author, repository, base, and head,
and mark the verified draft ready once. Opening, synchronizing, editing, reopening, or labeling a pull request does
not start this reviewer.

## Immutable input

The protected base supplies the workflow, materializer, prompt, and JSON schema. The materializer re-reads the live
pull request before and after construction, fetches exact Git objects into an isolated temporary object store, and
binds all of the following values:

- full base and head object IDs;
- the unique merge-base object ID;
- the conflict-free integration-tree object ID;
- SHA-256 and byte count of the complete `git diff --binary --full-index` from the base tree to the integration tree;
- protected workflow object ID, repository, pull-request number, base ref, and finalization trigger.

An empty or incomplete input, ambiguous ancestry, merge conflict, changed live binding, or input of 200,000 bytes or
more fails closed. Binary changes are included in the full diff instead of being exempted.

## Reviewer isolation and result

Codex receives a new directory containing only the complete diff, immutable metadata, protected prompt, and
protected schema. It receives no checkout, Git history, repository credentials, or automation token. The pinned
action runs ephemerally with the read-only permission profile and dropped sudo.

After the reviewer returns, the protected materializer reconstructs and compares the live input again. Only `PASS`
with zero findings and exact equality of base, head, merge base, integration tree, and full-diff SHA-256 creates the
neutral `Current revision review` check on the reviewed head. Failures create no passing check and cannot fall back to
another model, identity, or provider.

The legacy `Successful Copilot review` job remains temporarily for non-Release-App pull requests while the protected
ruleset is migrated to the neutral context. It is never emitted by the Exact-Revision Codex workflow and is not
evidence that Codex was GitHub Copilot.
