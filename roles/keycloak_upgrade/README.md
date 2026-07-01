# keycloak_upgrade

Upgrade coordinator for Keycloak.

It is dry-run by default. When enabled, it can run a backup, apply a target
Keycloak image through `keycloak_deploy`, and validate the result.
