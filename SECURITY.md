# Security Policy

This repository is part of the ModuLix automation stack and may
be used in security-sensitive environments (infrastructure, platforms,
compliance tooling). This document describes how we handle security-related
issues for this project.

## Supported versions

We use semantic versioning (`vMAJOR.MINOR.PATCH`) for releases.

For open-source Ansible collections, we generally support:

- The **latest released MAJOR version** (e.g. `1.x`) – receives bug fixes and
  security-relevant updates.
- **Pre-1.0 releases** (`0.x`) are considered experimental and may only receive
  best-effort fixes.

Older MAJOR versions are not actively maintained. If you depend on an older
version, we strongly recommend upgrading to the latest MAJOR/MINOR release.

> Note: Collections that have not yet reached `1.0.0` are still evolving. In
> that phase, breaking changes may occur more frequently.

## Reporting a vulnerability

If you believe you have found a security issue in this project, please **do not
open a public GitHub issue**.

Instead, use one of the following channels:

1. **GitHub Security Advisories**

   - Go to the repository on GitHub.
   - Open the **Security** tab.
   - Use the **“Report a vulnerability”** flow to create a private advisory.

2. **Email (for sensitive reports)**

   If you prefer, you can contact us via email:

   - `security@l-it.io` (preferred)
   - Please include:
     - A short description of the issue.
     - A minimal, reproducible example if possible.
     - Which versions you have tested (e.g. `1.2.3` of the collection).

We aim to:

- Acknowledge receipt of your report within **3 business days**.
- Provide an initial assessment and next steps within **10 business days**.
- Coordinate disclosure timing with you, especially if the issue is severe or
  widely exploitable.

## Scope

This policy applies to:

- The source code in this repository (Ansible roles, playbooks, plugins).
- CI tooling and automation that ship as part of the collection or are
  documented for production-like usage.

Out of scope (but still welcome as feedback):

- Misconfigurations in local test environments (e.g. Vagrant, Molecule labs).
- Issues caused by third-party components (e.g. RHEL/OCP bugs, Terraform
  providers), unless the collection clearly misuses them.

If you are unsure whether an issue is in scope, please err on the side of
reporting it privately – we will clarify and redirect if needed.
