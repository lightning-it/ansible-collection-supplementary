"""Executable CA pinning, rendered mount, and Java truststore regressions."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from ansible.plugins.filter.core import FilterModule
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[2]


def certificate_fixture(hostname="localhost", future_ca=False):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Offline regression CA")])
    now = datetime.datetime.now(datetime.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + datetime.timedelta(days=1) if future_ca else now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=2))
    )
    ca = builder.add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(key, hashes.SHA256())
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (
        x509.CertificateBuilder()
        .issuer_name(name)
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    return ca, leaf, leaf_key


def fingerprint(certificate):
    digest = certificate.fingerprint(hashes.SHA256()).hex()
    return ":".join(digest[index : index + 2] for index in range(0, len(digest), 2))


class ApplicationJavaTrustTests(unittest.TestCase):
    def render(self, role, extra):
        location = ROOT / "roles" / role
        values = yaml.safe_load((location / "defaults/main.yml").read_text())
        values.update(extra)
        environment = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701 - YAML, not HTML
        environment.filters.update(FilterModule().filters())
        template = "guacamole-pod.yml.j2" if role == "guacamole_deploy" else "keycloak-pod.yml.j2"
        return yaml.safe_load(environment.from_string((location / "templates" / template).read_text()).render(values))

    def test_guacamole_trust_preserves_proxy_and_default_off(self):
        base = {
            "guacamole_deploy_secrets": {"db_password": "offline-fixture-only"},
            "guacamole_deploy_proxy_url": "http://10.20.30.1:3128",
            "guacamole_deploy_no_proxy": ["localhost", "127.0.0.1"],
        }
        for certificate in ("", "PUBLIC_CA_FIXTURE"):
            pod = self.render(
                "guacamole_deploy",
                {**base, "guacamole_deploy_java_ca_certificate": certificate},
            )
            app = next(item for item in pod["spec"]["containers"] if item["name"] == "guacamole")
            values = {item["name"]: item["value"] for item in app["env"]}
            self.assertIn("-Dhttps.proxyHost=10.20.30.1", values["JAVA_TOOL_OPTIONS"])
            self.assertNotIn("OPENID_ENABLED", values)
            init = [item for item in pod["spec"]["initContainers"] if item["name"] == "java-trust"]
            if certificate:
                self.assertEqual(len(init), 1)
                self.assertIn('cp "$JAVA_HOME/lib/security/cacerts"', init[0]["args"][0])
                self.assertIn(
                    "-Djavax.net.ssl.trustStore=/etc/guacamole-trust/cacerts",
                    values["JAVA_TOOL_OPTIONS"],
                )
                self.assertTrue(app["volumeMounts"][0]["readOnly"])
                self.assertTrue(
                    next(volume for volume in pod["spec"]["volumes"] if volume["name"] == "java-trust")[
                        "selinuxRelabel"
                    ]
                )
            else:
                self.assertEqual(init, [])
                self.assertNotIn("javax.net.ssl.trustStore", values["JAVA_TOOL_OPTIONS"])

    def test_rotating_either_pinned_ca_changes_the_transactional_manifest(self):
        base = {"guacamole_deploy_secrets": {"db_password": "offline-fixture-only"}}
        for kind in ("java", "guacd"):
            values = {
                **base,
                f"guacamole_deploy_{kind}_ca_certificate": "PUBLIC_CA_FIXTURE",
                f"guacamole_deploy_{kind}_ca_sha256": ":".join(["11"] * 32),
            }
            before = self.render("guacamole_deploy", values)
            values[f"guacamole_deploy_{kind}_ca_sha256"] = ":".join(["22"] * 32)
            after = self.render("guacamole_deploy", values)
            self.assertNotEqual(before, after)
            self.assertEqual(
                after["metadata"]["annotations"][f"lit.io/{kind}-ca-sha256"],
                values[f"guacamole_deploy_{kind}_ca_sha256"],
            )

    def test_keycloak_public_ca_is_readonly_and_default_off(self):
        base = {
            "keycloak_deploy_db_password_effective": "offline-fixture-only",
            "keycloak_deploy_admin_password_effective": "offline-fixture-only",
        }
        before = self.render(
            "keycloak_deploy",
            {
                **base,
                "keycloak_deploy_trust_ca_certificate": "PUBLIC_CA_FIXTURE",
                "keycloak_deploy_trust_ca_sha256": ":".join(["11"] * 32),
            },
        )
        after = self.render(
            "keycloak_deploy",
            {
                **base,
                "keycloak_deploy_trust_ca_certificate": "PUBLIC_CA_FIXTURE",
                "keycloak_deploy_trust_ca_sha256": ":".join(["22"] * 32),
            },
        )
        self.assertNotEqual(before, after)
        self.assertEqual(after["metadata"]["annotations"]["lit.io/issuer-ca-sha256"], ":".join(["22"] * 32))
        for certificate in ("", "PUBLIC_CA_FIXTURE"):
            pod = self.render(
                "keycloak_deploy",
                {**base, "keycloak_deploy_trust_ca_certificate": certificate},
            )
            app = pod["spec"]["containers"][0]
            values = {item["name"]: item["value"] for item in app["env"]}
            if certificate:
                self.assertEqual(
                    values["KC_TRUSTSTORE_PATHS"],
                    "/opt/keycloak/extra-trust/issuer-ca.pem",
                )
                self.assertTrue(
                    next(item for item in app["volumeMounts"] if item["name"] == "keycloak-trust")["readOnly"]
                )
                self.assertTrue(
                    next(volume for volume in pod["spec"]["volumes"] if volume["name"] == "keycloak-trust")[
                        "selinuxRelabel"
                    ]
                )
            else:
                self.assertNotIn("KC_TRUSTSTORE_PATHS", values)

    def test_real_ca_tasks_reject_wrong_pin_before_writes(self):
        ca, _leaf, _key = certificate_fixture()
        pem = ca.public_bytes(serialization.Encoding.PEM).decode()
        for role, prefix, filename in (
            ("guacamole_deploy", "java", "java_trust.yml"),
            ("keycloak_deploy", "trust", "certificate_trust.yml"),
        ):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                (directory / "java-trust").mkdir()
                base_var = (
                    "guacamole_deploy_base_dir" if role == "guacamole_deploy" else "keycloak_deploy_host_data_dir"
                )
                base_value = str(directory) if role == "guacamole_deploy" else str(directory / "data")
                for matched in (True, False):
                    play = [
                        {
                            "hosts": "localhost",
                            "gather_facts": False,
                            "vars": {
                                base_var: base_value,
                                f"{role}_{prefix}_ca_certificate": pem,
                                f"{role}_{prefix}_ca_sha256": fingerprint(ca) if matched else ":".join(["00"] * 32),
                            },
                            "tasks": [
                                {"ansible.builtin.import_tasks": str(ROOT / "roles" / role / "tasks" / filename)}
                            ],
                        }
                    ]
                    source = directory / "test.yml"
                    source.write_text(yaml.safe_dump(play))
                    config = directory / "ansible.cfg"
                    config.write_text("[defaults]\nstdout_callback=default\n")
                    result = subprocess.run(  # noqa: S603 - trusted fixture commands and fixed tool arguments
                        [
                            shutil.which("ansible-playbook"),
                            "-i",
                            "localhost,",
                            "-c",
                            "local",
                            "--check",
                            str(source),
                        ],
                        env={
                            **os.environ,
                            "ANSIBLE_CONFIG": str(config),
                            "ANSIBLE_NOCOLOR": "1",
                            "ANSIBLE_LOCAL_TEMP": str(directory / "ansible"),
                        },
                        capture_output=True,
                        text=True,
                        timeout=45,
                        check=False,
                    )
                    if matched:
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("exact unexpired reviewed CA", result.stdout)
                    self.assertFalse((directory / "java-trust/issuer-ca.pem").exists())

    def test_all_application_trust_boundaries_refuse_future_pinned_ca_before_writes(self):
        for role, prefix, filename in (
            ("guacamole_deploy", "java", "java_trust.yml"),
            ("guacamole_deploy", "guacd", "guacd_trust.yml"),
            ("keycloak_deploy", "trust", "certificate_trust.yml"),
        ):
            for future in (False, True):
                with self.subTest(role=role, prefix=prefix, future=future), tempfile.TemporaryDirectory() as temporary:
                    directory = Path(temporary)
                    ca, _leaf, _key = certificate_fixture(future_ca=future)
                    pem = ca.public_bytes(serialization.Encoding.PEM).decode()
                    marker = directory / "write-boundary"
                    tasks = yaml.safe_load((ROOT / "roles" / role / "tasks" / filename).read_text())[:2]
                    tasks += [
                        {"ansible.builtin.copy": {"dest": str(marker), "content": "public fixture", "mode": "0600"}}
                    ]
                    source = directory / "test.yml"
                    source.write_text(
                        yaml.safe_dump(
                            [
                                {
                                    "hosts": "localhost",
                                    "gather_facts": False,
                                    "vars": {
                                        f"{role}_{prefix}_ca_certificate": pem,
                                        f"{role}_{prefix}_ca_sha256": fingerprint(ca),
                                    },
                                    "tasks": tasks,
                                }
                            ]
                        )
                    )
                    config = directory / "ansible.cfg"
                    config.write_text("[defaults]\n")
                    result = subprocess.run(  # noqa: S603 - fixed local Ansible command and controlled offline fixture
                        [shutil.which("ansible-playbook"), "-i", "localhost,", "-c", "local", str(source)],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=45,
                        env={
                            **os.environ,
                            "ANSIBLE_CONFIG": str(config),
                            "ANSIBLE_LOCAL_TEMP": str(directory / "ansible"),
                        },
                    )
                    self.assertEqual(result.returncode == 0, not future, result.stdout + result.stderr)
                    self.assertEqual(marker.exists(), not future)

    def test_real_init_command_preserves_stock_java_trust_and_adds_only_pinned_ca(self):
        self.assertIsNotNone(shutil.which("keytool"), "Pinned Devtools keytool required")
        ca, _leaf, _key = certificate_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "issuer-ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
            pod = self.render(
                "guacamole_deploy",
                {
                    "guacamole_deploy_secrets": {"db_password": "offline-fixture-only"},
                    "guacamole_deploy_java_ca_certificate": "PUBLIC_CA_FIXTURE",
                },
            )
            init = next(item for item in pod["spec"]["initContainers"] if item["name"] == "java-trust")
            command = init["args"][0].replace("/trust/", str(directory) + "/")
            keytool = Path(shutil.which("keytool")).resolve()
            java_home = keytool.parent.parent
            self.assertTrue((java_home / "lib/security/cacerts").is_file())
            baseline = subprocess.run(  # noqa: S603 - trusted fixture commands and fixed tool arguments
                [str(keytool), "-list", "-cacerts", "-storepass", "changeit"],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            ).stdout
            # Ubuntu's stock truststore can be read-only; its private copy must
            # become writable before the import and read-only again afterwards.
            fixture_java_home = directory / "jdk"
            stock = fixture_java_home / "lib/security/cacerts"
            stock.parent.mkdir(parents=True)
            shutil.copyfile(java_home / "lib/security/cacerts", stock)
            stock.chmod(0o444)
            java_home = fixture_java_home
            subprocess.run(  # noqa: S603 - trusted fixture commands and fixed tool arguments
                ["/bin/sh", "-ec", command],
                env={**os.environ, "JAVA_HOME": str(java_home)},
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            after = subprocess.run(  # noqa: S603 - trusted fixture commands and fixed tool arguments
                [
                    str(keytool),
                    "-list",
                    "-keystore",
                    str(directory / "cacerts"),
                    "-storepass",
                    "changeit",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            ).stdout
            baseline_aliases = {line.split(",", 1)[0] for line in baseline.splitlines() if "trustedCertEntry" in line}
            after_aliases = {line.split(",", 1)[0] for line in after.splitlines() if "trustedCertEntry" in line}
            self.assertGreater(len(baseline_aliases), 50)
            self.assertEqual(after_aliases - baseline_aliases, {"guacamole-reviewed-ca"})
            self.assertTrue(baseline_aliases.issubset(after_aliases))
            pinned = subprocess.run(  # noqa: S603 - trusted fixture commands and fixed tool arguments
                [
                    str(keytool),
                    "-exportcert",
                    "-rfc",
                    "-alias",
                    "guacamole-reviewed-ca",
                    "-keystore",
                    str(directory / "cacerts"),
                    "-storepass",
                    "changeit",
                ],
                capture_output=True,
                timeout=15,
                check=True,
            ).stdout
            self.assertEqual(
                x509.load_pem_x509_certificate(pinned).fingerprint(hashes.SHA256()),
                ca.fingerprint(hashes.SHA256()),
            )

    def test_applications_refuse_a_second_unreviewed_ca_before_writes(self):
        ca, _leaf, _key = certificate_fixture()
        foreign, _leaf, _key = certificate_fixture()
        pem = ca.public_bytes(serialization.Encoding.PEM).decode()
        extra = foreign.public_bytes(serialization.Encoding.PEM).decode()
        for role, prefix, filename in [
            ("guacamole_deploy", "java", "java_trust.yml"),
            ("guacamole_deploy", "guacd", "guacd_trust.yml"),
            ("keycloak_deploy", "trust", "certificate_trust.yml"),
        ]:
            for bundle in [pem, pem + extra]:
                with (
                    self.subTest(role=role, prefix=prefix, bundle_count=bundle.count("-----BEGIN")),
                    tempfile.TemporaryDirectory(dir=os.environ["HOME"]) as temporary,
                ):
                    directory = Path(temporary)
                    marker = directory / "write-boundary"
                    tasks = yaml.safe_load((ROOT / "roles" / role / "tasks" / filename).read_text())[:2]
                    tasks += [
                        {"ansible.builtin.copy": {"dest": str(marker), "content": "public fixture", "mode": "0600"}}
                    ]
                    source = directory / "test.yml"
                    source.write_text(
                        yaml.safe_dump(
                            [
                                {
                                    "hosts": "localhost",
                                    "gather_facts": False,
                                    "vars": {
                                        f"{role}_{prefix}_ca_certificate": bundle,
                                        f"{role}_{prefix}_ca_sha256": fingerprint(ca),
                                    },
                                    "tasks": tasks,
                                }
                            ]
                        )
                    )
                    config = directory / "ansible.cfg"
                    config.write_text("[defaults]\n")
                    result = subprocess.run(  # noqa: S603 - fixed tool and generated offline fixture
                        [shutil.which("ansible-playbook"), "-i", "localhost,", "-c", "local", str(source)],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=45,
                        env={
                            **os.environ,
                            "ANSIBLE_CONFIG": str(config),
                            "ANSIBLE_LOCAL_TEMP": str(directory / "ansible"),
                        },
                    )
                    self.assertEqual(result.returncode == 0, bundle == pem, result.stdout + result.stderr)
                    self.assertEqual(marker.exists(), bundle == pem)


if __name__ == "__main__":
    unittest.main()
