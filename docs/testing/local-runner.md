# Local Keycloak Incus Runner

Use a dedicated Linux x86-64 host with Incus, at least 8 GiB available memory and
20 GiB free disk for Heavy/Acceptance, outbound package/image access, and nested
Podman. CI labels are `self-hosted`, `linux`, `x64`, `incus`, and `keycloak-test`.
VM targets additionally require `/dev/kvm`.

Set `KEYCLOAK_RHEL9_INCUS_IMAGE` and `KEYCLOAK_RHEL10_INCUS_IMAGE` as repository
variables to approved, entitlement-compliant RHEL images. Empty variables fail
closed during instance creation; CI never substitutes Ubuntu for a RHEL cell.

```bash
incus version
incus info
test -e /dev/kvm || echo "containers only: KVM unavailable"
df -h .
grep MemAvailable /proc/meminfo
```

To reproduce CI, check out its exact commit, select the same target/image, assign
a unique owner and instance, and run the documented scenario. The lifecycle
refuses resources owned by another run and deletes only matching owner labels.
Never perform unfiltered stale-resource cleanup on a shared runner.
