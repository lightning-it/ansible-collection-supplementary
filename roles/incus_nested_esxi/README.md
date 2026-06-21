# Incus Nested ESXi Role

Launches a prepared nested ESXi VM image on Incus for temporary VMware API
validation jobs.

This role does not build or distribute ESXi media. It expects a private,
prepared Incus VM image alias that already boots ESXi and exposes a stable
management endpoint.

## Behavior

- validates required inputs
- checks `incus` and `curl` are available on the delegated host
- creates an Incus VM from `incus_nested_esxi_image`
- applies CPU, memory, secure boot, nesting, optional root disk size, and
  optional `raw.qemu`
- waits for the ESXi `/sdk` endpoint
- exposes `incus_nested_esxi_packer_vars` for standalone ESXi Packer builds
- supports `incus_nested_esxi_state: absent` for cleanup

## Example

```yaml
---
- name: Prepare nested ESXi for Packer
  hosts: localhost
  connection: local
  gather_facts: false
  roles:
    - role: lit.supplementary.incus_nested_esxi
      vars:
        incus_nested_esxi_image: local:esxi-packer-ci
        incus_nested_esxi_instance_name: esxi-packer-ci-123
        incus_nested_esxi_endpoint: 192.0.2.10
        incus_nested_esxi_username: root
        incus_nested_esxi_password: "{{ lookup('ansible.builtin.env', 'NESTED_ESXI_PASSWORD') }}"
        incus_nested_esxi_datastore: datastore1
        incus_nested_esxi_network: "VM Network"
```

Use `incus_nested_esxi_state: absent` with the same instance name to destroy the
VM in a cleanup step.
