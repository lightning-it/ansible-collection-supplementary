# netbox_deploy

Deploys a version- and digest-pinned NetBox application pod with isolated
PostgreSQL, Valkey task, and Valkey cache services. Only the NetBox HTTP port is
bound to the host and defaults to loopback. All secret values must be supplied
from a secret boundary such as `vault_secret_bundle`.

When OIDC is enabled, the role renders a private Python configuration fragment
because NetBox Docker does not map every `SOCIAL_AUTH_*` setting directly from
environment variables. The same read-only fragment is mounted into the web and
worker containers; the Keycloak client secret remains `0600` on the host and
must be passed by a `no_log` caller.

OIDC is opt-in. The default allowed-hosts contract permits only local readiness
checks; productive callers must supply their exact public hostname and must not
use a wildcard.
