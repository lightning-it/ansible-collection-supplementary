# SPDX-License-Identifier: MIT
"""Bind a leaf cryptographically to an independently fetched Vault issuer in RAM."""

from datetime import datetime, timezone

from ansible.errors import AnsibleFilterError


def vault_pki_direct_issuer_matches(certificate, issuer):
    try:
        from cryptography import x509
        from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    except ImportError:
        raise AnsibleFilterError("cryptography >= 40 is required for PKI issuer verification") from None
    try:
        leaf = x509.load_pem_x509_certificate(certificate.encode())
        authority = x509.load_pem_x509_certificate(issuer.encode())
        now = datetime.now(timezone.utc)  # noqa: UP017 - Ansible controllers before Python 3.11 remain supported
        if not (
            authority.not_valid_before.replace(tzinfo=timezone.utc)  # noqa: UP017
            <= now
            <= authority.not_valid_after.replace(tzinfo=timezone.utc)  # noqa: UP017
        ):
            return False
        constraints = authority.extensions.get_extension_for_class(x509.BasicConstraints).value
        if not constraints.ca:
            return False
        try:
            if not authority.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign:
                return False
        except x509.ExtensionNotFound:
            pass
        leaf.verify_directly_issued_by(authority)
        return True
    except (ValueError, TypeError, AttributeError, InvalidSignature, UnsupportedAlgorithm, x509.ExtensionNotFound):
        raise AnsibleFilterError("PKI issuer verification failed") from None


def vault_pki_chain_is_valid(chain, issuer):
    """Validate the independently authenticated issuer-to-root chain in order."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
    except ImportError:
        raise AnsibleFilterError("cryptography >= 40 is required for PKI chain verification") from None
    try:
        if not isinstance(chain, list) or not 1 <= len(chain) <= 16:
            return False
        if any(
            not isinstance(pem, str)
            or pem.count("-----BEGIN CERTIFICATE-----") != 1
            or pem.count("-----END CERTIFICATE-----") != 1
            for pem in chain
        ):
            return False
        certificates = [x509.load_pem_x509_certificate(pem.encode()) for pem in chain]
        declared = x509.load_pem_x509_certificate(issuer.encode())
        fingerprints = [certificate.fingerprint(hashes.SHA256()) for certificate in certificates]
        if fingerprints[0] != declared.fingerprint(hashes.SHA256()) or len(set(fingerprints)) != len(fingerprints):
            return False
        for index, authority in enumerate(certificates):
            now = datetime.now(timezone.utc)  # noqa: UP017
            if (
                not authority.not_valid_before.replace(tzinfo=timezone.utc)  # noqa: UP017
                <= now
                <= authority.not_valid_after.replace(tzinfo=timezone.utc)  # noqa: UP017
            ):  # noqa: UP017
                return False
            constraints = authority.extensions.get_extension_for_class(x509.BasicConstraints).value
            if not constraints.ca or (constraints.path_length is not None and index > constraints.path_length):
                return False
            parent = chain[index + 1] if index + 1 < len(chain) else chain[index]
            if not vault_pki_direct_issuer_matches(chain[index], parent):
                return False
        return True
    except (ValueError, TypeError, AttributeError, x509.ExtensionNotFound):
        raise AnsibleFilterError("PKI chain verification failed") from None


class FilterModule:
    def filters(self):
        return {
            "vault_pki_direct_issuer_matches": vault_pki_direct_issuer_matches,
            "vault_pki_chain_is_valid": vault_pki_chain_is_valid,
        }
