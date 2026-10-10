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


def chain_fixture():
    now = datetime.datetime.now(datetime.UTC)
    certificates, keys = [], []
    for index, common_name in enumerate(["Root", "Parent intermediate", "Direct issuer", "localhost"]):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        builder = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(certificates[-1].subject if certificates else name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=1))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=index < 3, path_length=2 - index if index < 3 else None), True)
        )
        if index == 3:
            from cryptography.x509.oid import ExtendedKeyUsageOID

            builder = builder.add_extension(
                x509.SubjectAlternativeName([x509.DNSName("localhost")]), False
            ).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
        certificates.append(builder.sign(keys[-1] if keys else key, hashes.SHA256()))
        keys.append(key)
    chain = [cert.public_bytes(serialization.Encoding.PEM).decode() for cert in reversed(certificates[:-1])]
    return certificates[0], certificates[-1], keys[-1], chain


class CompleteChainTests(unittest.TestCase):
    def test_nested_chain_requires_every_parent_in_order_and_no_duplicates(self):
        _root, leaf, _key, chain = chain_fixture()
        pem = leaf.public_bytes(serialization.Encoding.PEM).decode()
        self.assertTrue(MODULE.vault_pki_chain_is_valid(chain, chain[0]))
        self.assertTrue(MODULE.vault_pki_direct_issuer_matches(pem, chain[0]))
        from ansible.errors import AnsibleFilterError

        for candidate in [
            chain[:1],
            [chain[0], chain[2]],
            list(reversed(chain)),
            chain + [chain[-1]],
            [],
            "not a list",
        ]:
            try:
                accepted = MODULE.vault_pki_chain_is_valid(candidate, chain[0])
            except AnsibleFilterError:
                accepted = False
            self.assertFalse(accepted)
        self.assertFalse(MODULE.vault_pki_chain_is_valid(chain, chain[-1]))


class DependencyMetadataTests(unittest.TestCase):
    def test_collection_builder_discovers_the_fixed_controller_dependency(self):
        import yaml

        root = PATH.parents[2]
        metadata = yaml.safe_load((root / "meta/execution-environment.yml").read_text())
        requirements = root / metadata["dependencies"]["python"]
        self.assertIn("cryptography==50.0.1", requirements.read_text().splitlines())
        galaxy = yaml.safe_load((root / "galaxy.yml").read_text())
        self.assertEqual(str(galaxy["dependencies"]["community.crypto"]), "3.5.0")
        self.assertNotIn("meta", galaxy["build_ignore"])
