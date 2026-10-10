"""A correctly signed leaf cannot authorize an expired or future issuer."""

import datetime
import importlib.util
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

PATH = Path(__file__).resolve().parents[2] / "plugins/filter/vault_pki_issuer.py"
SPEC = importlib.util.spec_from_file_location("vault_pki_issuer", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class IssuerLifetimeTests(unittest.TestCase):
    def test_signature_requires_a_currently_valid_authority(self):
        now = datetime.datetime.now(datetime.UTC)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fixture issuer")])
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fixture.example")]))
            .issuer_name(name)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256())
            .public_bytes(serialization.Encoding.PEM)
            .decode()
        )
        for begin, end, accepted in [(-2, -1, False), (1, 2, False), (-1, 1, True)]:
            with self.subTest(begin=begin, end=end):
                issuer = (
                    x509.CertificateBuilder()
                    .subject_name(name)
                    .issuer_name(name)
                    .public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(now + datetime.timedelta(days=begin))
                    .not_valid_after(now + datetime.timedelta(days=end))
                    .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                    .sign(key, hashes.SHA256())
                    .public_bytes(serialization.Encoding.PEM)
                    .decode()
                )
                self.assertEqual(MODULE.vault_pki_direct_issuer_matches(leaf, issuer), accepted)
