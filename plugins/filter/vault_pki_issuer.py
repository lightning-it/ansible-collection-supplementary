# SPDX-License-Identifier: MIT
"""Bind a leaf cryptographically to an independently fetched Vault issuer in RAM."""

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


class FilterModule:
    def filters(self):
        return {"vault_pki_direct_issuer_matches": vault_pki_direct_issuer_matches}
