"""Exercise the actual Ansible certificate modules and role leaf predicates."""
import datetime
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class LeafValidationTest(unittest.TestCase):
    def exercise(self, ca):
        root = Path(__file__).resolve().parents[2]
        tasks = yaml.safe_load((root / 'roles/vault_pki_certificate/tasks/main.yml').read_text())
        predicates = [t for t in tasks if t['name'] in (
            'Require the valid exact public DNS server identity',
            'Require the protected matching server key pair')]
        self.assertEqual(len(predicates), 2)
        with tempfile.TemporaryDirectory(dir=os.environ['HOME']) as directory:
            directory = Path(directory)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'fixture.example')])
            now = datetime.datetime.now(datetime.timezone.utc)
            builder = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('fixture.example')]), False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False))
            if ca:
                builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            (directory / 'certificate.pem').write_bytes(builder.sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM))
            (directory / 'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            (directory / 'key.pem').chmod(0o600)
            play = [{'hosts':'localhost', 'connection':'local', 'gather_facts':False,
                     'vars':{'vault_pki_certificate_common_name':'fixture.example'},
                     'tasks':[
                         {'name':'Inspect real public fixture', 'community.crypto.x509_certificate_info':{'path':str(directory/'certificate.pem'),'valid_at':{'now':'+0s'}},'register':'vault_pki_certificate_info'},
                         {'name':'Inspect real protected fixture key','community.crypto.openssl_privatekey_info':{'path':str(directory/'key.pem')},'register':'vault_pki_certificate_key_info','no_log':True},
                         *predicates]}]
            path=directory/'play.yml';path.write_text(yaml.safe_dump(play))
            config=directory/'ansible.cfg';config.write_text('[defaults]\n')
            environment={k:v for k,v in os.environ.items() if k!='ANSIBLE_VAULT_PASSWORD_FILE'}
            result=subprocess.run(['ansible-playbook','-i','localhost,',str(path)],capture_output=True,text=True,timeout=60,env={**environment,'ANSIBLE_CONFIG':str(config),'ANSIBLE_REMOTE_TMP':str(directory/'tmp')})
            return result.returncode, result.stdout + result.stderr

    def test_vault_leaf_without_basic_constraints_is_accepted(self):
        code, output = self.exercise(False)
        self.assertEqual(code, 0, output[-2000:])

    def test_certificate_authority_is_rejected(self):
        code, output = self.exercise(True)
        self.assertNotEqual(code, 0)
        self.assertIn('Require the valid exact public DNS server identity', output)


if __name__ == '__main__':
    unittest.main()
