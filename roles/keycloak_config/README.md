# keycloak_config

Runtime configuration wrapper for Keycloak deployment variables.

The role is skipped by default. When enabled, it maps config-layer values into
`keycloak_deploy` variables and re-runs `keycloak_deploy` to render/apply the
runtime manifest.
