# Supplementary #974: default-held one-shot caller contract

This repository-local candidate is implementation preparation, not activation or
hosted acceptance. Its only job is guarded to the exact repository/Main/manual/
first attempt, `github.ref_protected == true`, actor ID `76040632`, and both
`github.actor` and `github.triggering_actor` exactly `litroc`. Workflow-wide
permissions are empty; the single caller job has only `contents: read` and
`id-token: write`. SHA-pinned checkout reads the exact
event SHA without persisted credentials. There is no Environment, reusable job,
schedule, dispatch, receiver deployment, retry or evidence upload. Empty inputs
fail before transport or token retrieval. Existing promotion/release workflows,
environments, scheduler containment and the completed #1205 collector are unchanged.
No endpoint, certificate, pin, source SHA, expiry or operation is supplied here.

`python3 scripts/rep120_caller_contract.py` describes the held interface.
`--inspect-context` additionally validates an allowlist of GitHub metadata, but
these environment strings are untrusted observations, never signed OIDC evidence.
Both description modes retain `enabled=false`, `request=null`, `oidc=null`,
`native_delivery=null` and `hosted_acceptance=false`. They do not call the sender.
The bounded sender entrypoint is `python3 -m scripts.rep120_caller_sender`.

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
sender reads these two runner-provided values after nonsecret preflight, and
retrieves the JWT only after the receiver's TLS peer and leaf pin pass. Root
selected the audience; permission is granted only to this guarded caller job.
Root separately admitted the dispatch identity `litroc` / user ID `76040632`;
an actual public GitHub user GET confirmed this exact pair. This is a distinct
dispatch decision, not inferred authority from the same ID's approval role.
The job predicate applies before its OIDC permission is granted. The sender
also requires exact `GITHUB_ACTOR`, string `GITHUB_ACTOR_ID`,
`GITHUB_TRIGGERING_ACTOR` and string `GITHUB_REF_PROTECTED=true` metadata before
opening any socket or retrieving OIDC. Both login fields bind to the same
fixed, read-back identity on attempt 1; no unsupported triggering-actor-ID
context is invented. Aliases, case changes, leading-zero IDs, missing metadata,
another trigger actor or an unprotected ref are held. These environment
observations remain untrusted outside the guarded hosted job and do not replace
the receiver's authenticated live run/source/identity/permission readback.
Tokens must never enter
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
No actual request, run, deadline or approval ID is invented by this candidate.

## Bounded public dispatch input API

The two optional string inputs default to empty and are **nonsecret JSON only**:

- `delivery`: exactly `ipv4`, `port`, `public_pem`, `leaf_sha256`, `expires_at`.
  IPv4 is canonical numeric text; port is an integer `1..65535`. PEM is one
  public certificate, never a private key. The leaf pin is lowercase DER SHA256.
  The owner-supplied integer expiry is future and at most 300 seconds away.
  Root supplies the actual values after native admission, not this code.
- `envelope`: exactly `schema`, `nonce`, `operation_key`, `config_sha256`,
  `source_sha`, `resource_sha256`, `request`. Schema is
  `lit-li178-one-shot-transport/v1`; nonce/op/config/resource are exact lowercase
  64-hex owner bindings; source is the actual protected caller Main 40-hex SHA.
  `request` has exactly the seven broker fields above, with `run_id: null`.
  The sender fills **only** that null field with actual integer `GITHUB_RUN_ID`
  after first-attempt context validation. No other field changes.
  Root binds the actual request digest after live run-ID readback, before its one
  accept. Supplied `oidc` or a prepopulated run ID fails before transport.

Neither input is authority proof. The admitted receiver independently binds nonce,
operation, config, Source, resource and canonical actual request digest. Its
native callback authenticates real JWT/JWKS, current protected source/run, exact
append approval, persistent claim and resource policies before credentials.
Sender shape checks do not replace native authorization or ledger-core replay.

Root prepares the listener before dispatch and activates accept only after actual
run-ID binding. The sender performs one connection, no readiness polling, sleep
or second attempt after an uncertain outcome. TLS verification uses only the
supplied public CA, fixed hostname `li178-one-shot`, TLS1.3 minimum and exact
DER SHA256 pin before obtaining or sending OIDC. No DNS or proxy is used for
receiver delivery. Binary framing matches Root's `send_once`: `LIT178T1`,
network-order uint32 length, canonical compact sorted ASCII JSON plus newline,
then `LIT178END`; body at most 1 MiB and OIDC at most 16 KiB.

OIDC retrieval is one direct HTTPS GET using actual runner URL/bearer, fixed
audience, compiled system trust locations and no proxy, redirect or retry.
Ambient `SSLKEYLOGFILE` and certificate environment overrides are not consumed.
URL must be a subdomain of `actions.githubusercontent.com` with exactly
`api-version=2.0`; no userinfo, fragment or non-443 port. The absolute origin-form
path uses RFC3986 `pchar` syntax and literal slashes, not a handcrafted identifier
alphabet or fixed endpoint name. Root paths, internal empty segments and trailing
slashes are preserved. Empty paths and leading `//` hold to avoid implicit or
authority-form routing. Dot segments (including the terminal segment), malformed
escapes, escaped separators/control bytes and double decoding still hold.
The sender preserves the accepted path bytes without decoding or normalization.
The [official runner](https://github.com/actions/runner/blob/main/src/Runner.Worker/Handlers/ScriptHandler.cs)
exports the service's `GenerateIdTokenUrl`; the
[official toolkit](https://github.com/actions/toolkit/blob/main/packages/core/src/oidc-utils.ts)
consumes that generated URL without specifying its opaque segment values.
[RFC3986 section 3.3](https://www.rfc-editor.org/rfc/rfc3986#section-3.3)
defines path syntax, not GitHub route semantics or native authorization.
No literal endpoint is guaranteed by those sources; the remaining ambiguity and
decoding exclusions are conservative local constraints, not universal provider
guarantees. The workflow's only input-derived environment values are delivery and
envelope; neither can set the runner URL/bearer. Exact protected Main, actor, event,
source and attempt-one gates remain mandatory, and Root still validates the JWT's
actual subject/audience/run independently. Locally forged environment metadata is
not authenticated authority. No actual rejected hosted path is disclosed or
inferred from synthetic grammar tests.
Invalid routing or changed query holds. Root verifies actual runner routing at
activation; synthetic test URLs are not actual hosted URL evidence.
The JWT remains in process memory/encrypted frame, never argv, extra env, logs,
input/artifacts. Core dumps are disabled; Python heap zeroing is not claimed.

One monotonic deadline bounds transport to at most 120 seconds and delivery expiry;
OIDC connect/read socket timeouts are additionally at most ten seconds. OS DNS
resolution of the official OIDC service is not claimed preemptible; the
three-minute job timeout is the outer process bound. Expiry is rechecked before
sending. The sole accepted ACK is exact fixed transport metadata with Boolean
`hosted_acceptance: false`; ACK reads are bounded to 4096 bytes. Errors print one
fixed held message, never the underlying exception, response, request or token.

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
   `policy_epoch` and activation of the narrow job OIDC permission. Audience and approval location/actor
   are already selected above; do not reopen those routine decisions.
2. The complete authenticated binding, including writer/signer user IDs,
   platform signer fingerprint and fresh effective-policy hash. Existing resource
   facts are reused, not new authority or partial enabled configuration.
3. Native receiver location/protocol and bounded framing, peer authentication,
   exact immutable request-byte acquisition and protected source binding. No
   HTTPS endpoint, SSH credential, socket path, bearer-token exchange or host
   access route is invented here. The Python broker exposes no accepted hosted API.
   Root supplies a concrete private short-lived one-shot TLS transport contract;
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

The concrete sender is integrated into the same candidate/path. It does
not wait for hosted acceptance merely to prepare source. The combined candidate
was published as PR #1210, not promoted to protected Main or dispatched;
Root owns actual transport/identity admission. Publish only
when the complete combined candidate passes existing gates; bind
the actual resulting protected Main SHA, never this local draft or a prior SHA.
No extra cumulative AI review or optional intermediate publication is requested.
Actual sender/receiver activation remains a separately bounded nonoverlapping
next step. Acceptance requires actual positive/negative,
race/crash, lifecycle/drain/revocation and readback evidence; this description,
fixtures and GitHub artifacts are not WORM/CAS, attestations, R8 or a canary.
Nothing activates #974, changes the scheduler, closes LI-178/LI-206 or starts a
24-hour timer.

## Local verification

Failed caller commands report exactly one fixed stage code: `INPUT_CONTEXT`,
`OIDC_CAPABILITY`, `TCP`, `TLS`, `OIDC_GET`, `SEND`, or `ACK`. These codes identify
the active phase only, not a verified underlying cause or evidence of acceptance.
Post-OIDC input revalidation still reports `INPUT_CONTEXT`; cleanup failures retain
the active phase. No exception text, traceback, URL, token, payload or environment
value is printed. A missing or invalid internal stage falls back to `INPUT_CONTEXT`.
Only a known `OIDC_CAPABILITY` predicate failure adds one finite suffix:
`URL_MISSING`, `URL_FORMAT`, `URL_HTTPS`, `URL_USERINFO`, `URL_PORT`,
`URL_FRAGMENT`, `URL_HOST`, `URL_PATH`, `URL_QUERY`, `BEARER_MISSING`,
`BEARER_FORMAT`, `BEARER_LENGTH`, or `BEARER_ASCII`. This names the first rejected
existing predicate, never a value, measured length, header hash or exception.
Missing, forged or wrong-stage reason metadata adds no suffix. Unexpected failures
retain the stage-only message; the suffix does not establish actual hosted cause
until observed in the corresponding native run. Existing unknown URL routing/query
changes outside the documented opaque-path contract still hold.
Path rejection now identifies a fixed subpredicate: `URL_PATH_ORIGIN_FORM`,
`URL_PATH_ESCAPE`, `URL_PATH_SYNTAX`,
`URL_PATH_DOT_SEGMENT`, `URL_PATH_CONTROL`, `URL_PATH_SEPARATOR`, or
`URL_PATH_DOUBLE_ENCODING`. Previously accepted paths remain accepted; only the
undocumented endpoint/empty-segment routing assumptions are removed. Origin-form
is checked before grammar rejection is classified in escape/syntax order;
decoded segments are checked in wire order, with dot/control/separator/percent
precedence within each segment. Only these constant names may cross the error
boundary; no path, byte, length, URL, bearer or exception text is exposed.
Legacy `URL_PATH` remains a valid historical code. This correction does not
establish which predicate rejected the actual hosted path, prove hosted success,
or authorize a diagnostic dispatch. A next regular Root-owned attempt still
requires its normal gates. All existing admission, source, run, expiry, origin,
query/audience, TLS, OIDC and ACK guards remain unchanged. There is still no retry,
dispatch or activation authority in this sender.

Run the repository's `pre-commit run --all-files` first. Focused tests use the
existing pinned, offline, read-only, non-root Devtools boundary:

```sh
bash scripts/devtools-local-quality.sh python3 -m unittest tests.unit.test_rep120_caller_contract tests.unit.test_rep120_caller_sender -v
bash scripts/devtools-local-quality.sh ruff check scripts/rep120_caller_contract.py scripts/rep120_caller_sender.py tests/unit/test_rep120_caller_contract.py tests/unit/test_rep120_caller_sender.py
```

The focused suite is `tests.unit.test_rep120_caller_contract` plus
`tests.unit.test_rep120_caller_sender`. It validates default-held inputs, exact
workflow permission/trigger scope, run-ID-only substitution, malformed/drift
rejection before network/token, no redirects/proxy/retries, bounded frames/ACK,
expiry and secret-safe errors. Real Linux loopback TLS tests generate fixture
keys only in memfds, prove compatible framing and reject hostname/pin mismatch
before even the mocked OIDC callback. They do not obtain real OIDC, exercise an
actual hosted receiver/Broker, prove adoption or count as native acceptance.
