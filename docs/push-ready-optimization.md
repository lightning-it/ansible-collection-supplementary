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

The evidence records total duration, per-reviewer duration, review bytes,
executed and repeated checks, cache hits and misses, maximum parallelism, and
explicit local external-review invocation counts split between Codex and
Copilot. Those invocation counts are the stable cost proxy: compare them and
the measured durations rather than storing account-specific prices or billing
data in repository evidence.
The server-side baseline additionally records the Current-Head Copilot gate,
Collection CI, and final end-to-end workflow durations for the exact SHA.

## Parallel reviewer contract

Codex and GitHub Copilot are submitted together. Each reviewer receives its own
private temporary repository containing one history-free synthetic root commit.
Both roots are derived independently and must bind to the same authoritative
base tip, merge-base, head commit and tree, integration tree, exact patch digest,
and instruction digests. A startup barrier prevents either external invocation
from being deliberately serialized behind the other.

The result passes only when both required reviewers pass. Timeouts, failures,
foreign reviewer identities, changed workspaces, different input bindings,
non-overlapping external execution, or reuse of one workspace stop fail closed.
Evidence contains only cryptographic bindings and timing metadata for the two
workspaces, not their paths or content.

The local Copilot CLI result remains an approximation. GitHub's authoritative
Copilot Current-Head review and every protected repository gate remain required
after the normal fast-forward feature-branch push.

## Risk profiles and trusted classification

The base branch owns the only trusted classifier. Known collection code, role,
test, Molecule, changelog, and documentation paths use the `standard` profile:
all deterministic gates plus one complete history-free Codex review run locally,
while local Copilot is not invoked. Engine, policy, workflow, authorization,
release, promotion, acceptance, validator, and otherwise unknown paths use the
`trust-root` profile and require Codex and Copilot in separate parallel
history-free workspaces. A missing, malformed, or pre-profile base policy also
falls back to `trust-root`. Editing the classifier or either profile therefore
classifies itself as `trust-root`.

Evidence binds the profile, its trusted base-policy digest, the authoritative
base tip, merge-base, exact head, integration tree, instructions, and exact
review input. A head or base movement invalidates the evidence.

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
