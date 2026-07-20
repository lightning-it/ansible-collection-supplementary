# Local Incus Runner

Use a dedicated Linux x86-64 host with Incus, the profile resources declared by
the generated matrix, outbound package/image access, and nested Podman where
required. Keycloak Heavy/Acceptance currently require at least 8 GiB available
memory and 20 GiB free disk. CI labels include `self-hosted`, `linux`, `x64`,
`incus`, and the component runner label.
VM targets additionally require `/dev/kvm`.

On hosts with active firewalld, the runner must be able to add and remove only
the exact per-run bridge interface in an existing runtime zone. The lifecycle
does not create or persist host firewall policy. The default zone is `trusted`;
its guest-to-host exposure and the restrictive-zone override are documented in
[the shared Incus guide](incus.md#host-firewall-interoperability).

Treat these runners as disposable test infrastructure. Prefer ephemeral or
just-in-time registration, one job per runner, a clean workspace and Incus
project for every job, and destruction after completion. Never place release,
AWS archive, signing, production, or customer credentials on a self-hosted test
runner. Same-repository pull-request heads execute only after the
non-bypassable `ansible-collection-runtime-tests` environment is approved by
the release team. Fork heads are rejected and must be reproduced on a reviewed
same-repository branch. Protected `develop`/`main` runs use the separate
`ansible-collection-runtime-protected` environment. Both paths generate
evidence for the exact executed SHA; only protected-main evidence can proceed
to signing and publication eligibility.

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
unique repository/run/attempt/profile identity, and run the documented scenario.
The shared lifecycle refuses resources owned by another run and deletes only
matching owner labels. Never perform unfiltered stale-resource cleanup on a
shared runner. Candidate/install/package paths include repository, workflow run,
and attempt identity so persistent hosts cannot reuse another run's files. See
[the shared Incus guide](incus.md).
