# LI-178 / Supplementary #974: held caller contract

This repository-local candidate is preparation, not hosted acceptance. Its only
job is guarded to the exact repository/Main/manual/first attempt; its sole step
unconditionally exits held with `exit 1`. It has no permissions, environment,
reusable workflow, checkout, token request or broker effect. No input or repository
variable can enable a sender, and reruns are rejected. Existing promotion/release workflows,
environments, scheduler containment and the completed #1205 collector are unchanged.
It is not an executable append packet or production broker configuration.

`python3 scripts/rep120_caller_contract.py` describes the held interface.
`--inspect-context` additionally validates an allowlist of GitHub metadata, but
these environment strings are untrusted observations, never signed OIDC evidence.
Both modes retain `enabled=false`, `request=null`, `oidc=null`,
`native_delivery=null` and `hosted_acceptance=false`. There is no enable option.

## Protected source discovery

Protected Supplementary main `187ee98a433152e418941f091298c3e0a0c76bdc` and develop
`600b8c9195b95c342b712afb8546c2bb1d4b1fb9` were independently read. Their promoter
blob is `a35f319eb8c2132a503faeea41973e7c4ef3ec3c`. Neither protected tree has a
REP120 broker caller, receiver, configuration or OIDC transport. Existing
`id-token: write` jobs belong to collection CI/publication, not this interface.
The promoter dispatches itself from scheduled/develop events, then uses
`ansible-collection-release-prepare` and a Release App before branch comparison;
it cannot be relabelled as the broker caller. Scheduler activation is out of scope.

The contract below was first read from protected Source main `dbcf3f75` and then
rebound to Root's reported new protected Main
`c3ba9663b6467d8fb336cc11b954bf3716ded1b6`, exact broker blob
`36824fc60fd1e8465eb895966938eb5e4d1c819c`, remote-append blob
`9f2d5f0816f149386e6fa46020b543d0fd7ed2fb`, and core blob
`f065e6daff54f14e423fc7e8eef18416f1559f2c`. Fresh immutable API reads and the
Source comparison show the caller/request/approval/OIDC interface unchanged;
only signed Git-object reconstruction changed. No Source code is copied,
changed, retested or republished here.

## Caller and OIDC bindings

The candidate source path is `.github/workflows/rep120-ledger-caller.yml` in
`lightning-it/ansible-collection-supplementary`, repository ID `1103407173`,
owner ID `54334171`. Only a future protected **main commit containing this exact
workflow and consumer implementation** can become `caller.source_sha`; the
current protected commits do not contain this candidate. A local candidate SHA
or workflow blob is not that protected commit or activation authority.

The accepted broker independently requires all of these signed claims:

| Claim | Exact binding |
| --- | --- |
| `iss` | `https://token.actions.githubusercontent.com` |
| `aud` | Root decision: `lit-rep120-ledger:1413923700:operation-ledger-core` |
| `repository`, `repository_id`, `repository_owner_id` | The exact Supplementary identities above; IDs are strings in JWT |
| `ref`, `sha`, `workflow_sha` | `refs/heads/main`, both SHAs equal externally pinned `caller.source_sha` |
| `workflow_ref` | `lightning-it/ansible-collection-supplementary/.github/workflows/rep120-ledger-caller.yml@refs/heads/main` |
| `sub` | `repo:lightning-it/ansible-collection-supplementary:ref:refs/heads/main` |
| `run_id`, `run_attempt` | Actual request run ID and string `1` |
| `job_workflow_ref`, `job_workflow_sha` | Must be absent |

RS256/JWKS identity and signature are verified by the broker, not this helper.
`iat <= now < exp`, `nbf <= now`, and `0 < exp-iat <= 600` are mandatory.
The live run must simultaneously be attempt 1, main/exact source/exact workflow,
same repository/head repository, event `push` or `workflow_dispatch`,
`status=in_progress`, `conclusion=null`; main must still be protected/current.
Completed, waiting, scheduled, reusable, rerun or drifted callers fail closed.

GitHub's actual token request mechanism is job-scoped `id-token: write` plus its
runner-provided `ACTIONS_ID_TOKEN_REQUEST_URL` and
`ACTIONS_ID_TOKEN_REQUEST_TOKEN` (or toolkit `getIDToken(audience)`). The
candidate neither grants that permission nor reads these values. Root has
selected the audience; the narrowly scoped permission and private native delivery
before a separately reviewed sender is implemented. Tokens must never enter
logs, command arguments, artifacts, Git or request/evidence JSON.
An Environment job changes GitHub's subject; it cannot use this broker's
branch subject. Do not weaken existing release Environment semantics to fit it.
The repository was created in 2025 and the live OIDC customization GET returned
`use_default=true`; actual signed subject readback remains an admission test.
See [GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc).

## Actual request and approval contract (not a populated packet)

The native broker consumes exactly seven JSON fields, no schema wrapper:
`expected_head`, `operation_key`, `path`, `contents`, `run_id`, `approval_id`,
`expires_at`. `expected_head` is the actual expected ledger OID, not always
Genesis. `operation_key` is the authenticated operation's 64-lowercase-hex key;
never a freshly invented UUID. `path` is exactly
`ledger/operations/<operation_key>/(record|four-digit-event).json`.
`contents` is canonical base64 of the complete core-valid immutable append;
the record's `created_at` or event's `at` must equal authenticated broker time.
Core replay/semantics and existing operation ownership remain mandatory.
The three numeric fields are positive integers. Broker time must satisfy
`now < expires_at <= now+600` and remain before runtime expiry.
Both `path=null` and `contents=null` mean no-op, not ownership or acceptance.

`approval_id` means a **GitHub issue-comment ID**, not an Environment approval,
Jira receipt, generic original mandate or run approval. The exact comment body is:

```text
Ledger append APPROVED <operation_key> <sha256(graphql_input)> <sha256(canonical(settings))> <caller.source_sha> <expires_at>
```

No placeholders are sent. `graphql_input` is the broker's prepared compact,
sorted ASCII GraphQL input bytes **without** a trailing newline. It includes
the actual ref node, expected head, complete single addition and operation
headline. `canonical(settings)` is sorted compact ASCII JSON **with** its
trailing newline. No helper duplicates the accepted replay or hashing engine.
Root must supply the actual validated plan/input/configuration bytes, not a
self-authenticating hash or draft. The broker replays and recomputes them.

The configured approval repository/issue must match the comment API/HTML URLs.
The exact configured actor ID must still have write/maintain/admin permission,
the issue must be open, and the literal comment must remain exact/unwithdrawn
at each effect fence. Root's nonsecret binding decision selects approval repository
`lightning-it/github-management-lit`, issue `721`, actor ID `76040632`. These
routine bindings are not per-append approval or proof of live actor permissions.
The caller may not fabricate a comment or approver.
There is no request, run, deadline or approval ID in this candidate.

## Root-owned interface fields still required

The ledger resource is no longer missing: independent GETs read repository
`1413923700`, canonical `refs/heads/operation-ledger-core`, node
`REF_kwDOVEbDdNoAIHJlZnMvaGVhZHMvb3BlcmF0aW9uLWxlZGdlci1jb3Jl`, parentless
root `e0b105b37d23b71ec9b06b5fc966b90443b99490`, valid GitHub signature and tree
`aa437c8a920cfc7e100485e5e8e8d6dc14922e08`. Root's native/ref receipts report
GPG verification and App-only write/signature/delete/forcepush/ref-creation
policy admission, effective policy digest
`9d9c705131abec6c3fec944f69ca74897067494d01bc90a5976680e26152e4e0`.
Those receipts are advisory provenance here, not a whole policy transaction audit.
Writer App/install `5267441/170270980` and reader `5274635/170286504` already
exist; this candidate requests no App, key, installation or credential change.

Root must still supply/approve these exact integration fields:

1. The future protected caller Main SHA, accountable `owner_sha256`,
   `policy_epoch` and job OIDC permission. Audience and approval location/actor
   are already selected above; do not reopen those routine decisions.
2. The complete authenticated binding, including writer/signer user IDs,
   platform signer fingerprint and fresh effective-policy hash. Existing resource
   facts are reused, not new authority or partial enabled configuration.
3. Native receiver location/protocol and bounded framing, peer authentication,
   exact immutable request-byte acquisition and protected source binding. No
   HTTPS endpoint, SSH credential, socket path, bearer-token exchange or host
   access route is invented here. The Python broker exposes no accepted hosted API.
   Root reports preparation of a private short-lived one-shot TLS receiver;
   actual origin/port, certificate trust or pin, peer/OIDC admission, byte framing,
   deadline and response/readback semantics remain Root-owned fields, not facts
   supplied or enabled by this candidate. `native_delivery` remains null.
4. Supervisor credential-free pre-exec/start proof and post-start private-pipe
   delivery of OIDC (<=16384 bytes), independent reader token (<=4096 bytes) and
   deferred writer key. These are native descriptor inputs, not workflow secrets.
5. Exact root-private persistent domain/device/inode/UID, domain/clock/crypto
   hashes, runtime expiry, key-reader custody locator and revocation/drain owners.
6. The actual authenticated operation/material, replay-valid single append,
   trusted timestamp, prepared GraphQL bytes, full canonical settings and exact
   per-append issue-comment approval while the first-attempt caller is running.

Review this local held source now so Root can prepare the receiver and proposed
caller path without waiting for hosted acceptance. When Root supplies the
approved private transport and identity fields, integrate the narrowly bounded
sender into this same candidate/path and publish through existing gates; bind
the actual resulting protected Main SHA, never this local draft or a prior SHA.
No extra cumulative AI review or optional intermediate publication is requested.
Sender/receiver integration and permission remain a separately bounded
nonoverlapping next step. Acceptance requires actual positive/negative,
race/crash, lifecycle/drain/revocation and readback evidence; this description,
fixtures and GitHub artifacts are not WORM/CAS, attestations, R8 or a canary.
Nothing activates #974, changes the scheduler, closes LI-178/LI-206 or starts a
24-hour timer.

## Local verification

Run the repository's `pre-commit run --all-files` first. Focused tests use the
existing pinned, offline, read-only, non-root Devtools boundary:

```sh
bash scripts/devtools-local-quality.sh python3 -m unittest tests.unit.test_rep120_caller_contract -v
bash scripts/devtools-local-quality.sh ruff check scripts/rep120_caller_contract.py tests/unit/test_rep120_caller_contract.py
```

These tests validate held defaults, metadata drift/malformed inputs, credential
canary exclusion and the guarded/always-held/no-permission workflow. They do not
execute a hosted caller, obtain OIDC, exercise native transport or prove adoption.
