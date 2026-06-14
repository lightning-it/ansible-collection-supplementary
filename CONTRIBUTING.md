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
   Update READMEs, role documentation, example playbooks, and changelog entries
   when functionality changes. Explain _why_ as well as _what_.

4. **Respect the licence.**  
   All contributions are under `GPL-2.0-only`. New dependencies must be licence
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

## AI assistants / `agent.md`

If you use AI coding assistants (e.g. ChatGPT, Copilot, Codex) for changes in
this repository:

- Make sure they follow the rules defined in `agent.md` at the repository root.
- Always **load and apply** `agent.md` before asking the assistant to create or
  modify roles, Molecule scenarios, CI workflows, or helper scripts.
- Do not accept suggestions that:
  - hardcode collection names where they should be derived,
  - break existing patterns for roles, Molecule, or devtools integration,
  - bypass linting or testing conventions described in `agent.md`.

In short: AI-generated changes are welcome, but they must conform to the same
standards as handwritten code and follow the shared agent specification.

## Workflow Checklist

Before opening a pull request:

- [ ] Branch from `main`.  
- [ ] Run `pre-commit install` once per clone, then `pre-commit run --all-files`.  
- [ ] Run `molecule test` for affected roles/scenarios (`devtools-molecule.sh` for
      light scenarios, dedicated `*_heavy` scripts for Vagrant/VM-based tests).  
- [ ] Validate `ansible-galaxy collection build` if you touched `galaxy.yml`,
      `meta/main.yml`, or collection layout.  
- [ ] Update `README.md` and example playbooks when user-facing behaviour changes.  
- [ ] Make sure GitHub Actions are green (Collection CI, Semantic Release dry-run
      on PRs).  

For collections using semantic-release:

- [ ] Follow conventional commits (`feat:`, `fix:`, `chore:`, `docs:`) so the
      release tooling can infer version bumps and changelog entries.

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

- Versioning is handled by **semantic-release** via GitHub Actions.
- Do **not** create tags manually; tags are created by the release workflow on
  merge to `main`.
- Changelogs are generated automatically based on commit messages and the
  configured semantic-release plugins.
- Publishing to Ansible Galaxy (where configured) is done from CI
  (e.g. `ansible-collection-*/.github/workflows/*publish-galaxy.yml`).
  Do not upload local builds manually.

## Tooling & Dev Environment

Collections assume the following tooling:

- **pre-commit** with shared hooks (YAML, ansible-lint, Molecule, actionlint,
  renovate-config-validator, etc.).
- **ee-wunder-devtools-ubi9** container as the canonical dev/CI environment:
  - Terraform, tflint, terraform-docs,
  - ansible-core, ansible-lint, Molecule,
  - semantic-release + Node toolchain.
- Local scripts under `scripts/` (e.g. `devtools-ansible-lint.sh`,
  `devtools-molecule.sh`, heavy scenarios like `devtools-molecule-*_heavy.sh`)
  are part of the expected workflow.

When in doubt, prefer running checks through the devtools wrapper scripts so
your local behaviour matches CI.

## Getting Help

- Use the GitHub issue tracker of the respective collection repository for bugs
  and feature requests.
- For internal Lightning IT discussions (design, roadmap, platform-wide changes),
  coordinate via the usual internal channels (e.g. `#automation` Slack or the
  internal ModuLix documentation).

---

_This file is managed centrally for Lightning IT Ansible collections. Downstream
repositories should not edit their copy directly — propose changes via the
shared assets repository or the designated “collection-meta” repo so every
collection stays aligned._
