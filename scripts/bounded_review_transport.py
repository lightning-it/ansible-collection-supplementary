"""One-shot protected Responses transport with bounded, withheld output.

Only a trusted controller may call this module, after durable admission. It is
not a standalone reviewer or workflow authority. The credential goes over stdin
to isolated count/response workers, never in argv, a file, a URL or diagnostic
output. Workers permit only verified TLS to fixed Responses endpoints, no redirects,
environment proxies, retry or decompression. The parent kills the worker on the
review's absolute deadline; an unknown upstream outcome retains its reservation.
"""

from __future__ import annotations

import http.client
import json
import os
import signal
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from bounded_review import ReviewError, canonical, integer, require
from bounded_review_provider import ResponseBudget

MAX_RESPONSE_BYTES = 8_000_000
MAX_WORKER_INPUT = 2_100_000
WORKER_ENVIRONMENT = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}


def strict_json(payload: bytes | str, *, json_limits: tuple[int, int] | None = None) -> Any:
    if json_limits is not None:
        # Prevent json.loads byte auto-detection (UTF-16/32) from interpreting a
        # different structure than the UTF-8 lexical allocation guard.
        if type(payload) is bytes:
            payload = payload.decode("utf-8", errors="strict")
        from single_review_resources import preflight_json

        preflight_json(payload, *json_limits)

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "transport-duplicate-key")
            result[key] = value
        return result

    def constant(_value):
        raise ReviewError("transport-json-constant")

    try:
        return json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)
    except (json.JSONDecodeError, UnicodeError):
        raise ReviewError("transport-invalid-json") from None


def completed_response(payload: bytes, *, streaming: bool) -> dict[str, Any]:
    """Find one complete upstream response before releasing any response bytes.

    Source: https://developers.openai.com/api/reference/resources/responses/streaming-events
    SSE events carry a typed JSON object and sequence_number; completed carries
    the full response and usage. Reject ambiguous, truncated or failed streams.
    """
    require(0 < len(payload) <= MAX_RESPONSE_BYTES, "transport-response-size")
    if not streaming:
        response = strict_json(payload)
        require(type(response) is dict, "transport-response-shape")
        return response
    text = payload.decode("utf-8", errors="strict")
    text = text.replace("\r\n", "\n")
    require("\r" not in text and text.endswith("\n\n"), "transport-incomplete-stream")
    result = None
    identity = None
    sequence = -1
    count = 0
    for block in text.split("\n\n"):
        if not block:
            continue
        event_name = None
        data = []
        for line in block.split("\n"):
            if line.startswith(":"):
                continue
            field, separator, value = line.partition(":")
            require(bool(separator), "transport-sse-field")
            value = value.removeprefix(" ")
            if field == "event":
                require(event_name is None, "transport-sse-event")
                event_name = value
            elif field == "data":
                data.append(value)
            else:
                raise ReviewError("transport-sse-field")
        if not data:
            require(event_name is None, "transport-sse-data")
            continue
        require(result is None, "transport-after-completion")
        event = strict_json("\n".join(data))
        require(type(event) is dict, "transport-sse-event")
        kind = event.get("type")
        require(type(kind) is str and kind.startswith("response."), "transport-sse-event")
        require(event_name in (None, kind), "transport-event-mismatch")
        integer(event.get("sequence_number"), sequence + 1, sequence + 1, "transport-sequence")
        sequence += 1
        count += 1
        require(count <= 100_000, "transport-event-budget")
        require(kind not in ("response.failed", "response.incomplete", "response.cancelled"), "transport-incomplete")
        if kind == "response.created":
            require(identity is None and count == 1, "transport-response-identity")
            response = event.get("response")
            require(type(response) is dict, "transport-response-shape")
            identity = response.get("id")
            require(type(identity) is str and 0 < len(identity) <= 256, "transport-response-identity")
        else:
            require(identity is not None, "transport-response-identity")
        if "response" in event:
            response = event["response"]
            require(type(response) is dict and response.get("id") == identity, "transport-response-identity")
        if kind == "response.completed":
            require(type(event.get("response")) is dict, "transport-response-shape")
            result = event["response"]
    require(result is not None, "transport-incomplete-stream")
    return result


# Official Responses input_tokens/count schema. All supported context-bearing
# fields are copied exactly from the normalized response request. State references
# remain forbidden by ResponseBudget. Sampling/telemetry/output controls are not
# count endpoint parameters and cannot inject input context.
COUNT_FIELDS = frozenset(
    {
        "model",
        "input",
        "instructions",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "reasoning",
        "text",
        "truncation",
        "conversation",
        "previous_response_id",
    }
)


def count_request(request: dict[str, Any]) -> dict[str, Any]:
    return json.loads(canonical({key: value for key, value in request.items() if key in COUNT_FIELDS}))


def fetch_once(request: dict[str, Any], credential: str, timeout: float, *, counting: bool = False) -> bytes:
    """Worker-only fixed TLS endpoint. No provider retry is ever attempted."""
    require(type(credential) is str and 1 <= len(credential) <= 4096, "transport-credential")
    require(all(32 < ord(c) < 127 for c in credential), "transport-credential")
    connection = http.client.HTTPSConnection("api.openai.com", timeout=timeout, context=ssl.create_default_context())
    try:
        connection.request(
            "POST",
            "/v1/responses/input_tokens" if counting else "/v1/responses",
            canonical(request),
            {
                "Authorization": "Bearer " + credential,
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
            },
        )
        response = connection.getresponse()
        require(response.status == 200, "transport-upstream-status")
        require(response.getheader("Content-Encoding", "identity").lower() == "identity", "transport-content-encoding")
        expected = "text/event-stream" if request.get("stream", False) else "application/json"
        require(
            response.getheader("Content-Type", "").split(";", 1)[0].strip().lower() == expected,
            "transport-content-type",
        )
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        require(0 < len(payload) <= MAX_RESPONSE_BYTES, "transport-response-size")
        return payload
    finally:
        connection.close()


def monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def run_worker(
    request: dict[str, Any],
    credential: str,
    deadline: int,
    *,
    counting: bool = False,
    input_limit: int = MAX_WORKER_INPUT,
    json_limits: tuple[int, int] | None = None,
) -> bytes:
    """Perform one fixed-endpoint operation within the shared absolute deadline.

    A new process bounds DNS, connect, write and read together. Killing it stops
    local I/O, not a claim of remote compute cancellation: ambiguous requests
    remain fully charged and cannot be retried. No client callback sees partial
    output or a success event before authenticated usage is settled.
    """
    child = None
    try:
        require(type(credential) is str and 1 <= len(credential) <= 4096, "transport-credential")
        remaining = deadline - monotonic_ms()
        require(remaining > 0, "provider-timeout")
        message = canonical(
            {"request": request, "credential": credential, "timeout_ms": remaining, "counting": counting}
        )
        integer(input_limit, 1, 2**63 - 1, "transport-resource-limit")
        require(len(message) <= input_limit, "transport-request-size")
        child = subprocess.Popen(
            [sys.executable, "-E", "-s", str(Path(__file__).resolve()), "--worker", str(len(message))]
            + ([] if json_limits is None else [str(value) for value in json_limits]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=WORKER_ENVIRONMENT,
            cwd="/",
            start_new_session=True,
        )
        remaining = (deadline - monotonic_ms()) / 1000
        require(remaining > 0, "provider-timeout")
        payload, _ = child.communicate(message, timeout=remaining)
        require(child.returncode == 0, "transport-upstream-failure")
        return payload
    finally:
        if child is not None:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            child.communicate()


def exchange(
    ledger: ResponseBudget,
    request: dict[str, Any],
    credential: str,
    *,
    worker_input_limit: int | None = None,
    json_limits: tuple[int, int] | None = None,
) -> bytes:
    """Count the complete normalized input, admit its reserve, then send once.

    Both isolated workers share one absolute deadline. Count failures are terminal
    and never reach the model endpoint. No partial output precedes settlement.
    """
    try:
        digest, bounded = ledger.reserve(request, now_ms=monotonic_ms())
        options = {} if worker_input_limit is None else {"input_limit": worker_input_limit}
        if json_limits is not None:
            options["json_limits"] = json_limits
        count = strict_json(run_worker(count_request(bounded), credential, ledger.deadline, counting=True, **options))
        ledger.admit_tokens(digest, bounded, count, now_ms=monotonic_ms())
        payload = run_worker(bounded, credential, ledger.deadline, **options)
        response = completed_response(payload, streaming=bounded.get("stream", False))
        ledger.complete(digest, response, now_ms=monotonic_ms())
        return payload
    except BaseException:
        ledger.abandon()
        raise


def worker(input_limit: int = MAX_WORKER_INPUT, json_limits: tuple[int, int] | None = None) -> int:
    try:
        integer(input_limit, 1, 2**63 - 1, "transport-resource-limit")
        payload = sys.stdin.buffer.read(input_limit + 1)
        require(len(payload) <= input_limit, "transport-request-size")
        message = strict_json(payload, json_limits=json_limits)
        require(
            type(message) is dict and set(message) == {"request", "credential", "timeout_ms", "counting"},
            "transport-worker-input",
        )
        integer(message["timeout_ms"], 1, 100_000, "transport-worker-timeout")
        require(type(message["counting"]) is bool, "transport-worker-operation")
        result = fetch_once(
            message["request"], message["credential"], message["timeout_ms"] / 1000, counting=message["counting"]
        )
        sys.stdout.buffer.write(result)
        return 0
    except Exception:
        # Never expose error bodies, request data, credentials, headers or a
        # traceback. The parent records a generic, terminal transport failure.
        return 1


if __name__ == "__main__":
    if len(sys.argv) in (3, 5) and sys.argv[1] == "--worker":
        limits = tuple(int(value) for value in sys.argv[3:]) if len(sys.argv) == 5 else None
        raise SystemExit(worker(int(sys.argv[2]), limits))
    raise SystemExit(worker() if sys.argv[1:] == ["--worker"] else 2)
