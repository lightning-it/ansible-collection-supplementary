# Contributing to Lightning IT Ansible Collections

Thanks for taking the time to contribute! These guidelines keep all collections
consistent and make reviews fast and predictable.

This document applies to all `ansible-collection-*` repositories under
`lightning-it`.

## Ground Rules

1. **Automate everything you can.**
   Run the shared pre-commit hooks (`pre-commit run --all-files`) and ensure all
   GitHub Actions workflows are green before asking for review.

2. **Keep changes scoped.**
   Focus each pull request on a single fix or feature. Avoid opportunistic
   refactors unless they are clearly part of the change description.

3. **Document behaviour.**
   Update READMEs, role documentation, example playbooks, and changelog
   fragments when functionality changes. Explain _why_ as well as _what_.

4. **Respect the licence.**
   All contributions are under `MIT`. New dependencies must be licence
   compatible and, where relevant, documented in `requirements.yml` or
   `requirements.txt`.

5. **No secrets or customer data.**
   Never commit credentials, tokens, or production configuration. Use CI
   variables, vaults, and environment variables instead.

## Renovate and Entitlement-Gated Collections

If a repository tracks entitlement-gated Ansible collections (for example
Red Hat Automation Hub content) with Renovate, configure an authenticated
registry for `galaxy-collection` lookups.

Recommended registry URL:

- `https://console.redhat.com/api/automation-hub/content/published/`

Automation Hub requires authentication. For Red Hat offline tokens, Mend-hosted
Renovate cannot perform the required refresh-token -> access-token exchange
during `galaxy-collection` lookups.

Policy for certified-only requirement files:

- Exclude those files from Renovate checks/updates.
- Maintain certified collection versions via controlled manual or CI workflow.

Without this, Renovate lookups for collections such as `ansible.controller` or
`redhat.satellite` will fail in Mend-hosted mode when using offline tokens.

## AI assistants / `AGENTS.md`

If you use AI coding assistants (e.g. ChatGPT, Copilot, Codex) for changes in
this repository:

- Make sure they follow the rules defined in `AGENTS.md` at the repository root.
- Always **load and apply** `AGENTS.md` before asking the assistant to create or
  modify roles, Molecule scenarios, CI workflows, or helper scripts.
- Do not accept suggestions that:
  - hardcode collection names where they should be derived,
  - break existing patterns for roles, Molecule, or devtools integration,
  - bypass linting or testing conventions described in `AGENTS.md`.

In short: AI-generated changes are welcome, but they must conform to the same
standards as handwritten code and follow the shared agent specification.

## Workflow Checklist

Before opening a pull request:

- [ ] Branch from the current `develop` integration branch.
- [ ] Run `pre-commit install` once per clone, then `pre-commit run --all-files`.
- [ ] Run `molecule test` for affected roles/scenarios (`devtools-molecule.sh` for
      light scenarios, dedicated `*_heavy` scripts for Vagrant/VM-based tests).
- [ ] Validate `ansible-galaxy collection build` if you touched `galaxy.yml`,
      `meta/main.yml`, or collection layout.
- [ ] Add a changelog fragment for user-visible collection changes.
- [ ] Update `README.md` and example playbooks when user-facing behaviour changes.
- [ ] Make sure GitHub Actions are green (Collection CI and changelog checks).
- [ ] Update `meta/role-coverage.yml` and generated coverage when a role or
      scenario is added or materially changed.
- [ ] Run every affected supported Tiny, Heavy, and Application Acceptance
      profile; do not represent Stub or Skip-mode output as production coverage.

## Changelog Fragments

Lightning IT Ansible collections use the official Ansible collection changelog
workflow with `antsibull-changelog`.

Normal feature and fix PRs must add a fragment under:

```text
changelogs/fragments/<meaningful-name>.yml
```

Use one or more supported antsibull categories:

```yaml
---
minor_changes:
  - role_name - Add support for the new user-visible behavior.
bugfixes:
  - role_name - Fix idempotency when the target file already exists.
security_fixes:
  - role_name - Avoid logging sensitive token material.
```

Do not manually edit generated changelog files in normal feature or fix PRs:

- `changelogs/changelog.yaml`
- `CHANGELOG.rst`
- legacy `CHANGELOG.md` files, where still present

Generated changelog files are changed by release PRs from `release/vX.Y.Z`
branches only.

Fragment exceptions are allowed when a PR is documentation-only, CI-only,
metadata-only, or test-only. Apply one of these labels when appropriate:

- `skip-changelog`
- `documentation`
- `ci`
- `tests`

## Pull Request Expectations

Each pull request should include:

- A concise title following conventional commits
  (e.g. `fix: address selinux idempotency`, `feat: add tf_runner role`).
- A description covering:
  - the problem,
  - the solution,
  - and how you validated it (commands, scenarios, environments).
- Links to related issues or discussions (if any).
- Logs or snippets when relevant (e.g. Molecule output, failing CI logs).

Keep the diff focused. If you need to do mechanical refactors or formatting
sweeps, do them in a separate PR.

## Release Process Highlights

- Versioning follows semantic versioning and `galaxy.yml` is the source of
  truth for the collection version.
- Ansible collections do not use `semantic-release`: `feat:` and `fix:` commits
  are useful PR conventions, but releases are explicit maintainer actions so the
  collection changelog, `galaxy.yml` version, release branch, and Galaxy
  publication stay aligned.
- Release preparation is automatic after feature changes are merged to `main`:
  the **Prepare collection release** workflow opens a `release/vX.Y.Z` PR when
  unreleased changelog fragments exist.
- The workflow derives patch, minor, or major impact from reviewed changelog
  fragment categories, requires the exact next stable semantic version, creates
  or updates a `release/vX.Y.Z` branch, runs `antsibull-changelog release`,
  bumps `galaxy.yml`, builds the collection, and opens a release PR into
  `main`.
- Release PRs must use a merge commit. Squash and rebase merges are prohibited
  because publication binds the reviewed release head and both merge parents.
- After the release PR is merged and the GitHub Release is published, automation
  opens a release back-sync PR from `main` to `develop`.
- `develop` to `main` promotion PRs are opened only when `main` is already an
  ancestor of `develop`; merge release back-sync PRs before promoting more work.
- Maintainers may still run the workflow manually to assert the fragment-derived
  version or retry a release preparation; manual input cannot override reviewed
  semantic impact.
- Do **not** push release commits directly to `main`.
- GitHub Release notes are generated from the repository changelog content after
  the release PR is merged.
- Publishing to Ansible Galaxy is done from CI only when explicitly enabled and
  `GALAXY_API_TOKEN` is configured. Do not upload local builds manually.

## Tooling & Dev Environment

Collections assume the following tooling:

- **pre-commit** with shared hooks. The collection hooks are devtools-backed
  and intentionally mirror the PR gates: changelog policy, ansible-lint,
  Molecule light scenarios, and collection smoke build/install.
- Validation containers are tag-and-digest pinned. Non-Molecule hooks receive a
  read-only workspace without an engine socket or sibling-source mounts;
  Molecule explicitly opts into only its required workspace, network, and
  nested-container access.
- The devtools `HOME` is a fresh engine-managed tmpfs for every invocation. It
  is explicitly mounted `exec` for identical Docker and Podman behavior because
  Molecule stages executable test shims below `HOME`; `nosuid`, `nodev`,
  `no-new-privileges`, and capability dropping retain the surrounding
  isolation. No persistent whole-home cache is mounted.
- **ee-wunder-devtools-ubi9** container as the canonical dev/CI environment:
  - Terraform, tflint, terraform-docs,
  - ansible-core, ansible-lint, Molecule,
  - antsibull-changelog and collection build tooling.
- Local scripts under `scripts/` (e.g. `devtools-ansible-lint.sh`,
  `devtools-molecule.sh`, heavy scenarios like `devtools-molecule-*_heavy.sh`)
  are part of the expected workflow.

Run `pre-commit run --all-files` before opening or updating a PR. The local
hooks use the same `ee-wunder-devtools-ubi9` container path as GitHub Actions,
so host-installed Ansible tooling must not be treated as authoritative.

## Getting Help

- Use the GitHub issue tracker of the respective collection repository for bugs
  and feature requests.
- For internal Lightning IT discussions (design, roadmap, platform-wide changes),
  coordinate via the usual internal channels (e.g. `#automation` Slack or the
  internal ModuLix documentation).

---

_This file is derived from the Lightning IT collection baseline but remains
repository-local. Automated shared-assets synchronization is intentionally
limited to the marked pre-commit block, the container and devtool wrappers, and
the three digest-pinned validation, devtool, and shipped-image Renovate
managers._
