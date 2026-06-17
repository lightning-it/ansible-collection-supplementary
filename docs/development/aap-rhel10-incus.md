# AAP RHEL 10 Incus Development

The legacy `deploy/incus` shell workflow was removed.

Use the Ansible-based Incus lifecycle instead:

- `lit.ubuntu.incus_instance` owns Incus instance create/start/stop/delete,
  cloud-init SSH keys, device configuration, and generated inventory.
- `lit.rhel.*` roles own RHEL registration, repositories, guest preparation,
  Podman, and generic RHEL host state.
- `lit.supplementary.aap_prepare` owns AAP bundle and manifest staging.
- `lit.supplementary.aap_deploy` owns AAP installer inventory rendering and the
  AAP 2.7 installer run.

Do not recreate shell helpers in this repository. New protected Incus validation
should be implemented as Ansible playbooks or runbooks that compose the roles
above.
