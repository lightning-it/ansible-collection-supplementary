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
executed and repeated checks, cache hits and misses, and maximum parallelism.
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

## Early review-size contract

The engine renders the exact 40-line-context, binary-aware patch before any
expensive deterministic check or external review. The configured maximum is an
exclusive boundary: a 200000-byte policy accepts at most 199999 bytes. The safe
preflight output contains only byte count, limit, path count, and patch digest.
The limit is never increased or bypassed automatically.

## Staged rollout

1. Merge the bounded engine foundation through its protected Current-Head
   gates.
2. Merge this parallel-review and measurement stage after a fresh dual review.
3. Add the signed exact-input review cache as a separate stage.
4. Add bounded parallel local checks and the explicit Foundation stack schema.
5. Run one complete real Supplementary pilot with `humanActions=0` on the final
   unchanged integration head.
6. Only after acceptance, port the proven contracts to Shared Assets and create
   one guarded sync PR per managed repository.

Each stage is independently reviewable. A stacked stage is not published until
its immediate predecessor is regularly merged. Cached part-review PASS records
may accelerate later work but never replace the one full final integration-head
review or the final end-to-end run.
