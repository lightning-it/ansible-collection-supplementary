# MLX-90 push-ready optimization pilot

This document defines the Supplementary-first performance pilot. It does not
weaken the exact-head, external-review, secret-isolation, or protected GitHub
gate contracts. The implementation remains repository-local until a fresh
pilot is accepted and then becomes eligible for canonicalization in
`lightning-it/shared-assets-lit`.

## Measured baseline contract

The baseline is captured on the final unchanged foundation head with the
sequential v2 engine before enabling this optimization. Preserve the resulting
local evidence metadata and the linked GitHub runs. Record only hashes,
timestamps, durations, sizes, counters, versions, and URLs; never retain the
private review patch or reviewer credentials.

The reproducible measurement is:

```shell
python3 scripts/lit-push-ready.py push-ready
python3 scripts/lit-push-ready.py verify
```

The single repository-quality check has a 3600-second fail-closed timeout. This
budget covers the complete isolated pre-commit suite plus the supplemental
rootless Molecule parity scenario; it does not skip, shorten, or make either
gate optional. Exceeding the budget still stops evidence creation and prevents
the governed push.

The evidence records total duration, review bytes, executed and repeated
checks, cache hits and misses, and explicit local external-review invocation
counts split between Codex and Copilot. Both invocation counts and all local AI
timings MUST remain zero. `local_ai_egress=prohibited` is a verified invariant,
not an optional optimization.
The server-side baseline additionally records the Current-Head Copilot gate,
Collection CI, and final end-to-end workflow durations for the exact SHA.

### Immutable PR #667 server baseline

The GitHub baseline is [Supplementary PR #667](https://github.com/lightning-it/ansible-collection-supplementary/pull/667),
final head `f6102f681c9cc2a56090910e485b242a1c5da6c9`, merged normally as
`7eb8a9e04574650bb4736324bf647ab522e1dc33` at
`2026-08-11T22:24:58Z`. GitHub records 12 Copilot review submissions bound
to 11 distinct PR heads. This is the pre-pilot server-side cost proxy; the
accepted standard-profile pilot must normally produce one Copilot submission
for its one finalized head.

For the final #667 head, the
[Copilot gate run](https://github.com/lightning-it/ansible-collection-supplementary/actions/runs/31541388637)
started its request job at `2026-08-11T22:12:19Z`; the successful exact-head
gate ran from `22:12:26Z` through `22:19:15Z` (409 seconds). The protected
[Collection CI run](https://github.com/lightning-it/ansible-collection-supplementary/actions/runs/31541389122)
ran its final-head gates from `22:13:31Z` through `22:24:55Z` (684 seconds).
The final request-to-normal-merge interval was 759 seconds. Preserve these
absolute timestamps, run IDs, head and merge SHA when comparing the live pilot;
do not substitute total PR age or an unbound average.

## Local deterministic boundary

Push-Ready creates one private temporary repository containing a history-free
synthetic root commit, validates the exact integration tree, scans the snapshot
for unsafe paths and secret-like content, and then destroys the workspace. It
does not submit the snapshot or diff to Codex, Copilot, or another external AI
reviewer. Enabling either dormant local agent configuration, adding an agent to
a review profile, or injecting local AI evidence stops fail closed.

The protected `Current revision review` check on GitHub and every other
protected repository gate remain required after the normal feature-branch push.

## Risk profiles and trusted classification

The base branch owns the only trusted classifier. Known collection code, role,
test, Molecule, changelog, and documentation paths use the `standard` profile.
Engine, policy, workflow, authorization, release, promotion, acceptance,
validator, and otherwise unknown paths use the `trust-root` profile. Both
profiles execute the same deterministic no-AI local boundary; the classification
remains evidence for risk handling and protected server policy. A missing,
malformed, or pre-profile base policy falls back to `trust-root`. Editing the
classifier or either profile therefore classifies itself as `trust-root`.

The standard path allowlist is necessary but not sufficient. The trusted base
policy also scans path components and the exact final diff for its sorted
security-risk vocabulary. Authentication, authorization, AAP, CaC, Keycloak,
Vault, TLS, credentials, permissions, policies, release/promotion/acceptance,
signatures, secrets, tokens, Rulesets, and branch-protection changes therefore
remain `trust-root` even when their files live below an otherwise standard
role, test, Molecule, or documentation prefix. Unknown or malformed risk
classification remains fail-closed.

Evidence binds the profile, its trusted base-policy digest, the authoritative
base tip, merge-base, exact head, integration tree, instructions, and exact
review input. A head or base movement invalidates the evidence.

## Trust-Root controller boundary

The first introduction or an update of the Trust-Root controller itself follows
the protected Current-Head Trust-Root review path. It cannot certify,
install, or approve itself. Only after that controller has been merged through
the protected Current-Head gates may a controlled environment cache its exact
blob from the authoritative Base. Later engine and policy changes use that
cached Base controller: it reloads the pinned Base engine, requires the
controller to be byte-for-byte unchanged, and verifies existing evidence
through the immutable Base policy.

Local controller commands never invoke Codex, Copilot, or another external
reviewer. The optional cache is an owned regular file below the current
worktree's Git administrative directory and can be installed only from the
unchanged Base. Missing, altered, symlinked, or unsafe cache content stops
verification. The controller does not install or replace Git hooks; protected
server gates remain the only protected acceptance boundary. Its local
`verify` command can report only on already-produced advisory evidence and
never authorizes a push or merge.

Repository discovery, local object reads, configuration inspection, and the
anonymous Base refresh all resolve Git from the system default path and run in
the same minimal environment without inherited Git, proxy, or credential
variables. The candidate engine path must be a regular non-symlink file inside
the authorized repository; any other filesystem type fails closed before Base
code is loaded.

## Finalization and server review

Local `validate` performs deterministic checks without external review. Drafts,
ordinary pushes, and `synchronize` events never request GitHub Copilot. They only
make any old Current-Head result stale. One request is made when a draft becomes
ready or when the protected `develop` workflow receives a finalization dispatch
bound to the exact live PR head. A previous request or completed review for that
same head makes the operation idempotent.

All unresolved material Copilot findings for one reviewed head are supplied to
one Codex remediation run and can produce at most one correction commit. That
commit receives one final exact-head Copilot re-review. New material findings in
that closing review stop fail-closed; they do not start a recursive loop.
Formatter-, linter-, and type-only advice covered by passing deterministic gates
does not justify a no-op source commit.

## Automation and approval boundary

All repository-local validation, ordinary branch pushes, PR creation, protected
Current-Head gates, normal merge commits, rollout PRs, Security dispatches, and
acceptance collection are designed to continue without an interactive human
step. A previously authorized automation identity is not replaced with a
personal token, synthetic approval, or privileged bypass.

Private source sent outside the Lightning IT trust boundary is different. The
external review payload is frozen and identified by repository, branch, exact
head SHA, base SHA, integration tree, and patch digest. Where the execution
platform requires payload-specific Egress consent, that consent is collected
once only after the local finalization gate. It authorizes that immutable
payload and cannot silently authorize a later correction commit. An ADR or
repository workflow cannot weaken an enforcement rule owned by the execution
platform.

The operational target is therefore zero repeated approval requests for an
unchanged final head, not reuse of consent for different private content.
Review idempotency prevents duplicate Egress for the same binding. Local checks
and bundled remediation run before finalization wherever their trust level
permits, minimizing the chance that external review creates a replacement head.
If fully non-interactive private Egress is required in the future, the approved
reviewers must run inside the Lightning IT trust boundary or the platform owner
must provide a separately governed persistent Egress policy; branch, Ruleset,
environment, and administrator bypasses remain prohibited.

## Early review-size contract

The engine renders the exact 40-line-context, binary-aware patch before any
expensive deterministic check or external review. The configured maximum is an
exclusive boundary: a 200000-byte policy accepts at most 199999 bytes. The safe
preflight output contains only byte count, limit, path count, and patch digest.
The limit is never increased or bypassed automatically.

## Staged rollout

1. Merge the bounded engine foundation through its protected Current-Head
   gates.
2. Merge the two-profile, finalization, parallel-review, and measurement pilot
   after a fresh trust-root dual review.
3. Add the signed exact-input review cache as a separate stage only after the
   profile pilot has live evidence.
4. Add bounded parallel local checks and the explicit Foundation stack schema.
5. Run one complete real Supplementary pilot with `humanActions=0` on the final
   unchanged integration head.
6. Only after acceptance, port the proven contracts to Shared Assets and create
   one guarded sync PR per managed repository.

Each stage is independently reviewable. A stacked stage is not published until
its immediate predecessor is regularly merged. Cached part-review PASS records
may accelerate later work but never replace the one full final integration-head
review or the final end-to-end run.
