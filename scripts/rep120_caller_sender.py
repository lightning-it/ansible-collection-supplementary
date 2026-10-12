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
from enum import Enum
from typing import Any
from urllib.parse import parse_qsl, unquote_to_bytes, urlencode, urlsplit

from scripts.rep120_caller_contract import AUDIENCE, REQUEST_FIELDS, exact_type, inspect_context

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


class HoldStage(Enum):
    """Finite source-owned codes, never derived from exception or input text."""

    INPUT_CONTEXT = "INPUT_CONTEXT"
    OIDC_CAPABILITY = "OIDC_CAPABILITY"
    TCP = "TCP"
    TLS = "TLS"
    OIDC_GET = "OIDC_GET"
    SEND = "SEND"
    ACK = "ACK"


class OidcHoldReason(Enum):
    """Finite predicate names only; never routing, credential or exception data."""

    URL_MISSING = "URL_MISSING"
    URL_FORMAT = "URL_FORMAT"
    URL_HTTPS = "URL_HTTPS"
    URL_USERINFO = "URL_USERINFO"
    URL_PORT = "URL_PORT"
    URL_FRAGMENT = "URL_FRAGMENT"
    URL_HOST = "URL_HOST"
    URL_PATH = "URL_PATH"
    URL_QUERY = "URL_QUERY"
    BEARER_MISSING = "BEARER_MISSING"
    BEARER_FORMAT = "BEARER_FORMAT"
    BEARER_LENGTH = "BEARER_LENGTH"
    BEARER_ASCII = "BEARER_ASCII"


class OidcHeld(Held):
    """Carry a source-owned predicate, never its failing value."""

    def __init__(self, reason: OidcHoldReason) -> None:
        super().__init__("runner OIDC capability held")
        self.reason = reason


class StageHeld(Held):
    """Preserve only the active fixed stage across the outer error mask."""

    def __init__(self, stage: HoldStage, reason: OidcHoldReason | None = None) -> None:
        super().__init__("one-shot caller held; no retry")
        self.stage = stage
        self.reason = reason


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

    def constant(_value):
        raise ValueError

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        if not exact_type(value, dict):
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
    return exact_type(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def bind_run(envelope: dict[str, Any], environ: Mapping[str, str]) -> dict[str, Any]:
    """Fill only the template's null run_id with this actual first-attempt run."""
    context = inspect_context(environ)
    if not exact_type(envelope, dict) or not exact_type(envelope.get("request"), dict):
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
    if not exact_type(delivery, dict) or set(delivery) != DELIVERY_FIELDS:
        raise Held("missing delivery binding")
    try:
        if not exact_type(delivery["ipv4"], str) or str(ipaddress.IPv4Address(delivery["ipv4"])) != delivery["ipv4"]:
            raise ValueError
        if not exact_type(delivery["port"], int) or not 1 <= delivery["port"] <= 65535:
            raise ValueError
    except (ValueError, TypeError):
        raise Held("invalid address") from None
    if not hex_value(delivery["leaf_sha256"], 64):
        raise Held("invalid certificate pin")
    pem = delivery["public_pem"]
    if (
        not exact_type(pem, str)
        or not 1 <= len(pem) <= MAX_OIDC
        or not pem.startswith("-----BEGIN CERTIFICATE-----\n")
        or not pem.rstrip().endswith("-----END CERTIFICATE-----")
        or pem.count("-----BEGIN") != 1
        or not pem.isascii()
    ):
        raise Held("invalid public certificate")
    expiry = delivery["expires_at"]
    if not exact_type(expiry, int) or not now < expiry <= now + 300:
        raise Held("expired delivery")
    if not exact_type(envelope, dict) or set(envelope) != ENVELOPE_FIELDS or envelope["schema"] != SCHEMA:
        raise Held("invalid nonsecret envelope")
    for name in ENVELOPE_FIELDS - {"schema", "request"}:
        if not hex_value(envelope[name], 40 if name == "source_sha" else 64):
            raise Held("invalid envelope binding")
    if envelope["source_sha"] != observed["GITHUB_SHA"]:
        raise Held("caller source mismatch")
    request = envelope["request"]
    if not exact_type(request, dict) or set(request) != set(REQUEST_FIELDS):
        raise Held("invalid request fields")
    if request["operation_key"] != envelope["operation_key"] or not hex_value(request["expected_head"], 40):
        raise Held("request binding mismatch")
    for field in ("run_id", "approval_id", "expires_at"):
        if not exact_type(request[field], int) or not 1 <= request[field] <= 2**53 - 1:
            raise Held("invalid request identity")
    if request["run_id"] != int(observed["GITHUB_RUN_ID"]) or not now < request["expires_at"] <= expiry:
        raise Held("request run/deadline mismatch")
    path, contents = request["path"], request["contents"]
    if path is None and contents is None:
        pass
    elif (
        not exact_type(path, str)
        or re.fullmatch(r"ledger/operations/" + envelope["operation_key"] + r"/(record|[0-9]{4})\.json", path) is None
        or not exact_type(contents, str)
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


def oidc_idtoken_path(path: str) -> bool:
    """RFC3986 routing segments, unchanged on the wire; literal endpoint only."""
    # Runner supplies server-generated routing, not a UUID/ASCII-identifier schema.
    # Only its path syntax is checked here; this never authenticates the caller.
    pchar = r"(?:[A-Za-z0-9._~!$&'()*+,;=:@-]|%[0-9A-Fa-f]{2})"
    if re.fullmatch(rf"/(?:{pchar}+/)*idtoken", path) is None:
        return False
    for segment in path.split("/")[1:-1]:
        decoded = unquote_to_bytes(segment)
        # No normalization, traversal, hidden separator/control or double decoding.
        if decoded in (b".", b"..") or any(byte < 33 or byte in (37, 47, 92, 127) for byte in decoded):
            return False
    return True


def oidc_endpoint(value: str) -> tuple[str, str]:
    """Only the runner's GitHub HTTPS idtoken URL; no audience override."""
    if exact_type(value, str) and not value:
        raise OidcHeld(OidcHoldReason.URL_MISSING)
    if not exact_type(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise OidcHeld(OidcHoldReason.URL_FORMAT)
    try:
        url = urlsplit(value)
        host = url.hostname or ""
    except (ValueError, TypeError):
        raise OidcHeld(OidcHoldReason.URL_FORMAT) from None
    try:
        query = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True)
    except (ValueError, TypeError):
        raise OidcHeld(OidcHoldReason.URL_QUERY) from None
    if url.scheme != "https":
        raise OidcHeld(OidcHoldReason.URL_HTTPS)
    if url.username is not None or url.password is not None:
        raise OidcHeld(OidcHoldReason.URL_USERINFO)
    try:
        port = url.port
    except ValueError:
        raise OidcHeld(OidcHoldReason.URL_PORT) from None
    if port not in (None, 443):
        raise OidcHeld(OidcHoldReason.URL_PORT)
    if url.fragment:
        raise OidcHeld(OidcHoldReason.URL_FRAGMENT)
    if re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.actions\.githubusercontent\.com", host) is None:
        raise OidcHeld(OidcHoldReason.URL_HOST)
    if not oidc_idtoken_path(url.path):
        raise OidcHeld(OidcHoldReason.URL_PATH)
    if query != [("api-version", "2.0")]:
        raise OidcHeld(OidcHoldReason.URL_QUERY)
    return host, url.path + "?" + urlencode(query + [("audience", AUDIENCE)])


def oidc_capability(environ: Mapping[str, str]) -> tuple[str, str, str]:
    host, target = oidc_endpoint(environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", ""))
    bearer = environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if not exact_type(bearer, str):
        raise OidcHeld(OidcHoldReason.BEARER_FORMAT)
    if not bearer:
        raise OidcHeld(OidcHoldReason.BEARER_MISSING)
    if not 1 <= len(bearer) <= MAX_OIDC:
        raise OidcHeld(OidcHoldReason.BEARER_LENGTH)
    if any(ord(c) < 33 or ord(c) > 126 for c in bearer):
        raise OidcHeld(OidcHoldReason.BEARER_ASCII)
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
            or not exact_type(token, str)
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
    stage = HoldStage.INPUT_CONTEXT
    raw = secure = None
    message = None
    try:
        validate_inputs(delivery, envelope, environ, time.time())
        stage = HoldStage.OIDC_CAPABILITY
        oidc_capability(environ)  # Check routing/capability before consuming the slot.
        deadline = time.monotonic() + min(120, delivery["expires_at"] - time.time())
        stage = HoldStage.TLS
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_verify_locations(cadata=delivery["public_pem"])
        stage = HoldStage.TCP
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(remaining(deadline))
        raw.connect((delivery["ipv4"], delivery["port"]))
        stage = HoldStage.TLS
        secure = context.wrap_socket(raw, server_hostname=PEER_NAME, do_handshake_on_connect=False)
        secure.settimeout(remaining(deadline))
        secure.do_handshake()
        certificate = secure.getpeercert(binary_form=True)
        if not isinstance(certificate, bytes):
            raise Held("missing peer certificate")
        actual = hashlib.sha256(certificate).hexdigest()
        if secure.version() != "TLSv1.3" or not hmac.compare_digest(actual, delivery["leaf_sha256"]):
            raise Held("TLS peer held")
        stage = HoldStage.OIDC_GET
        message = envelope | {"oidc": fetch_oidc(environ, deadline)}
        stage = HoldStage.INPUT_CONTEXT
        validate_inputs(delivery, envelope, environ, time.time())
        stage = HoldStage.SEND
        data = canonical(message)
        secure.settimeout(remaining(deadline))
        secure.sendall(MAGIC + struct.pack("!I", len(data)) + data + TRAILER)
        stage = HoldStage.ACK
        return read_ack(secure, envelope["operation_key"], deadline)
    except Exception as error:
        reason = getattr(error, "reason", None) if isinstance(error, OidcHeld) else None
        raise StageHeld(stage, reason) from None
    finally:
        try:
            if message is not None:
                message.pop("oidc", None)
            if secure is not None:
                secure.close()
            if raw is not None:
                raw.close()
        except Exception:
            raise StageHeld(stage) from None


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
    except Exception as error:
        failed_stage = error.stage if isinstance(error, StageHeld) else HoldStage.INPUT_CONTEXT
        code = next((stage.value for stage in HoldStage if stage is failed_stage), HoldStage.INPUT_CONTEXT.value)
        reason = (
            getattr(error, "reason", None)
            if isinstance(error, StageHeld) and failed_stage is HoldStage.OIDC_CAPABILITY
            else None
        )
        reason_code = next((item.value for item in OidcHoldReason if item is reason), None)
        if reason_code is not None:
            code += ":" + reason_code
        print(f"REP120 one-shot caller held [{code}]; no retry or acceptance.", file=sys.stderr)
        return 2
    print("REP120 transport complete; hosted acceptance remains false.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
