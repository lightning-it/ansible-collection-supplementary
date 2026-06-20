# lit.supplementary.incus_esxi_image

Imports or prepares a private nested ESXi Incus image alias for temporary
vSphere/Packer validation jobs.

This role does not build, download, or distribute VMware ESXi installation
media. It expects private ESXi artifacts that your organization is licensed to
use. The output is a local Incus image alias such as `local:esxi-packer-ci`.

Use `lit.supplementary.incus_nested_esxi` to launch that prepared image as a
temporary ESXi VM.

## Supported Sources

- `metadata` plus optional `rootfs`: imports an existing Incus image artifact
  with `incus image import`.
- `backup`: imports an Incus instance backup, publishes the imported instance as
  an image alias, and optionally deletes the temporary instance.

Configure exactly one source: `incus_esxi_image_metadata` or
`incus_esxi_image_backup`.

## Key Variables

- `incus_esxi_image_alias` (default: `esxi-packer-ci`): Local image alias
  without the `local:` prefix.
- `incus_esxi_image_metadata`: Metadata tarball, directory, or URL for
  `incus image import`.
- `incus_esxi_image_rootfs`: Optional rootfs tarball or qcow2 artifact.
- `incus_esxi_image_backup`: Incus instance backup artifact to import and
  publish.
- `incus_esxi_image_replace` (default: `false`): Replace an existing alias.
- `incus_esxi_image_command_user`: Optional local user for Incus commands.
- `incus_esxi_image_project`: Optional Incus project.
- `incus_esxi_image_backup_storage_pool`: Optional storage pool for backup
  import.
- `incus_esxi_image_cleanup_backup_instance` (default: `true`): Delete the
  temporary backup import instance after publishing.

## Metadata Artifact Example

```yaml
---
- name: Import nested ESXi Incus image
  hosts: incus_hosts
  become: true
  gather_facts: false
  roles:
    - role: lit.supplementary.incus_esxi_image
      vars:
        incus_esxi_image_alias: esxi-packer-ci
        incus_esxi_image_metadata: /srv/incus/images/esxi-packer-ci-metadata.tar.xz
        incus_esxi_image_rootfs: /srv/incus/images/esxi-packer-ci.qcow2
        incus_esxi_image_replace: true
```

## Backup Artifact Example

```yaml
---
- name: Publish nested ESXi backup as an Incus image
  hosts: incus_hosts
  become: true
  gather_facts: false
  roles:
    - role: lit.supplementary.incus_esxi_image
      vars:
        incus_esxi_image_alias: esxi-packer-ci
        incus_esxi_image_backup: /srv/incus/images/esxi-packer-ci-backup.tar.gz
        incus_esxi_image_replace: true
        incus_esxi_image_backup_storage_pool: default
```

## Feeding the Runtime Role

```yaml
---
- name: Launch nested ESXi from prepared image
  hosts: localhost
  connection: local
  gather_facts: false
  roles:
    - role: lit.supplementary.incus_nested_esxi
      vars:
        incus_nested_esxi_image: "{{ incus_esxi_image_result.nested_esxi_image | default('local:esxi-packer-ci') }}"
        incus_nested_esxi_instance_name: esxi-packer-ci-test
        incus_nested_esxi_endpoint: 192.0.2.10
        incus_nested_esxi_username: root
        incus_nested_esxi_password: "{{ lookup('ansible.builtin.env', 'NESTED_ESXI_PASSWORD') }}"
```
