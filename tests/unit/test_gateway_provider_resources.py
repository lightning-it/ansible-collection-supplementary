"""Provider allocation and absolute socket-deadline regressions; no API traffic."""

import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

try:
    from . import test_exact_revision_gateway as fixtures
except ImportError:
    import test_exact_revision_gateway as fixtures

gateway = fixtures.gateway
transport = gateway.transport


class NormalizedRequestBudgetTests(unittest.TestCase):
    def test_normalized_byte_boundary_rejects_before_digest_request_consumption_or_charge(self):
        import bounded_review_provider as provider

        profile = gateway.config.profile()
        for metadata in (None, {"agent": "codex"}):
            request = {"model": profile["model"], "input": "boundary"}
            if metadata is not None:
                request["client_metadata"] = metadata
            reference = gateway.ResponseBudget(profile, max_cost_microusd=1_000_000, start_ms=0, timeout_ms=1000)
            _digest, normalized = reference.reserve(request, now_ms=1)
            size = len(gateway.review.canonical(normalized))
            self.assertLess(len(gateway.review.canonical(request)), size)
            self.assertNotIn("client_metadata", normalized)
            for limit in (size - 1, size, size + 1):
                with self.subTest(metadata=metadata, limit=limit, normalized_size=size):
                    budget = gateway.ResponseBudget(
                        profile,
                        max_cost_microusd=1_000_000,
                        start_ms=0,
                        timeout_ms=1000,
                        request_byte_limit=limit,
                    )
                    with patch.object(provider, "sha", wraps=provider.sha) as digest:
                        if limit < size:
                            with self.assertRaisesRegex(gateway.review.ReviewError, "provider-request-size"):
                                budget.reserve(request, now_ms=1)
                            digest.assert_not_called()
                            self.assertEqual(0, budget.charged)
                            self.assertEqual(set(), budget.requests)
                            self.assertEqual(set(), budget.responses)
                            self.assertIsNone(budget.active)
                            self.assertIsNone(budget.admitted)
                            self.assertTrue(budget.failed)
                        else:
                            _digest, bounded = budget.reserve(request, now_ms=1)
                            self.assertEqual(normalized, bounded)
                            self.assertEqual(1, digest.call_count)
                            self.assertEqual(1, len(budget.requests))
                            self.assertGreater(budget.charged, 0)


class ProviderResourceTests(unittest.TestCase):
    setUp = fixtures.SingleReviewGatewayTests.setUp
    request = fixtures.SingleReviewGatewayTests.request
    response = fixtures.SingleReviewGatewayTests.response

    def test_count_and_each_provider_response_decode_preflight_before_json_allocation(self):
        bomb = '{"items":[' + ",".join("{}" for _unused_value_1 in range(3000)) + "]}"
        deep = '{"items":' + "[" * 65 + "0" + "]" * 65 + "}"
        for payload, reason in ((bomb, "node-budget"), (deep, "depth")):
            for streaming in (False, True):
                with self.subTest(reason=reason, streaming=streaming):
                    wire = payload.encode() if not streaming else b"data: " + payload.encode() + b"\n\n"
                    with patch.object(transport.json, "loads") as decode, self.assertRaisesRegex(ValueError, reason):
                        transport.completed_response(wire, streaming=streaming, json_limits=(2048, 64))
                    decode.assert_not_called()
            response = self.response()
            response["output"][0]["content"][0]["text"] = payload
            with patch.object(transport.json, "loads") as decode, self.assertRaisesRegex(ValueError, reason):
                gateway.final_packet(response, json_limits=(2048, 64))
            decode.assert_not_called()

    def test_actual_exchange_rejects_count_response_structure_before_inference(self):
        for payload in (b'{"items":[' + b"{}," * 3000 + b"{}]}", b"[" * 65 + b"0" + b"]" * 65):
            ledger = gateway.ResponseBudget(
                gateway.config.profile(),
                max_cost_microusd=1_000_000,
                start_ms=transport.monotonic_ms(),
                timeout_ms=1000,
            )
            with patch.object(transport, "run_worker", return_value=payload) as worker, self.assertRaises(ValueError):
                transport.exchange(ledger, self.request(), "fixture", json_limits=(2048, 64))
            self.assertEqual(1, worker.call_count)
            self.assertTrue(ledger.failed)
            self.assertEqual((2112, 65), worker.call_args.kwargs["json_limits"])

    def test_submit_rejects_provider_outer_and_inner_structure_without_retry_or_receipt(self):
        for streaming in (False, True):
            for inner in (False, True):
                with self.subTest(streaming=streaming, inner=inner):
                    response = self.response()
                    if inner:
                        response["output"][0]["content"][0]["text"] = json.dumps({"items": [{}] * 3000})
                    else:
                        response["extra"] = [{}] * 3000
                    if streaming:
                        events = [
                            {"type": "response.created", "sequence_number": 0, "response": {"id": response["id"]}},
                            {"type": "response.completed", "sequence_number": 1, "response": response},
                        ]
                        wire = b"".join(b"data: " + gateway.review.canonical(item) + b"\n\n" for item in events)
                    else:
                        wire = gateway.review.canonical(response)
                    reviewer = gateway.Reviewer(self.state, self.prompt, self.root / "public")
                    contract = dict(self.state["resource_contract"])
                    contract["max_json_nodes"] = 2048
                    contract["max_wire_bytes"] = (
                        contract["reserved_bytes"]
                        - (2048 + gateway.resources.ENVELOPE_NODES) * gateway.resources.NODE_BYTES
                    ) // gateway.resources.COPIES
                    with (
                        patch.object(
                            transport,
                            "run_worker",
                            side_effect=[
                                gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10}),
                                wire,
                            ],
                        ) as worker,
                        self.assertRaisesRegex(ValueError, "node-budget"),
                    ):
                        reviewer.submit(self.request() | {"stream": streaming}, "fixture", admission=contract)
                    self.assertEqual(2, worker.call_count)
                    self.assertTrue(reviewer.failed)
                    self.assertFalse((self.root / "public/receipt.json").exists())
                    (self.root / "public/failure.json").unlink()

    def test_second_submit_decode_uses_same_admitted_limits(self):
        with (
            patch.object(transport, "completed_response", wraps=transport.completed_response) as decode,
            patch.object(
                transport,
                "run_worker",
                side_effect=[
                    gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10}),
                    gateway.review.canonical(self.response()),
                ],
            ),
        ):
            self.reviewer.submit(self.request(), "fixture")
        self.assertEqual(2, decode.call_count)
        limits = (self.reviewer.admission["node_limit"], gateway.resources.MAX_JSON_DEPTH)
        self.assertEqual([limits, limits], [call.kwargs["json_limits"] for call in decode.call_args_list])

    def test_actual_http_absolute_deadline_bounds_request_line_headers_and_body_drips(self):
        for stage in ("request-line", "header", "body"):
            with self.subTest(stage=stage):
                reviewer = gateway.Reviewer(self.state, self.prompt, self.root / "public")
                reviewer.startup_deadline = transport.monotonic_ms() + 200
                with (
                    gateway.http.server.HTTPServer(("127.0.0.1", 0), gateway.handler_for(reviewer)) as server,
                    patch.object(transport, "run_worker") as worker,
                ):
                    serving = threading.Thread(target=server.handle_request, daemon=True)
                    serving.start()
                    started = time.monotonic()
                    with socket.create_connection(server.server_address, timeout=1) as client:
                        if stage == "request-line":
                            client.sendall(b"POST /responses HTTP/1.")
                        elif stage == "header":
                            client.sendall(b"POST /responses HTTP/1.0\r\nX-Drip: ")
                        else:
                            client.sendall(
                                b"POST /responses HTTP/1.0\r\nContent-Type: application/json\r\n"
                                b"Authorization: Bearer fixture\r\nContent-Length: 1000\r\n\r\n"
                            )
                        while serving.is_alive() and time.monotonic() - started < 1:
                            try:
                                client.sendall(b"x")
                            except OSError:
                                break
                            time.sleep(0.02)
                        serving.join(0.5)
                    self.assertFalse(serving.is_alive(), stage)
                    self.assertLess(time.monotonic() - started, 0.8)
                    worker.assert_not_called()
                self.assertTrue(reviewer.failed)
                self.assertTrue((self.root / "public/failure.json").exists())
                (self.root / "public/failure.json").unlink()

    def test_model_budget_cannot_extend_absolute_startup_deadline(self):
        self.reviewer.startup_deadline = transport.monotonic_ms() + 500
        with patch.object(
            transport,
            "run_worker",
            side_effect=[
                gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10}),
                gateway.review.canonical(self.response()),
            ],
        ):
            self.reviewer.submit(self.request(), "fixture")
        self.assertEqual(self.reviewer.startup_deadline, self.reviewer.budget.deadline)


if __name__ == "__main__":
    unittest.main()
