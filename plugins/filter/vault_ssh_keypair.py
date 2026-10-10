# SPDX-License-Identifier: MIT
"""Validate SSH key correspondence in RAM for read-only secret-bundle plans."""

from ansible.errors import AnsibleFilterError
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization


def vault_ssh_keypair_matches(private, public):
    try:
        encoded = private.encode("utf-8")
        if encoded.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----"):
            key = serialization.load_ssh_private_key(encoded, password=None)
        else:
            key = serialization.load_pem_private_key(encoded, password=None)
        expected = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        actual = serialization.load_ssh_public_key(public.encode("utf-8")).public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        return expected == actual
    except (ValueError, TypeError, AttributeError, UnsupportedAlgorithm):
        raise AnsibleFilterError("SSH keypair verification failed") from None


class FilterModule:
    def filters(self):
        return {"vault_ssh_keypair_matches": vault_ssh_keypair_matches}
