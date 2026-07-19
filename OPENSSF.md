# OpenSSF Readiness

This repository follows the Lightning IT shared OpenSSF readiness model generated from `lightning-it/shared-assets-lit`.

## Repository

- Repository: `ansible-collection-supplementary`
- Visibility: `public`
- Type: `ansible_collection`
- Release type: `ansible_galaxy`
- Artifact type: `ansible_collection_tarball`

## Scorecard

Enabled through `.github/workflows/openssf-scorecard.yml` with scheduled,
manual, and `branch_protection_rule` triggers. The workflow executes the
Scorecard v2.4.3 container by immutable registry digest and uploads SARIF to
GitHub code scanning.

Repository-run results are not published to the OpenSSF API. Its workflow
verifier currently allows the upstream `ossf/scorecard-action` reference, whose
v2.4.3 metadata delegates to a mutable container tag, but does not accept a
digest-form container reference. The workflow therefore does not request an
OIDC token or claim publication; the public badge can reflect OpenSSF's
independent scan until digest-pinned publication is supported upstream.

The Scorecard badge is included in `README.md` only for public repositories where the workflow is synced.

## Best Practices Badge

Required but not enrolled. Enroll manually at OpenSSF Best Practices, complete the questionnaire until the project reaches the configured target level, then record the numeric project ID in `openssf_best_practices.project_id` in `release-model/repositories.yml`.

Do not add a passing OpenSSF Best Practices badge until the repository is actually enrolled and passing. Badges must be generated from `release-model/repositories.yml`; hand-written badges are rejected by the release-model audit.

## Security Policy

`SECURITY.md` describes supported versions, vulnerability reporting, coordinated disclosure, supported artifact scope, and the distinction between public repository content and private customer or infrastructure data.

## Branch Protection And Release Integrity

- `main` is the protected release branch.
- `develop` is the integration branch for normal work, Renovate, and shared-assets-lit PRs.
- `develop` to `main` promotion PRs require manual review.
- Renovate and shared-assets-lit PRs may auto-merge only into `develop` after required checks pass.
- Releases and publishing happen only from trusted `main` workflows after validation.
- Release evidence is generated for repositories with release artifacts.

## Dependency Automation

Dependency automation must target `develop` and must not bypass required checks. Coverage should include GitHub Actions, language dependencies, Ansible content, container base images, pre-commit hooks, and documentation tooling where applicable.

## Security Scanning

ansible-lint, yamllint, changelog checks, collection build/smoke validation, and CodeQL where enabled.

## Exceptions

Repository-specific exceptions must be documented in this file or in `.lit/repository.yml`. Exceptions must not expose secrets, private infrastructure details, customer data, or credential-bearing examples.
