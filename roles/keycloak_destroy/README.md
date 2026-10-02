# keycloak_destroy

Guarded destroy role for Keycloak runtime resources.

The role is dry-run by default. Data and secret removal each require their own
explicit flags.
Execution fails closed for Quadlet-managed deployments until verified persistent-unit removal is implemented.
