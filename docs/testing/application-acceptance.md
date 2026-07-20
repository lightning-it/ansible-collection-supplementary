# Application Acceptance

Application Acceptance proves that a real consumer can use the deployed result.
The acceptance surface is declared per role in `meta/role-coverage.yml`.

| Component type | Required surface |
|---|---|
| Web application | Browser plus authenticated API |
| API service | Authenticated positive and negative API workflow |
| Database | Native client transaction, permissions, persistence, and restore |
| Logging | Generate, transport, ingest, query, and verify an exact event |
| Monitoring | Register/discover a target, collect state, and query the result |
| Network service | Establish a connection/tunnel and transfer real traffic |
| Agent | Generate source data, deliver it, and verify the destination |
| Runner | Register and execute a harmless real workload |
| Backup | Back up, mutate/remove state, restore, and compare exact state |
| Configuration-as-Code | Apply, query, reconcile, delete, and prove idempotency |
| Infrastructure | Perform, verify, rerun, revert, and clean up a safe operation |

Authorized identities must succeed; read-only identities must be unable to
modify; invalid, unauthorized, and revoked credentials must fail where those
controls apply. UI visibility is never sufficient authorization evidence: pair
it with an API, CLI, protocol, protected endpoint, database, or network check.

Browser scenarios use pinned pytest/Playwright tooling and emit JUnit, Allure,
sanitized screenshots, traces, console logs, and network diagnostics. The
patched stable Chrome channel is installed through Playwright for every cell
instead of trusting a shared cache-directory marker. Its executable path,
exact version, SHA-256, and target operating-system package inventory are preserved
as commit- and cell-bound dependency evidence and included in the release SBOM.
The package inventory binds unqualified binary and source-package identities to
the exact distro; Chromium uses the conservative NVD Chrome CPE for security
advisory matching.
The Keycloak relying party keeps OIDC tokens and claims only in a bounded,
server-side session store; its browser cookie is an opaque, rotated identifier.
The actual browser action sequence is traced from the start of the journey, but
snapshots, screenshots, and sources are disabled. On failure, the raw trace
exists only in a private temporary directory and is rewritten before evidence
capture: network/resource members, input values, headers, bodies, cookies,
storage, tokens, secrets, and URL queries are removed, with residual-secret
checks failing closed. A new cookie-free context renders the sanitized event
metadata for the screenshot. Non-browser scenarios use the smallest native
client suitable for the service.

An acceptance test cannot pass because variables rendered, a process exists,
installation was disabled, a command failure was ignored, or an external
integration was unavailable. Those outcomes are failures or explicit registry
blockers.

Keycloak's OIDC relying-party workflow is the current production reference; see
[`keycloak.md`](keycloak.md). It proves Keycloak behavior only and does not imply
coverage for another application. Its Application Acceptance scenario also
emits a separate JUnit report for an apply/query/mutate/zero-change/delete
`keycloak_cac` lifecycle, so the configuration-as-code claim is independent of
the browser authorization report.
