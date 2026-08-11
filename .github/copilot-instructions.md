# GitHub Copilot review instructions

- Review every change for correctness, security, least privilege, and failure behavior.
- When present, apply all repository-specific guidance in `AGENTS.md` and path-scoped instruction files.
- Treat malformed external input as an error rather than silently coercing it.
- Check that credentials are scoped to the smallest required job.
- Require new or modified third-party GitHub Actions dependencies to use immutable commit SHAs.
- Explain each finding's impact and propose a concrete fix.
- Prefer a regression test for bugs and security issues.

<!-- Managed contract: Codex and Copilot must apply AGENTS.md. -->
<!-- AGENTS_SHA256: 742ea2cf942da5b1fd856a9008507daa47cf7a5974822a6c16e08e99188bf1c3 -->
