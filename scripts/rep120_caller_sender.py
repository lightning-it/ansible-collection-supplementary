"""One-shot caller transport; no deployment, retry or hosted-acceptance claim."""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import resource
import socket
import ssl
import struct
import sys
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from scripts.rep120_caller_contract import AUDIENCE, REQUEST_FIELDS, inspect_context

MAGIC = b"LIT178T1"
TRAILER = b"LIT178END"
SCHEMA = "lit-li178-one-shot-transport/v1"
MAX_BODY = 1048576
MAX_OIDC = 16384
MAX_OIDC_RESPONSE = 32768
PEER_NAME = "li178-one-shot"
ENVELOPE_FIELDS = {"schema", "nonce", "operation_key", "config_sha256", "source_sha", "resource_sha256", "request"}
DELIVERY_FIELDS = {"ipv4", "port", "public_pem", "leaf_sha256", "expires_at"}


class Held(ValueError):
    """Only fixed safe errors cross the command boundary."""


def canonical(value: object) -> bytes:
    try:
        data = (
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"
        ).encode()
        if not 0 < len(data) <= MAX_BODY:
            raise ValueError
        return data
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise Held("invalid message") from None


def decode(data: bytes) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def constant(_):
        raise ValueError

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        if type(value) is not dict:
            raise ValueError
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise Held("invalid message") from None


def remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise Held("deadline exceeded")
    return left


def hex_value(value: object, length: int) -> bool:
    return type(value) is str and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def bind_run(envelope: dict[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    """Fill only the template's null run_id with this actual first-attempt run."""
    context = inspect_context(environ)
    if type(envelope) is not dict or type(envelope.get("request")) is not dict:
        raise Held("missing request template")
    run_id = int(context["GITHUB_RUN_ID"])
    request = envelope["request"]
    if "run_id" not in request or request["run_id"] is not None:
        raise Held("request template requires null run_id")
    return envelope | {"request": request | {"run_id": run_id}}


def validate_inputs(delivery: dict[str, Any], envelope: dict[str, Any], context: Mapping[str, str], now: float) -> None:
    """Nonsecret checks before opening a socket or requesting a token."""
    observed = inspect_context(context)
    if observed["GITHUB_EVENT_NAME"] != "workflow_dispatch":
        raise Held("manual caller required")
    if type(delivery) is not dict or set(delivery) != DELIVERY_FIELDS:
        raise Held("missing delivery binding")
    try:
        if type(delivery["ipv4"]) is not str or str(ipaddress.IPv4Address(delivery["ipv4"])) != delivery["ipv4"]:
            raise ValueError
        if type(delivery["port"]) is not int or not 1 <= delivery["port"] <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise Held("invalid address") from None
    if not hex_value(delivery["leaf_sha256"], 64):
        raise Held("invalid certificate pin")
    pem = delivery["public_pem"]
    if (
        type(pem) is not str
        or not 1 <= len(pem) <= MAX_OIDC
        or not pem.startswith("-----BEGIN CERTIFICATE-----\n")
        or not pem.rstrip().endswith("-----END CERTIFICATE-----")
        or pem.count("-----BEGIN") != 1
        or not pem.isascii()
    ):
        raise Held("invalid public certificate")
    expiry = delivery["expires_at"]
    if type(expiry) is not int or not now < expiry <= now + 300:
        raise Held("expired delivery")
    if type(envelope) is not dict or set(envelope) != ENVELOPE_FIELDS or envelope["schema"] != SCHEMA:
        raise Held("invalid nonsecret envelope")
    for name in ENVELOPE_FIELDS - {"schema", "request"}:
        if not hex_value(envelope[name], 40 if name == "source_sha" else 64):
            raise Held("invalid envelope binding")
    if envelope["source_sha"] != observed["GITHUB_SHA"]:
        raise Held("caller source mismatch")
    request = envelope["request"]
    if type(request) is not dict or set(request) != set(REQUEST_FIELDS):
        raise Held("invalid request fields")
    if request["operation_key"] != envelope["operation_key"] or not hex_value(request["expected_head"], 40):
        raise Held("request binding mismatch")
    for field in ("run_id", "approval_id", "expires_at"):
        if type(request[field]) is not int or not 1 <= request[field] <= 2**53 - 1:
            raise Held("invalid request identity")
    if request["run_id"] != int(observed["GITHUB_RUN_ID"]) or not now < request["expires_at"] <= expiry:
        raise Held("request run/deadline mismatch")
    path, contents = request["path"], request["contents"]
    if path is None and contents is None:
        pass
    elif (
        type(path) is not str
        or re.fullmatch(r"ledger/operations/" + envelope["operation_key"] + r"/(record|[0-9]{4})\.json", path) is None
        or type(contents) is not str
    ):
        raise Held("invalid append path")
    else:
        try:
            raw = base64.b64decode(contents, validate=True)
            if not raw or base64.b64encode(raw).decode("ascii") != contents:
                raise ValueError
        except (ValueError, UnicodeError):
            raise Held("invalid append encoding") from None
    # Reserve the maximum token before any effects; never write this sizing value.
    canonical(envelope | {"oidc": "x" * MAX_OIDC})


def oidc_endpoint(value: str) -> tuple[str, str]:
    """Only the runner's GitHub HTTPS idtoken URL; no audience override."""
    try:
        if type(value) is not str or not 1 <= len(value) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError
        url = urlsplit(value)
        host = url.hostname or ""
        query = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
        if (
            url.scheme != "https"
            or url.username is not None
            or url.password is not None
            or url.port not in (None, 443)
            or url.fragment
            or re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.actions\.githubusercontent\.com", host) is None
            or not re.fullmatch(r"/[A-Za-z0-9_/-]+/idtoken", url.path)
            or query != [("api-version", "2.0")]
        ):
            raise ValueError
        return host, url.path + "?" + urlencode(query + [("audience", AUDIENCE)])
    except (ValueError, TypeError):
        raise Held("invalid GitHub OIDC endpoint") from None


def oidc_capability(environ: Mapping[str, str]) -> tuple[str, str, str]:
    host, target = oidc_endpoint(environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", ""))
    bearer = environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if type(bearer) is not str or not 1 <= len(bearer) <= MAX_OIDC or any(ord(c) < 33 or ord(c) > 126 for c in bearer):
        raise Held("missing runner OIDC capability")
    return host, target, bearer


def fetch_oidc(environ: Mapping[str, str], deadline: float) -> str:
    """Direct stdlib HTTPS GET: zero redirects, proxies or automatic retries."""
    host, target, bearer = oidc_capability(environ)
    # Do not use create_default_context: SSLKEYLOGFILE could persist TLS secrets.
    # Use compiled system trust locations, not SSL_CERT_FILE/SSL_CERT_DIR overrides.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    paths = ssl.get_default_verify_paths()
    context.load_verify_locations(cafile=paths.openssl_cafile, capath=paths.openssl_capath)
    connection = http.client.HTTPSConnection(host, timeout=min(10.0, remaining(deadline)), context=context)
    try:
        connection.request("GET", target, headers={"Authorization": "Bearer " + bearer, "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            raise Held("OIDC request held")
        chunks = bytearray()
        while True:
            if connection.sock is not None:
                connection.sock.settimeout(min(10.0, remaining(deadline)))
            remaining(deadline)
            chunk = response.read1(min(4096, MAX_OIDC_RESPONSE + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
            if len(chunks) > MAX_OIDC_RESPONSE:
                raise Held("OIDC response too large")
        remaining(deadline)
        result = decode(bytes(chunks))
        token = result.get("value")
        if (
            set(result) != {"value"}
            or type(token) is not str
            or not 1 <= len(token) <= MAX_OIDC
            or re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token) is None
        ):
            raise Held("invalid OIDC response")
        return token
    except Exception:
        raise Held("OIDC request held") from None
    finally:
        connection.close()


def read_exact(stream: ssl.SSLSocket, size: int, deadline: float) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        stream.settimeout(remaining(deadline))
        chunk = stream.recv(size - len(chunks))
        if not chunk:
            raise Held("truncated response")
        chunks.extend(chunk)
    return bytes(chunks)


def read_ack(stream: ssl.SSLSocket, operation_key: str, deadline: float) -> dict[str, Any]:
    if read_exact(stream, len(MAGIC), deadline) != MAGIC:
        raise Held("invalid response")
    size = struct.unpack("!I", read_exact(stream, 4, deadline))[0]
    if not 0 < size <= 4096:
        raise Held("response too large")
    data = read_exact(stream, size, deadline)
    if read_exact(stream, len(TRAILER), deadline) != TRAILER:
        raise Held("invalid response")
    ack = decode(data)
    if ack.get("hosted_acceptance") is not False or ack != {
        "schema": SCHEMA,
        "state": "transport-complete",
        "operation_key": operation_key,
        "hosted_acceptance": False,
    }:
        raise Held("invalid transport ACK")
    return ack


def send_once(delivery: dict[str, Any], envelope: dict[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    """Validate TLS1.3, hostname and leaf pin before obtaining or sending OIDC."""
    validate_inputs(delivery, envelope, environ, time.time())
    oidc_capability(environ)  # Check routing/capability before consuming the slot.
    deadline = time.monotonic() + min(120, delivery["expires_at"] - time.time())
    raw = secure = None
    message = None
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_verify_locations(cadata=delivery["public_pem"])
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(remaining(deadline))
        raw.connect((delivery["ipv4"], delivery["port"]))
        secure = context.wrap_socket(raw, server_hostname=PEER_NAME, do_handshake_on_connect=False)
        secure.settimeout(remaining(deadline))
        secure.do_handshake()
        certificate = secure.getpeercert(binary_form=True)
        if not isinstance(certificate, bytes):
            raise Held("missing peer certificate")
        actual = hashlib.sha256(certificate).hexdigest()
        if secure.version() != "TLSv1.3" or not hmac.compare_digest(actual, delivery["leaf_sha256"]):
            raise Held("TLS peer held")
        message = envelope | {"oidc": fetch_oidc(environ, deadline)}
        validate_inputs(delivery, envelope, environ, time.time())
        data = canonical(message)
        secure.settimeout(remaining(deadline))
        secure.sendall(MAGIC + struct.pack("!I", len(data)) + data + TRAILER)
        return read_ack(secure, envelope["operation_key"], deadline)
    except Exception:
        raise Held("one-shot caller held; no retry") from None
    finally:
        if message is not None:
            message.pop("oidc", None)
        if secure is not None:
            secure.close()
        if raw is not None:
            raw.close()


def main() -> int:
    """No CLI inputs or token output; absent nonsecret bindings are held."""
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if len(sys.argv) != 1:
            raise Held("no command arguments accepted")
        raw_delivery = os.environ.get("REP120_DELIVERY", "")
        raw_envelope = os.environ.get("REP120_ENVELOPE", "")
        if not raw_delivery or not raw_envelope or len(raw_delivery) > 32768 or len(raw_envelope) > MAX_BODY:
            raise Held("missing bounded nonsecret inputs")
        envelope = bind_run(decode(raw_envelope.encode()), os.environ)
        send_once(decode(raw_delivery.encode()), envelope, os.environ)
    except Exception:
        print("REP120 one-shot caller held; no retry or acceptance.", file=sys.stderr)
        return 2
    print("REP120 transport complete; hosted acceptance remains false.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
