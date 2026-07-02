# keycloak

Orchestrator role for the Keycloak lifecycle.

It composes preflight, deploy, config, CaC, validation, operations, backup/restore,
upgrade, and destroy roles through boolean switches. Destructive and day-2
operation roles are disabled by default.

See `roles/keycloak/defaults/main.yml`.
