# MLX-90 Exact-Revision Codex review

Release-App pull requests use the protected Exact-Revision Codex exception in MLX-90 §7.2. They do not request or
claim a GitHub Copilot review. Human and external-contributor pull requests remain on their applicable Copilot path;
the Release App cannot use that path as a fallback.

Lightning-IT automation requests a paid Copilot review only for pull requests authored by the exact account
`litroc`. Every other human or external contributor must obtain a valid current-head review under their own
entitlement. The protected gate verifies that evidence but never requests or funds it, and no personal token or
personal provider key enters GitHub Actions.

Local Push-Ready commands never invoke Codex, Copilot, or another external AI service. They build and scan a
history-free exact-patch snapshot deterministically, record zero local AI invocations and
`local_ai_egress=prohibited`, and leave authoritative acceptance to the protected GitHub check. A contributor may
use personal Codex tooling for their own development, but candidate-controlled output is not accepted as a protected
attestation. Until an identity-bound personal-Codex evidence contract is separately governed and implemented, an
external contributor must provide supported current-head evidence under their own entitlement or the gate fails
closed.

## Finalization boundary

The reviewer runs only after the Release App dispatches it with the exact
pull-request number, base ref, base SHA, and head SHA while the workflow itself
executes from that protected base ref. The producer first creates the PR as a
draft, marks the verified PR ready, re-reads the live
author/repository/base/head binding, and only then dispatches the protected Base
controller.

Release-App workflows therefore create pull requests as drafts and mark the
verified draft ready once. Opening, synchronizing, editing, reopening, labeling,
or the ready event itself does not directly start this reviewer.

## Immutable input

The protected base supplies the workflow, materializer, prompt, and JSON schema. The materializer re-reads the live
pull request before and after construction, fetches exact Git objects into an isolated temporary object store, and
binds all of the following values:

- full base and head object IDs;
- the unique merge-base object ID;
- the conflict-free integration-tree object ID;
- SHA-256 and byte count of the complete `git diff --binary --full-index` from the base tree to the integration tree;
- SHA-256 of the protected workflow, materializer, prompt, and JSON schema;
- one canonical complete-input SHA-256 over all immutable metadata and
  protected-asset digests;
- protected workflow object ID, repository, pull-request number, base ref, and
  finalization trigger.

An empty or incomplete input, ambiguous ancestry, merge conflict, changed live binding, or input of 200,000 bytes or
more fails closed. Binary changes are included in the full diff instead of being exempted.

## Reviewer isolation and result

Codex receives a new directory containing only the complete diff, immutable metadata, protected prompt, and
protected schema. It receives no checkout, Git history, repository credentials, or automation token. The pinned
action runs ephemerally with the read-only permission profile and dropped sudo.

The review job's workflow-token permissions are exact and fail-closed:
`actions: read` to verify a reusable producer run, `checks: write` to reserve
and publish the bound result, plus `contents: read` and `pull-requests: read`
for protected controller and live-PR binding. It has no `copilot-requests`,
repository-content write, issue write, administration, workflow write, or
ruleset permission. The separate post-PASS helper receives `actions: write`
only to dispatch the protected verifier's single allowed re-evaluation; it
cannot publish review evidence or invoke an AI reviewer.

Before invoking Codex, the workflow reserves the complete-input hash. A prior
protected PASS for that identical input is reused without another AI call. A
prior failed or incomplete attempt blocks automatic retry. After a new reviewer
run returns, the protected materializer reconstructs and compares the live
input and rehashes every protected asset. Only `PASS` with zero findings and
exact equality of base, head, merge base, integration tree, full-diff SHA-256,
and complete-input SHA-256 creates the neutral `Current revision review` check
on the reviewed head. Failures create no passing check and cannot fall back to
another model, identity, or provider.

During the atomic Ruleset migration only, the same already-verified result also
publishes a temporary `Successful Copilot review` compatibility alias. Its
machine evidence explicitly identifies the actual Codex path; it never causes a
second AI call and is not a claim that Codex was GitHub Copilot. The alias is
removed immediately after the Ruleset requires `Current revision review`.

## Ruleset-bound verifier

The neutral status name is not a trust root by itself. A same-repository
workflow could otherwise request `checks: write` and publish a look-alike
result. The organization Ruleset therefore requires the exact public
`.github/workflows/supplementary-current-revision-required.yml` workflow from
the protected `main` ref of `lightning-it/.github`, targeted only to the
Supplementary repository ID and its protected branches. The workflow checks
its own source repository/ref/SHA and the single result's GitHub Actions App ID,
external ID, evidence JSON, producer run URL, workflow path, event, base SHA,
run attempt, and—on the Release-App path—the exact actor and triggering actor.

The required workflow performs no AI call and never checks out candidate code.
On an intermediate head it fails closed without requesting a review. After a
final protected producer publishes its bound neutral result, a separate
base-owned helper may rerun that one failed verifier attempt exactly once. It
derives the AI producer run only from schema-v4 JSON evidence and the verifier
run only from the verifier reservation's v2 external ID; both custom-check
details URLs remain canonical `/runs/<check-id>` links. The helper cannot
create review evidence, cannot invoke AI, and refuses a second failed retry.
This lets GitHub's default required-workflow events remain the immutable
enforcement root without turning every synchronize event into an AI request.
