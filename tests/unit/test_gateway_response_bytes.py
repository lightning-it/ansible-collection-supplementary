"""Actual admission-to-receipt output bounds; simulated worker wire only."""

import json
import tracemalloc
import unittest
from unittest.mock import patch

try:
    from . import test_exact_revision_gateway as fixtures
except ImportError:
    import test_exact_revision_gateway as fixtures

gateway = fixtures.gateway
transport = gateway.transport


class GatewayResponseByteTests(unittest.TestCase):
    setUp = fixtures.SingleReviewGatewayTests.setUp
    request = fixtures.SingleReviewGatewayTests.request
    response = fixtures.SingleReviewGatewayTests.response

    def narrow_contract(self):
        contract = dict(self.state["resource_contract"])
        contract.update(reserved_bytes=4 * 1024 * 1024, max_json_nodes=2048)
        contract["max_wire_bytes"] = (
            contract["reserved_bytes"]
            - (contract["max_json_nodes"] + gateway.resources.ENVELOPE_NODES) * gateway.resources.NODE_BYTES
        ) // gateway.resources.COPIES
        return contract

    def replies(self, mode, size):
        count = gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10})
        response = self.response()
        if mode == "count":
            count += b" " * (size - len(count))
            wire = gateway.review.canonical(response)
        elif mode == "nonstream":
            response["instructions"] = ""
            response["instructions"] = "x" * (size - len(gateway.review.canonical(response)))
            wire = gateway.review.canonical(response)
        else:
            events = [
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {"id": response["id"]},
                },
                {
                    "type": "response.completed",
                    "sequence_number": 1,
                    "response": response,
                },
            ]
            wire = b"".join(b"data: " + gateway.review.canonical(item) + b"\n\n" for item in events)
            padding = size - len(wire)
            self.assertGreaterEqual(padding, 3)
            wire = b":" + b"x" * (padding - 3) + b"\n\n" + wire
        self.assertEqual(size, len(count if mode == "count" else wire))
        return count, wire

    def reset_terminal_files(self):
        for name in ("receipt.json", "failure.json"):
            (self.root / "public" / name).unlink(missing_ok=True)

    def test_count_nonstream_sse_oversize_fail_before_decode_without_retry_or_receipt(self):
        contract = self.narrow_contract()
        maximum = contract["max_wire_bytes"]
        original_decode = transport.strict_json

        def bounded_decode(payload, **kwargs):
            # A raw oversized worker result must never reach a decoder.
            if type(payload) is bytes:
                self.assertLessEqual(len(payload), maximum)
            return original_decode(payload, **kwargs)

        for mode in ("count", "nonstream", "sse"):
            for size in (maximum + 1, 3_200_941):
                with self.subTest(mode=mode, size=size):
                    reviewer = gateway.Reviewer(self.state, self.prompt, self.root / "public")
                    count, wire = self.replies(mode, size)
                    with (
                        patch.object(transport, "run_worker", side_effect=[count, wire]) as worker,
                        patch.object(transport, "strict_json", side_effect=bounded_decode),
                    ):
                        with self.assertRaisesRegex(gateway.review.ReviewError, "response-size"):
                            reviewer.submit(self.request() | {"stream": mode == "sse"}, "fixture", admission=contract)
                        calls = worker.call_count
                        self.assertEqual(1 if mode == "count" else 2, calls)
                        self.assertTrue(reviewer.failed)
                        self.assertTrue(reviewer.budget.failed)
                        self.assertGreater(reviewer.budget.charged, 0)
                        self.assertFalse((self.root / "public/receipt.json").exists())
                        self.assertTrue((self.root / "public/failure.json").exists())
                        with self.assertRaises(gateway.review.ReviewError):
                            reviewer.submit(self.request(), "fixture", admission=contract)
                        self.assertEqual(calls, worker.call_count)
                        self.assertTrue(
                            all(call.kwargs["response_byte_limit"] == maximum for call in worker.call_args_list)
                        )
                    self.reset_terminal_files()

    def test_complete_responses_at_exact_boundary_and_near_limit_request_pass(self):
        contract = self.narrow_contract()
        maximum = contract["max_wire_bytes"]
        for mode in ("count", "nonstream", "sse"):
            with self.subTest(mode=mode):
                reviewer = gateway.Reviewer(self.state, self.prompt, self.root / "public")
                request = self.request() | {"stream": mode == "sse"}
                request["instructions"] += " " * (maximum - 1024 - len(gateway.review.canonical(request)))
                count, wire = self.replies(mode, maximum)
                with patch.object(transport, "run_worker", side_effect=[count, wire]) as worker:
                    returned = reviewer.submit(request, "fixture", admission=contract)
                self.assertEqual(wire, returned)
                self.assertEqual(2, worker.call_count)
                self.assertFalse(reviewer.failed)
                receipt = json.loads((self.root / "public/receipt.json").read_text())
                self.assertEqual("PASS", receipt["result"]["verdict"])
                self.assertEqual(maximum, receipt["admission_resources"]["response_wire_limit"])
                self.assertEqual(1, receipt["provider"]["request_count"])
                self.reset_terminal_files()

    def test_output_limit_uses_narrower_of_protected_and_current_contract(self):
        small = self.narrow_contract()
        large = self.state["resource_contract"]
        self.assertLess(small["max_wire_bytes"], large["max_wire_bytes"])
        for protected, current in ((small, large), (large, small)):
            with self.subTest(protected_is_narrower=protected is small):
                state = self.state | {"resource_contract": protected}
                reviewer = gateway.Reviewer(state, self.prompt, self.root / "public")
                counted, _ = self.replies("count", small["max_wire_bytes"] + 1)
                with (
                    patch.object(transport, "run_worker", return_value=counted) as worker,
                    self.assertRaisesRegex(gateway.review.ReviewError, "response-size"),
                ):
                    reviewer.submit(self.request(), "fixture", admission=current)
                self.assertEqual(small["max_wire_bytes"], worker.call_args.kwargs["response_byte_limit"])
                self.assertFalse((self.root / "public/receipt.json").exists())
                self.reset_terminal_files()

    def test_retained_request_and_many_short_sse_lines_fit_unchanged_reserve(self):
        # Regression for the already confirmed retained-working-set counterexample.
        # Reproduce Handler's body/parsed-request retention without a socket or
        # provider experiment; only worker response bytes come from fixtures.
        maximum = 1024 * 1024
        contract = self.narrow_contract()
        contract["max_wire_bytes"] = maximum
        contract["reserved_bytes"] = (
            maximum * gateway.resources.COPIES
            + (contract["max_json_nodes"] + gateway.resources.ENVELOPE_NODES) * gateway.resources.NODE_BYTES
        )
        request = self.request() | {"stream": True, "instructions": "🙂"}
        request["instructions"] = " " * (maximum - len(gateway.review.canonical(request)) - 512) + "🙂"
        encoded = gateway.review.canonical(request)
        response = self.response()
        response["usage"] = {"input_tokens": 170000, "output_tokens": 5, "total_tokens": 170005}
        terminal = b"".join(
            b"data: " + gateway.review.canonical(event) + b"\n\n"
            for event in (
                {"type": "response.created", "sequence_number": 0, "response": {"id": response["id"]}},
                {"type": "response.completed", "sequence_number": 1, "response": response},
            )
        )
        unicode_comment = ":🙂\n".encode()
        count = (maximum - len(terminal) - len(unicode_comment)) // 3
        wire = b":x\n" * count + unicode_comment + terminal
        self.assertLessEqual(len(encoded), maximum)
        self.assertLessEqual(len(wire), maximum)
        calls = []

        def worker(_request, _credential, _deadline, *, counting=False, **_options):
            calls.append(counting)
            if counting:
                return gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 170000})
            return memoryview(wire).tobytes()

        tracemalloc.start()
        try:
            # Handler retains its raw body while submit retains the parsed and
            # normalized request, exactly the overlap relevant to the finding.
            body = memoryview(encoded).tobytes()
            parsed = transport.strict_json(body, json_limits=(contract["max_json_nodes"], 64))
            with patch.object(transport, "run_worker", side_effect=worker):
                returned = self.reviewer.submit(parsed, "fixture", admission=contract)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, contract["reserved_bytes"])
        self.assertEqual(wire, returned)
        self.assertEqual([True, False], calls)
        self.assertTrue((self.root / "public/receipt.json").exists())
        self.assertEqual(32, gateway.resources.COPIES)
        print(
            "RETAINED_RESPONSE_REGRESSION "
            + json.dumps(
                {
                    "reserved_bytes": contract["reserved_bytes"],
                    "peak_python_bytes": peak,
                    "request_bytes": len(body),
                    "response_bytes": len(wire),
                    "wire_limit": maximum,
                    "count_then_inference": calls,
                    "scope": "actual JSON/submit/exchange/SSE/receipt with retained request body; worker wire fixtures; no socket/provider",  # noqa: E501 -- exact fixture payload.
                },
                sort_keys=True,
            )
        )

    def test_both_response_decodes_use_the_same_admitted_byte_limit(self):
        contract = self.narrow_contract()
        counted = gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10})
        wire = gateway.review.canonical(self.response())
        with (
            patch.object(transport, "run_worker", side_effect=[counted, wire]),
            patch.object(transport, "completed_response", wraps=transport.completed_response) as decode,
        ):
            self.reviewer.submit(self.request(), "fixture", admission=contract)
        self.assertEqual(2, decode.call_count)
        self.assertEqual(
            [contract["max_wire_bytes"]] * 2,
            [call.kwargs["response_byte_limit"] for call in decode.call_args_list],
        )


if __name__ == "__main__":
    unittest.main()
