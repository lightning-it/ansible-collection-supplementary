"""Execute the rendered trust initializer and check optional pod isolation."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import init_plugin_loader
from ansible.template import Templar
from jinja2 import FileSystemLoader

ROLE = Path(__file__).resolve().parents[2] / 'roles/guacamole_deploy'


class GuacdTrustTests(unittest.TestCase):
    def render(self, enabled):
        init_plugin_loader()
        values = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        values.update(guacamole_deploy_secrets={'db_password': 'synthetic-test-only'},
                      guacamole_deploy_guacd_ca_certificate='reviewed-public-ca\n' if enabled else '',
                      guacamole_deploy_host_aliases=[{'ip': '10.1.2.3', 'hostnames': ['desktop.example.test']}]
                      if enabled else [])
        engine = Templar(DataLoader(), values)
        values = engine.template(values)
        engine.environment.loader = FileSystemLoader(str(ROLE / 'templates'))
        text = engine.environment.get_template('guacamole-pod.yml.j2').render(**values)
        return yaml.safe_load(text)['spec']

    def test_default_does_not_modify_guacd_stock_trust_or_dns(self):
        spec = self.render(False)
        self.assertNotIn('hostAliases', spec)
        self.assertNotIn('guacd-trust', [item['name'] for item in spec['initContainers']])
        guacd = next(item for item in spec['containers'] if item['name'] == 'guacd')
        self.assertNotIn('volumeMounts', guacd)

    def test_rendered_initializer_preserves_stock_ca_and_adds_only_public_ca(self):
        spec = self.render(True)
        init = next(item for item in spec['initContainers'] if item['name'] == 'guacd-trust')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stock = root / 'stock.pem'
            stock.write_text('stock-ca-one\nstock-ca-two\n')
            (root / 'issuer-ca.pem').write_text('reviewed-public-ca\n')
            script = init['args'][0].replace('/trust/', str(root) + '/')
            subprocess.run(['/bin/sh', '-ec', script], env={**os.environ, 'GUACD_STOCK_CA_BUNDLE': str(stock)},
                           check=True, capture_output=True)
            self.assertEqual((root / 'ca-certificates.crt').read_text(),
                             'stock-ca-one\nstock-ca-two\n\nreviewed-public-ca\n')
            self.assertEqual(stock.read_text(), 'stock-ca-one\nstock-ca-two\n')
        guacd = next(item for item in spec['containers'] if item['name'] == 'guacd')
        self.assertEqual(guacd['volumeMounts'], [{'name': 'guacd-trust',
            'mountPath': '/etc/ssl/certs/ca-certificates.crt', 'subPath': 'ca-certificates.crt', 'readOnly': True}])
        self.assertEqual(spec['hostAliases'], [{'ip': '10.1.2.3', 'hostnames': ['desktop.example.test']}])
