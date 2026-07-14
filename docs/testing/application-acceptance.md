# Keycloak Application Acceptance

The acceptance scenario uses pinned pytest, Playwright for Python, Chromium,
Allure, and JUnit tooling. Its minimal OIDC relying party exposes `/viewer` and
`/admin`, validates Keycloak-issued tokens, and returns explicit status codes.

The identities are `keycloak_test_admin`, `keycloak_test_viewer`,
`keycloak_test_unauthorized`, and `keycloak_test_invalid`. Passwords and OIDC
secrets are generated per run or supplied through protected CI secrets; missing
settings fail the suite and no real secret is committed.

Tests cover browser login, redirects, sessions, admin mutation, viewer reading,
viewer mutation denial, unauthorized denial, invalid credentials, OIDC metadata,
JWKS signature, claims, roles, groups, expiry, tampered tokens, logout, and old
session denial. UI observations are paired with protected endpoint assertions.

On failure, password fields are cleared before screenshots. A fresh diagnostic
trace is then recorded without authentication input. Evidence redaction and
secret scanning remain mandatory.

```bash
playwright show-trace artifacts/playwright-traces/TEST.zip
allure generate artifacts/allure-results --clean -o artifacts/allure-report
allure open artifacts/allure-report
```

New security cases must use event-based waits, assert observable API behavior,
and never attach tokens, cookies, authorization headers, passwords, or keys.
