# Incus test environments

Supported profile scenarios run host-native against Incus. The shared lifecycle
under `molecule/shared/incus/` creates and destroys exact-owned instances and one
managed bridge per matrix cell.

## Identity and ownership

CI instance names incorporate scenario, workflow run, attempt, and target. The
bridge name is deterministic for the complete exact-owner value (`lit` plus the
first 12 hexadecimal characters of its SHA-256 digest) and remains within the
Linux interface-name limit. Every instance and bridge carries the generic
`user.lit-molecule-owner` label plus repository, run, attempt, scenario, and
target labels. A compatibility owner label may also be written for a specialized
scenario.

Creation refuses an existing instance or bridge owned by another run. Labels are
part of the `incus init` and `incus network create` requests, so there is no
unowned interval after resource creation. Each instance receives a local `eth0`
attachment to the exact-owned bridge before it can start. Reruns may reconcile
only resources with both expected owner labels. Never use unfiltered stale
cleanup on a shared runner.

When no owner is exported for a local Molecule invocation, the generated run ID
is atomically persisted in a private, context-hashed file below
`$MOLECULE_EPHEMERAL_DIRECTORY/lit-incus-lifecycle/`. A later standalone
`molecule destroy` with the same scenario and instance name reuses that ID. The
file rejects symlinks, unexpected content, foreign ownership, and permissive
modes; it is removed only after destroy proves that no exact-owned resource
remains. Protected CI always supplies an explicit owner and does not use this
fallback.

The bridge uses Incus-managed IPv4 DHCP and NAT, disables IPv6, and lets Incus
select a non-conflicting subnet. The former guest-side `10.248.82.0/24` setup ran
after instance start and was not safe for concurrent cells; it is retired. Tests
must not replace routes or `/etc/resolv.conf` manually.

### Host firewall interoperability

Incus and another nftables controller can both accept a packet, but a later
firewall chain can still reject it. Incus documents that this can break DHCP,
DNS, and external access and recommends placing the bridge in firewalld's
`trusted` zone. See [How to configure your firewall](https://linuxcontainers.org/incus/docs/main/howto/network_bridge_firewalld/).

The test lifecycle applies that guidance without changing permanent host state.
When `firewalld.service` is active, it disables Incus filtering only for the
exact-owned bridge, records the selected controller and zone on that bridge,
refuses a conflicting pre-existing interface binding, and adds the exact bridge
to an existing zone at runtime. Destroy verifies the recorded owner and zone,
removes the runtime binding before attempting network deletion, and records the
result. It never passes `--permanent`, reloads firewalld, or changes `incusbr0`.
Hosts without active firewalld continue to use Incus filtering unchanged.

The stock `trusted` zone permits guests on that one bridge to reach host
services, not only DHCP and DNS. This is an explicit tradeoff in firewalld's
documented bridge integration. Its exposure is bounded to a collision-resistant
per-run interface containing only declared exact-owned instances, protected
runner execution, and the runtime from create through destroy. Operators with a
pre-existing restrictive zone and forwarding policy can select it with
`MOLECULE_INCUS_FIREWALLD_ZONE`; the lifecycle validates that the zone already
exists and does not create persistent policy. The selected zone must allow DHCP
and DNS to the host and outbound forwarding/NAT. An interrupted run can leave a
runtime-only binding until firewalld reload or host reboot; rerunning destroy
with the same exact owner removes it deterministically.

After instance start, create waits for an Incus-managed IPv4 lease and then
proves a guest default route and IPv4 DNS resolution. `MOLECULE_INCUS_DNS_PROBE`
can select an approved DNS probe name. A host firewall that is neither inactive
nor covered by the firewalld integration fails these readiness checks instead of
surfacing later as an empty apt-cache error.

## Preflight

Before create, validate:

- Incus client/daemon availability and the requested image;
- available disk and memory against profile limits;
- `/dev/kvm` when `type: vm` is selected;
- target architecture and intentional container-versus-VM choice; and
- required outbound package/image access.

If firewalld is active, the runner identity also needs non-interactive privilege
for runtime-only `firewall-cmd` interface binding and removal. Do not grant
permission for permanent zone or policy changes to the test workflow.

Tiny uses the smallest sufficient container. Heavy/Acceptance use a VM only
when kernel behavior, full systemd fidelity, nested virtualization, or operating
system fidelity requires one. CPU, memory, and disk limits are explicit in the
scenario matrix.

## Execution

```bash
incus version
incus info
python3 scripts/validate-role-coverage.py matrix --profile heavy
# First export the ephemeral identity and secrets from docs/testing/keycloak.md.
run_keycloak_profile keycloak-heavy
```

RHEL image variables must reference approved, entitlement-compliant images.
Missing images fail as `infrastructure-error`; an Ubuntu substitute must never
make a RHEL cell pass.

Expensive environments use concurrency controls. Evidence is captured before
cleanup, including failure paths. Network ready, attachment, pre-destroy, and
post-destroy records are stored below
`$MOLECULE_TEST_ARTIFACTS/incus-lifecycle/<scenario>/<target>/`. Destroy enumerates
labels, removes only exact-owner matches, retains foreign resources, and fails if
any exact-owned instance or bridge remains.

For a concurrent local run, set a unique instance name while keeping one owner
value for create, cleanup, and destroy:

```bash
export MOLECULE_TEST_OWNER="local/${USER}/$(date -u +%Y%m%dT%H%M%S)-rsyslog"
export MOLECULE_TEST_INSTANCE="rsyslog-${USER}-$$"
export MOLECULE_TEST_TARGET=ubuntu-24.04
molecule test -s rsyslog-lifecycle-incus_heavy
```

If a run is interrupted, rerun `molecule destroy -s <scenario>` with the same
instance-name environment. The persisted local identity selects only that run's
resources. If you supplied an explicit owner, export the same value again. Do
not delete a name based on convention alone; verify the exact label.
