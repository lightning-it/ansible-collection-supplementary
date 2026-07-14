# External integrations and blockers

The coverage registry distinguishes an unavailable integration from a passing
test. External profiles use dedicated, non-production tenants, licences,
projects, zones, devices, runners, or infrastructure.

| Family | Current blocker | Required test boundary |
|---|---|---|
| AAP | Red Hat entitlement, bundle/manifest, subscribed RHEL lab | Dedicated protected AAP environment |
| Nessus | Tenable test activation/licence | Isolated licensed scanner and safe target |
| Cloudflared | Cloudflare test account, zone, tunnel credentials | Dedicated non-production tunnel/origin |
| Cloudflare WARP | Cloudflare Zero Trust test organization | Dedicated enrolled/revocable test device |
| ESXi/vCenter | Licensed media and isolated nested/physical lab | Reversible non-production resource |

Without the required boundary, the profile is
`blocked-external-license`, `blocked-external-service`, or
`blocked-external-infrastructure`. It must not be skipped and reported as
passed.

Protected credentials live in GitHub environments or the repository-supported
secret provider. Never commit activation codes, Cloudflare credentials, ESXi
licence material, AAP manifests, production tokens, or customer endpoints.

Fork pull requests do not receive protected credentials. External/nightly jobs
must fail closed when configured credentials are invalid; absence is handled by
the registry disposition, not by an ignored command.
