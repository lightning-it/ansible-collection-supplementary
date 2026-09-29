# keycloak_destroy

Guarded destroy role for Keycloak runtime resources.

The role is dry-run by default. An executed destroy removes the persistent
Quadlet service before removing the pod manifest. Data and secret removal each
require their own explicit flags. Set `keycloak_destroy_remove_systemd=false`
only for an explicitly managed external lifecycle controller.
