# GitHub Copilot review instructions

- Review every change for correctness, security, least privilege, and failure behavior.
- When present, apply all repository-specific guidance in `AGENTS.md` and path-scoped instruction files.
- Treat malformed external input as an error rather than silently coercing it.
- Check that credentials are scoped to the smallest required job.
- Require new or modified third-party GitHub Actions dependencies to use immutable commit SHAs.
- Explain each finding's impact and propose a concrete fix.
- Prefer a regression test for bugs and security issues.
- Treat `AGENTS.md` as the canonical repository contract. A managed
  `AGENTS_SHA256` marker below binds these instructions to the reviewed
  `AGENTS.md`; instruction drift is a blocking finding.

<!-- Managed contract: Codex and Copilot must apply AGENTS.md. -->
<!-- AGENTS_SHA256: d42f837868d998cc1486db4cf66aa53e4fd7aef6dba99db9124511827e88d7b0 -->
