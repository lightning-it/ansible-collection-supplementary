# GitHub Copilot review instructions

- Review every change for correctness, security, least privilege, and failure behavior.
- When present, apply all repository-specific guidance in `AGENTS.md` and path-scoped instruction files.
- Treat malformed external input as an error rather than silently coercing it.
- Check that credentials are scoped to the smallest required job.
- Require new or modified third-party GitHub Actions dependencies to use immutable commit SHAs.
- Explain each finding's impact and propose a concrete fix.
- Prefer a regression test for bugs and security issues.

<!-- Managed contract: Codex and Copilot must apply AGENTS.md. -->
<!-- AGENTS_SHA256: a0162704193f51350d43ad4873462490f6ead53919ebb37e07c15ef72dacbf04 -->
