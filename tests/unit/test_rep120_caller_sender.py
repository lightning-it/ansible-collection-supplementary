"""Offline caller negatives and real Linux loopback TLS; never hosted evidence."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import socket
import ssl
import struct
import subprocess
import threading
import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from scripts import rep120_caller_sender as sender
from tests.unit.test_rep120_caller_contract import context

JWT_CANARY = "synthetic-canary.signature.not-authenticated"
OIDC_URL = "https://fixture.actions.githubusercontent.com/uuid/_apis/distributedtask/hubs/actions/plans/plan/jobs/job/idtoken?api-version=2.0"
PUBLIC = "-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n"


def environment():
    return context() | {"ACTIONS_ID_TOKEN_REQUEST_URL": OIDC_URL, "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "runner-canary"}


def envelope():
    return {
        "schema": sender.SCHEMA,
        "nonce": "b" * 64,
        "operation_key": "c" * 64,
        "config_sha256": "d" * 64,
        "source_sha": "a" * 40,
        "resource_sha256": "e" * 64,
        "request": {
            "expected_head": "f" * 40,
            "operation_key": "c" * 64,
            "path": None,
            "contents": None,
            "run_id": 123,
            "approval_id": 456,
            "expires_at": int(time.time()) + 90,
        },
    }


def delivery():
    return {
        "ipv4": "127.0.0.1",
        "port": 1234,
        "public_pem": PUBLIC,
        "leaf_sha256": "a" * 64,
        "expires_at": int(time.time()) + 100,
    }


def ack():
    return {
        "schema": sender.SCHEMA,
        "state": "transport-complete",
        "operation_key": "c" * 64,
        "hosted_acceptance": False,
    }


def frame(value):
    body = sender.canonical(value)
    return sender.MAGIC + struct.pack("!I", len(body)) + body + sender.TRAILER


class InputTests(unittest.TestCase):
    def test_unadmitted_dispatcher_and_unprotected_ref_have_no_effects(self):
        mutations: dict[str, list[Any]] = {
            "GITHUB_ACTOR": ["other", "Litroc", "litroc ", "litroc[bot]", ""],
            "GITHUB_ACTOR_ID": ["76040633", "076040632", 76040632, ""],
            "GITHUB_TRIGGERING_ACTOR": ["other", "Litroc", "litroc ", "litroc[bot]", ""],
            "GITHUB_REF_PROTECTED": ["false", "True", "1", True, ""],
        }
        with (
            patch.object(sender.ssl, "SSLContext"),
            patch.object(sender.socket, "socket") as connect,
            patch.object(sender, "fetch_oidc") as fetch,
        ):
            for key, values in mutations.items():
                for value in values:
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        sender.send_once(delivery(), envelope(), environment() | {key: value})
                missing = environment()
                del missing[key]
                with self.subTest(missing=key), self.assertRaises(ValueError):
                    sender.send_once(delivery(), envelope(), missing)
            connect.assert_not_called()
            fetch.assert_not_called()

    def test_valid_inputs_and_only_actual_run_id_is_filled(self):
        original = envelope()
        original["request"]["run_id"] = None
        before = copy.deepcopy(original)
        bound = sender.bind_run(original, environment())
        self.assertEqual(original, before)
        self.assertEqual(bound, before | {"request": before["request"] | {"run_id": 123}})
        sender.validate_inputs(delivery(), bound, environment(), time.time())
        for value in (123, "123", True):
            original["request"]["run_id"] = value
            with self.assertRaises(sender.Held):
                sender.bind_run(original, environment())

    def test_delivery_and_envelope_drift_never_open_socket_or_fetch_oidc(self):
        cases: list[tuple[dict[str, Any], dict[str, Any], dict[str, str]]] = []
        mutations: dict[str, list[Any]] = {
            "ipv4": ["example.com", "127.00.0.1", "::1", 1],
            "port": [0, 65536, True, "443"],
            "public_pem": ["", "PRIVATE KEY", PUBLIC * 2],
            "leaf_sha256": [None, "A" * 64, "a" * 63],
            "expires_at": [0, True, int(time.time()) + 301],
        }
        for key, values in mutations.items():
            cases.extend((delivery() | {key: value}, envelope(), environment()) for value in values)
        for key in sender.DELIVERY_FIELDS:
            value = delivery()
            del value[key]
            cases.append((value, envelope(), environment()))
        cases.extend(
            (delivery(), envelope() | {key: value}, environment())
            for key, value in (
                ("oidc", JWT_CANARY),
                ("schema", "wrong"),
                ("source_sha", "b" * 40),
                ("nonce", "b" * 63),
                ("request", []),
            )
        )
        for key, value in (
            ("run_id", 124),
            ("run_id", True),
            ("expires_at", 0),
            ("approval_id", True),
            ("operation_key", "a" * 64),
            ("expected_head", "F" * 40),
            ("path", "../escape"),
            ("contents", "x"),
            ("extra", "not allowed"),
        ):
            value_envelope = envelope()
            value_envelope["request"][key] = value
            cases.append((delivery(), value_envelope, environment()))
        for key, value in (
            ("GITHUB_EVENT_NAME", "push"),
            ("GITHUB_RUN_ATTEMPT", "2"),
            ("GITHUB_REF", "refs/heads/develop"),
        ):
            cases.append((delivery(), envelope(), environment() | {key: value}))
        with patch.object(sender.socket, "socket") as connect, patch.object(sender, "fetch_oidc") as fetch:
            for supplied, message, env in cases:
                with self.subTest(case=len(str(supplied))), self.assertRaises(ValueError):
                    sender.send_once(supplied, message, env)
            connect.assert_not_called()
            fetch.assert_not_called()

    def test_duplicate_nonfinite_and_oversize_json_rejected(self):
        for value in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b"[]", b"\xff"):
            with self.subTest(value=value), self.assertRaises(sender.Held):
                sender.decode(value)
        with self.assertRaises(sender.Held):
            sender.canonical({"x": "a" * sender.MAX_BODY})

    def test_default_and_failure_output_are_fixed_and_secret_free(self):
        for values in ({}, {"REP120_DELIVERY": JWT_CANARY, "REP120_ENVELOPE": JWT_CANARY}):
            out, error = io.StringIO(), io.StringIO()
            with (
                patch.dict(os.environ, values | {"GH_TOKEN": JWT_CANARY}, clear=True),
                patch.object(sender.sys, "argv", ["sender"]),
            ):
                with patch.object(sender.resource, "setrlimit"), patch.object(sender, "send_once") as send:
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(error):
                        self.assertEqual(sender.main(), 2)
                    send.assert_not_called()
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(error.getvalue(), "REP120 one-shot caller held [INPUT_CONTEXT]; no retry or acceptance.\n")
            self.assertNotIn(JWT_CANARY, error.getvalue())


class OidcTests(unittest.TestCase):
    def test_fixed_audience_and_strict_official_endpoint(self):
        host, path = sender.oidc_endpoint(OIDC_URL)
        self.assertEqual(host, "fixture.actions.githubusercontent.com")
        self.assertIn("audience=lit-rep120-ledger%3A1413923700%3Aoperation-ledger-core", path)
        for url in (
            OIDC_URL.replace("https:", "http:"),
            OIDC_URL.replace(".com/", ".com.evil/"),
            OIDC_URL.replace("https://", "https://user@"),
            OIDC_URL.replace(".com/", ".com:444/"),
            OIDC_URL + "#fragment",
            OIDC_URL + "&audience=evil",
            OIDC_URL + "&api-version=2.0",
            OIDC_URL.replace("/idtoken?", "/other?"),
            OIDC_URL.replace("fixture.actions.githubusercontent.com", "127.0.0.1"),
            OIDC_URL + "\n",
            OIDC_URL.replace("?api-version=2.0", "?api-version=1.0"),
        ):
            with self.subTest(url=url), self.assertRaises(sender.Held):
                sender.oidc_endpoint(url)

    def response(self, status=200, body=None):
        response = MagicMock()
        response.status = status
        response.read1.side_effect = [body if body is not None else json.dumps({"value": JWT_CANARY}).encode(), b""]
        connection = MagicMock()
        connection.getresponse.return_value = response
        return connection

    def test_one_direct_oidc_get_no_proxy_or_retry(self):
        connection = self.response()
        env = environment() | {"HTTPS_PROXY": "http://invalid-proxy", "HTTP_PROXY": "http://invalid-proxy"}
        with patch.object(sender.http.client, "HTTPSConnection", return_value=connection) as factory:
            self.assertEqual(sender.fetch_oidc(env, time.monotonic() + 10), JWT_CANARY)
        factory.assert_called_once()
        connection.request.assert_called_once()
        args, kwargs = connection.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer runner-canary")
        connection.close.assert_called_once()

    def test_ambient_tls_keylog_and_trust_overrides_are_not_used(self):
        connection = self.response()
        with patch.dict(os.environ, {"SSLKEYLOGFILE": "/forbidden-keylog", "SSL_CERT_FILE": "/forbidden-ca"}):
            with patch.object(sender.ssl, "create_default_context") as ambient:
                with patch.object(sender.http.client, "HTTPSConnection", return_value=connection) as factory:
                    self.assertEqual(sender.fetch_oidc(environment(), time.monotonic() + 10), JWT_CANARY)
                ambient.assert_not_called()
                tls = factory.call_args.kwargs["context"]
                self.assertIsNone(tls.keylog_filename)
                self.assertTrue(tls.check_hostname)
                self.assertEqual(tls.verify_mode, ssl.CERT_REQUIRED)

    def test_redirect_error_malformed_oversize_response_never_retries_or_echoes(self):
        for status, body in (
            (302, b""),
            (307, b""),
            (403, JWT_CANARY.encode()),
            (200, b'{"value":"x","value":"y"}'),
            (200, b'{"value":"x"}'),
            (200, json.dumps({"value": JWT_CANARY, "extra": JWT_CANARY}).encode()),
            (200, json.dumps({"value": "a" * (sender.MAX_OIDC + 1)}).encode()),
            (200, b"x" * (sender.MAX_OIDC_RESPONSE + 1)),
        ):
            connection = self.response(status, body)
            with (
                self.subTest(status=status, size=len(body)),
                patch.object(sender.http.client, "HTTPSConnection", return_value=connection),
            ):
                with self.assertRaises(sender.Held) as result:
                    sender.fetch_oidc(environment(), time.monotonic() + 10)
                self.assertEqual(str(result.exception), "OIDC request held")
                connection.request.assert_called_once()
                connection.close.assert_called_once()


class TransportTests(unittest.TestCase):
    def test_untrusted_or_missing_stage_never_enters_main_output(self):
        for malformed in (False, True):
            error = sender.StageHeld(sender.HoldStage.ACK) if malformed else RuntimeError(JWT_CANARY)
            if malformed:
                error.__dict__["stage"] = JWT_CANARY
            message = envelope()
            message["request"]["run_id"] = None
            values = environment() | {
                "REP120_DELIVERY": json.dumps(delivery()),
                "REP120_ENVELOPE": json.dumps(message),
            }
            out, stderr = io.StringIO(), io.StringIO()
            with (
                self.subTest(malformed=malformed),
                patch.dict(os.environ, values, clear=True),
                patch.object(sender.sys, "argv", ["sender"]),
                patch.object(sender.resource, "setrlimit"),
                patch.object(sender, "send_once", side_effect=error) as send,
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(stderr),
            ):
                self.assertEqual(sender.main(), 2)
                send.assert_called_once()
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(
                stderr.getvalue(), "REP120 one-shot caller held [INPUT_CONTEXT]; no retry or acceptance.\n"
            )
            self.assertNotIn(JWT_CANARY, stderr.getvalue())

    def test_main_reports_only_fixed_stage_codes_without_retry_or_disclosure(self):
        for stage, failing_point in (
            ("INPUT_CONTEXT", "context"),
            ("OIDC_CAPABILITY", "capability"),
            ("TCP", "connect"),
            ("TLS", "certificate"),
            ("TLS", "handshake"),
            ("OIDC_GET", "fetch"),
            ("INPUT_CONTEXT", "revalidation"),
            ("SEND", "send"),
            ("ACK", "ack"),
            ("ACK", "cleanup"),
        ):
            with self.subTest(stage=stage, failing_point=failing_point):
                raw, secure, context_mock = MagicMock(), MagicMock(), MagicMock()
                secure.getpeercert.return_value = b"test leaf"
                secure.version.return_value = "TLSv1.3"
                context_mock.wrap_socket.return_value = secure
                supplied = delivery() | {"leaf_sha256": hashlib.sha256(b"test leaf").hexdigest()}
                message = envelope()
                message["request"]["run_id"] = None
                values = environment() | {
                    "REP120_DELIVERY": json.dumps(supplied),
                    "REP120_ENVELOPE": json.dumps(message),
                }
                error = RuntimeError(JWT_CANARY + OIDC_URL + json.dumps(message))
                out, stderr = io.StringIO(), io.StringIO()
                with (
                    patch.dict(os.environ, values, clear=True),
                    patch.object(sender.sys, "argv", ["sender"]),
                    patch.object(sender.resource, "setrlimit"),
                    patch.object(sender.ssl, "SSLContext", return_value=context_mock),
                    patch.object(sender.socket, "socket", return_value=raw) as factory,
                    patch.object(
                        sender, "oidc_capability", return_value=("host", "path", "runner-canary")
                    ) as capability,
                    patch.object(sender, "fetch_oidc", return_value=JWT_CANARY) as fetch,
                    patch.object(sender, "read_ack", return_value=ack()) as read,
                    patch.object(sender, "validate_inputs", wraps=sender.validate_inputs) as validate,
                ):
                    if failing_point == "context":
                        values["GITHUB_ACTOR"] = JWT_CANARY
                        os.environ["GITHUB_ACTOR"] = JWT_CANARY
                    elif failing_point == "capability":
                        capability.side_effect = error
                    elif failing_point == "connect":
                        raw.connect.side_effect = error
                    elif failing_point == "certificate":
                        context_mock.load_verify_locations.side_effect = error
                    elif failing_point == "handshake":
                        secure.do_handshake.side_effect = error
                    elif failing_point == "fetch":
                        fetch.side_effect = error
                    elif failing_point == "revalidation":
                        validate.side_effect = [None, error]
                    elif failing_point == "send":
                        secure.sendall.side_effect = error
                    elif failing_point == "cleanup":
                        raw.close.side_effect = error
                    else:
                        read.side_effect = error
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(stderr):
                        self.assertEqual(sender.main(), 2)
                    self.assertLessEqual(factory.call_count, 1)
                    self.assertLessEqual(raw.connect.call_count, 1)
                    self.assertLessEqual(fetch.call_count, 1)
                    self.assertLessEqual(secure.sendall.call_count, 1)
                    if failing_point in {"context", "capability", "connect", "certificate", "handshake"}:
                        fetch.assert_not_called()
                        secure.sendall.assert_not_called()
                    if failing_point in {"context", "capability"}:
                        factory.assert_not_called()
                    if factory.called:
                        raw.close.assert_called_once()
                self.assertEqual(out.getvalue(), "")
                self.assertEqual(stderr.getvalue(), f"REP120 one-shot caller held [{stage}]; no retry or acceptance.\n")
                for private in (JWT_CANARY, OIDC_URL, "runner-canary", json.dumps(message)):
                    self.assertNotIn(private, out.getvalue() + stderr.getvalue())

    def test_bad_pin_and_handshake_never_request_token_or_send_application_bytes(self):
        for fail_handshake in (False, True):
            raw, secure, context_mock = MagicMock(), MagicMock(), MagicMock()
            secure.getpeercert.return_value = b"wrong leaf"
            secure.version.return_value = "TLSv1.3"
            if fail_handshake:
                secure.do_handshake.side_effect = ssl.SSLError(JWT_CANARY)
            context_mock.wrap_socket.return_value = secure
            with (
                patch.object(sender.ssl, "SSLContext", return_value=context_mock),
                patch.object(sender.socket, "socket", return_value=raw),
            ):
                with patch.object(sender, "fetch_oidc") as fetch, self.assertRaises(sender.Held) as result:
                    sender.send_once(delivery(), envelope(), environment())
                self.assertEqual(str(result.exception), "one-shot caller held; no retry")
                fetch.assert_not_called()
                secure.sendall.assert_not_called()
                raw.connect.assert_called_once_with(("127.0.0.1", 1234))
                secure.close.assert_called_once()
                raw.close.assert_called_once()

    def test_ack_truncation_size_and_acceptance_are_rejected(self):
        variants = [
            b"wrong",
            sender.MAGIC + struct.pack("!I", 4097),
            frame(ack() | {"hosted_acceptance": True}),
            frame(ack() | {"hosted_acceptance": 0}),
            frame(ack() | {"operation_key": "d" * 64}),
            frame(ack())[:-1],
        ]
        for data in variants:
            stream = MagicMock()
            source = io.BytesIO(data)
            stream.recv.side_effect = source.read
            with self.subTest(length=len(data)), self.assertRaises(sender.Held):
                sender.read_ack(stream, "c" * 64, time.monotonic() + 1)

    def test_deadline_is_terminal(self):
        with self.assertRaises(sender.Held):
            sender.remaining(time.monotonic() - 1)

    def tls_exchange(self, bad_pin=False, bad_hostname=False):
        # Private fixture key stays in Linux memfd only; no key in repo/log/argv.
        key, cert = (os.memfd_create("sender-test", os.MFD_CLOEXEC) for _index in range(2))
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        results: list[str] = []
        thread = None
        try:
            name = "wrong-peer" if bad_hostname else sender.PEER_NAME
            generated = subprocess.run(  # noqa: S603 -- Fixed OpenSSL/test-owned memfds and peer names; no shell.
                [
                    "/usr/bin/openssl",
                    "req",
                    "-new",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-sha256",
                    "-nodes",
                    "-days",
                    "1",
                    "-config",
                    "/dev/null",
                    "-subj",
                    "/CN=" + name,
                    "-addext",
                    "subjectAltName=DNS:" + name,
                    "-keyout",
                    f"/proc/self/fd/{key}",
                    "-out",
                    f"/proc/self/fd/{cert}",
                ],
                pass_fds=(key, cert),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin", "LANG": "C"},
                timeout=10,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, "fixture generation failed")
            pem = os.pread(cert, 16384, 0).decode("ascii")
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.minimum_version = ssl.TLSVersion.TLSv1_3
            tls.load_cert_chain(f"/proc/self/fd/{cert}", f"/proc/self/fd/{key}")
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)

            def peer():
                try:
                    with listener.accept()[0] as raw:
                        raw.settimeout(5)
                        with tls.wrap_socket(raw, server_side=True) as stream:
                            deadline = time.monotonic() + 5
                            self.assertEqual(sender.read_exact(stream, len(sender.MAGIC), deadline), sender.MAGIC)
                            size = struct.unpack("!I", sender.read_exact(stream, 4, deadline))[0]
                            self.assertLessEqual(size, sender.MAX_BODY)
                            message = sender.decode(sender.read_exact(stream, size, deadline))
                            self.assertEqual(sender.read_exact(stream, len(sender.TRAILER), deadline), sender.TRAILER)
                            self.assertEqual(message, envelope_value | {"oidc": JWT_CANARY})
                            results.append("frame-verified")
                            stream.sendall(frame(ack()))
                except (OSError, sender.Held):
                    results.append("held-before-frame" if bad_pin or bad_hostname else "fixture-failed")
                except Exception:
                    results.append("fixture-failed")

            envelope_value = envelope()
            supplied = delivery() | {
                "port": listener.getsockname()[1],
                "public_pem": pem,
                "leaf_sha256": "0" * 64 if bad_pin else hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest(),
            }
            thread = threading.Thread(target=peer)
            thread.start()
            with patch.object(sender, "fetch_oidc", return_value=JWT_CANARY) as fetch:
                if bad_pin or bad_hostname:
                    with self.assertRaises(sender.Held):
                        sender.send_once(supplied, envelope_value, environment())
                    fetch.assert_not_called()
                else:
                    self.assertEqual(sender.send_once(supplied, envelope_value, environment()), ack())
                    fetch.assert_called_once()
                    self.assertNotIn("oidc", envelope_value)
            thread.join(6)
            self.assertFalse(thread.is_alive(), "fixture must terminate")
            self.assertEqual(results, ["held-before-frame" if bad_pin or bad_hostname else "frame-verified"])
        finally:
            listener.close()
            if thread is not None:
                thread.join(6)
            os.close(key)
            os.close(cert)

    def test_real_linux_tls_frame_compatible_and_ack_not_acceptance(self):
        self.tls_exchange()

    def test_real_linux_tls_wrong_pin_rejects_before_oidc(self):
        self.tls_exchange(bad_pin=True)

    def test_real_linux_tls_wrong_hostname_rejects_before_oidc(self):
        self.tls_exchange(bad_hostname=True)


if __name__ == "__main__":
    unittest.main()
