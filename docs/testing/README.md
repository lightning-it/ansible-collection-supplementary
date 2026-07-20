# Enterprise role testing

The collection-wide test model is driven by
[`meta/role-coverage.yml`](../../meta/role-coverage.yml). Every role has an
explicit maturity, platform, Tiny, Heavy, and Application Acceptance
disposition. The generated human-readable inventory is
[`role-coverage.md`](role-coverage.md).

Use these guides:

- [Role coverage and blockers](role-coverage.md)
- [Application Acceptance](application-acceptance.md)
- [Incus lifecycle and runners](incus.md)
- [Audit evidence](evidence.md)
- [Shipped source dependencies](source-dependencies.md)
- [External services, licences, and infrastructure](external-integrations.md)
- [Troubleshooting](troubleshooting.md)
- [Keycloak reference architecture](keycloak.md)
- [AAP protected validation](aap.md)

Production support is intentionally narrower than implementation inventory.
Legacy Basic, partial Heavy, Stub, and Skip-mode scenarios are recorded, but
they do not create a production support claim.

Run policy validation before any scenario:

```bash
python3 scripts/validate-role-coverage.py check
```

Run a profile directly with `molecule test -s <scenario>`. Protected profiles
require a host-native Incus runner; the containerized devtools runner remains
for local light and lint gates.
