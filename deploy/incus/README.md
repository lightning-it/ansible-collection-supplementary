# Incus AAP Workflow

These scripts provide the active local workflow for AAP development in this collection.
VM mode is the default because the AAP roles depend on guest OS behavior that is closer to a real RHEL system.

Available scripts:

- `deploy/incus/create.sh`
- `deploy/incus/inventory.sh`
- `deploy/incus/wait-for-instance.sh`
- `deploy/incus/destroy.sh`

## Image Alias Resolution

RHEL 9:

- prefer `INCUS_RHEL98_IMAGE`
- otherwise prefer `local:rhel98-ci`
- then fall back to `INCUS_RHEL9_IMAGE`
- then fall back to `local:rhel9-ci`

RHEL 10:

- prefer `INCUS_RHEL10_IMAGE`
- otherwise use `local:rhel10-ci`

## Create Local RHEL Image Aliases

The helper scripts expect private RHEL images to already be present in the
Incus image store. They do not download or publish Red Hat images.
Run these commands as a user that can access Incus, for example a user in the
`incus-admin` group, and confirm `incus info` works first.
VM mode also requires KVM on the Incus host; confirm `/dev/kvm` exists before
creating RHEL VMs.

### Get a RHEL 10 qcow2

Use one of these protected Red Hat sources:

- Download the official RHEL 10 KVM Guest Image from the Red Hat Customer Portal
  Software & Download Center:
  <https://access.redhat.com/downloads>
- Build a custom RHEL 10 KVM guest `.qcow2` with RHEL image builder:
  <https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10/html/composing_a_customized_rhel_system_image/creating-and-deploying-guest-images-wht-image-builder>

The downloaded or built file should be a KVM/cloud guest image in qcow2 format.
Keep it on the Incus host, for example:

```bash
sudo mkdir -p /srv/incus/images
sudo cp /path/to/rhel-10-*-x86_64-kvm.qcow2 /srv/incus/images/rhel-10-cloud.qcow2
sudo chown "$(id -u):$(id -g)" /srv/incus/images/rhel-10-cloud.qcow2
```

Check the required RHEL 10 alias:

```bash
incus image info local:rhel10-ci
```

If you already have Incus image artifacts, import them and assign the alias:

```bash
incus image import /path/to/metadata.tar.xz /path/to/disk.qcow2 \
  --alias rhel10-ci
```

If you have a standalone RHEL 10 cloud qcow2, create a minimal Incus metadata
tarball first:

```bash
workdir="$(mktemp -d)"
cp /srv/incus/images/rhel-10-cloud.qcow2 "$workdir/rootfs.img"
cat > "$workdir/metadata.yaml" <<EOF
architecture: x86_64
creation_date: $(date +%s)
properties:
  os: Red Hat Enterprise Linux
  release: "10"
  description: RHEL 10 cloud image
EOF

tar -C "$workdir" -cJf "$workdir/metadata.tar.xz" metadata.yaml
incus image import "$workdir/metadata.tar.xz" "$workdir/rootfs.img" \
  --alias rhel10-ci
rm -rf "$workdir"
```

Verify the imported image is a VM image:

```bash
incus image list local:rhel10-ci
incus image info local:rhel10-ci | grep -E 'type|description|release'
```

If your alias should point at a different name, keep the image as-is and export
the override before using the scripts:

```bash
export INCUS_RHEL10_IMAGE=local:my-rhel10-image
```

## Common Usage

Create the default validated RHEL 9.8 VM:

```bash
deploy/incus/create.sh --version 9 --vm --name aap-rhel9-dev
```

Use a separate short guest hostname when the Incus instance name needs extra
uniqueness:

```bash
deploy/incus/create.sh --version 9 --vm --name aap-rhel9-dev-123456 --hostname aap-rhel9-dev
```

Print a usable Ansible inventory:

```bash
deploy/incus/inventory.sh aap-rhel9-dev > /tmp/aap-rhel9-dev.yml
```

Use the same short name as inventory alias when needed:

```bash
deploy/incus/inventory.sh aap-rhel9-dev-123456 --host-alias aap-rhel9-dev > /tmp/aap-rhel9-dev.yml
```

Wait for the instance explicitly:

```bash
deploy/incus/wait-for-instance.sh aap-rhel9-dev
```

Destroy the instance:

```bash
deploy/incus/destroy.sh aap-rhel9-dev
```

`destroy.sh` unregisters RHSM from a running RHEL guest before deleting it.
This keeps ephemeral clones from leaving stale Red Hat consumers behind.

Useful teardown overrides:

- `INCUS_RHSM_UNREGISTER_ON_DESTROY=false` skips unregister/clean.
- `INCUS_RHSM_UNREGISTER_STRICT=false` deletes even when unregister fails.

## Environment Variables

- `INCUS_RHEL98_IMAGE`
- `INCUS_RHEL9_IMAGE`
- `INCUS_RHEL10_IMAGE`
- `INCUS_SSH_PUBLIC_KEY_FILE`
- `INCUS_SSH_PRIVATE_KEY_FILE`
- `INCUS_SSH_USER`
- `INCUS_SSH_COMMON_ARGS`
- `INCUS_FQDN_SUFFIX`
- `INCUS_VM_CPU`
- `INCUS_VM_MEMORY`
- `INCUS_VM_ROOT_SIZE`
- `INCUS_WAIT_TIMEOUT`
- `INCUS_RHSM_UNREGISTER_ON_DESTROY`
- `INCUS_RHSM_UNREGISTER_STRICT`

Example env files:

- `deploy/incus/examples/aap-rhel9.env`
- `deploy/incus/examples/aap-rhel10.env`

## Notes

- VM mode is the default validated path.
- Container mode is optional and intended only for fast-path experimentation with images that already provide
  systemd, cloud-init, and SSH.
- The scripts do not download private RHEL images or publish any image content.
- Keep imported RHEL base images unregistered. Use cloud-init for hostname and SSH access only; use
  `playbooks/rhel_prepare.yml` to compose `lit.rhel.rhsm`, `lit.rhel.repos`, and
  `lit.rhel.virtual_guest` for runtime VMs. Use `playbooks/rhel_teardown.yml`
  or `destroy.sh` to unregister them before deletion.
