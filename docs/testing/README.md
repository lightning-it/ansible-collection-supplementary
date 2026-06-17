# Testing

Use these docs:

- [AAP testing](aap.md)

AAP Incus lifecycle code is not kept in this collection. Use
`lit.ubuntu.incus_instance` from `ansible-collection-ubuntu` for Incus guests and
run this collection's AAP roles against the generated RHEL inventory.

Public-safe checks stay in this repository. Protected infrastructure validation
belongs in the consumer validation repository.
