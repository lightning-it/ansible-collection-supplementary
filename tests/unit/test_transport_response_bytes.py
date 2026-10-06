"""Admitted provider byte boundaries before HTTP/parent allocation or parsing."""

import io
import subprocess
import sys
import tracemalloc
import unittest
from unittest.mock import MagicMock, patch

try:
    from . import test_exact_revision_gateway as fixtures
except ImportError:
    import test_exact_revision_gateway as fixtures

transport = fixtures.gateway.transport
review = fixtures.gateway.review


class TransportResponseBytesTests(unittest.TestCase):
    def request(self):
        return {"model": fixtures.gateway.config.profile()["model"], "input": "Complete fixture input"}

    def test_http_count_and_model_reads_use_exact_admitted_limit_plus_sentinel(self):
        for counting in (False, True):
            for size in (63, 64, 65):
                with self.subTest(counting=counting, size=size):
                    connection = MagicMock()
                    upstream = connection.getresponse.return_value
                    upstream.status = 200
                    upstream.getheader.side_effect = lambda name, default="": {"Content-Type": "application/json"}.get(
                        name, default
                    )
                    upstream.read.return_value = b"x" * size
                    with patch.object(transport.http.client, "HTTPSConnection", return_value=connection):
                        if size <= 64:
                            self.assertEqual(
                                b"x" * size,
                                transport.fetch_once(
                                    self.request(), "fixture", 1, counting=counting, response_byte_limit=64
                                ),
                            )
                        else:
                            with self.assertRaisesRegex(review.ReviewError, "response-size"):
                                transport.fetch_once(
                                    self.request(), "fixture", 1, counting=counting, response_byte_limit=64
                                )
                    upstream.read.assert_called_once_with(65)
                    connection.close.assert_called_once()
                    self.assertEqual(1, connection.request.call_count)

    def test_worker_passes_response_limit_and_refuses_oversized_transport_result(self):
        for counting in (False, True):
            for size in (64, 65):
                message = review.canonical(
                    {"request": self.request(), "credential": "fixture", "timeout_ms": 100, "counting": counting}
                )
                output = io.BytesIO()
                with (
                    patch.object(transport.sys, "stdin", type("Input", (), {"buffer": io.BytesIO(message)})()),
                    patch.object(transport.sys, "stdout", type("Output", (), {"buffer": output})()),
                    patch.object(transport, "fetch_once", return_value=b"x" * size) as fetch,
                ):
                    code = transport.worker(len(message), (100, 10), response_byte_limit=64)
                self.assertEqual(0 if size == 64 else 1, code)
                self.assertEqual(b"x" * 64 if size == 64 else b"", output.getvalue())
                self.assertEqual(64, fetch.call_args.kwargs["response_byte_limit"])
                self.assertEqual(counting, fetch.call_args.kwargs["counting"])

    def test_actual_worker_cli_suffix_bounds_count_and_model_http_before_output(self):
        from pathlib import Path

        script = str(Path(transport.__file__).resolve())
        for counting in (False, True):
            for size in (64, 65):
                message = review.canonical(
                    {"request": self.request(), "credential": "fixture", "timeout_ms": 100, "counting": counting}
                )
                arguments = [script, "--worker", str(len(message)), "100", "10", "--response-byte-limit", "64"]
                endpoint = "/v1/responses/input_tokens" if counting else "/v1/responses"
                program = f"""
import http.client
import runpy
import sys
sys.path.insert(0, {str(Path(script).parent)!r})
class Response:
    status = 200
    def getheader(self, name, default=""):
        return {{"Content-Type": "application/json"}}.get(name, default)
    def read(self, maximum):
        assert maximum == 65, maximum
        return b"x" * {size}
class Connection:
    def __init__(self, *args, **kwargs):
        pass
    def request(self, method, endpoint, *args, **kwargs):
        assert method == "POST" and endpoint == {endpoint!r}
    def getresponse(self):
        return Response()
    def close(self):
        pass
http.client.HTTPSConnection = Connection
sys.argv = {arguments!r}
runpy.run_path({script!r}, run_name="__main__")
"""
                with self.subTest(counting=counting, size=size):
                    result = subprocess.run(  # noqa: S603 -- fixed repository/fixture command and isolated environment.
                        [sys.executable, "-I", "-c", program],
                        input=message,
                        capture_output=True,
                        timeout=5,
                        cwd="/",
                        env=transport.WORKER_ENVIRONMENT,
                        check=False,  # The test asserts the exact return code.
                    )
                    self.assertEqual(0 if size == 64 else 1, result.returncode, result.stderr)
                    self.assertEqual(b"x" * 64 if size == 64 else b"", result.stdout)
                    self.assertEqual(b"", result.stderr)

    def test_actual_child_stdout_size_is_checked_before_parent_read_and_unknown_output_is_not_drained(self):
        original_spawn = subprocess.Popen
        original_file = transport.tempfile.TemporaryFile
        limit = 65536
        for size in (limit - 1, limit, limit + 1, limit * 16):
            with self.subTest(size=size):
                children, outputs = [], []

                def temporary_file(size=size, outputs=outputs, **kwargs):  # pylint: disable=dangerous-default-value
                    # Capture this fixture's list, not a shared default across tests.
                    file = original_file(**kwargs)
                    proxy = MagicMock(wraps=file)
                    if size > limit:
                        proxy.read.side_effect = AssertionError("oversized output must never be read")
                    outputs.append(proxy)
                    return proxy

                def spawn(argv, size=size, children=children, **kwargs):  # pylint: disable=dangerous-default-value
                    # Capture this iteration's observed child list.
                    self.assertEqual(["--response-byte-limit", str(limit)], argv[-2:])
                    self.assertIsNot(kwargs["stdout"], subprocess.PIPE)
                    code = "import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x' * " + str(size) + ")"
                    child = original_spawn([sys.executable, "-I", "-c", code], **kwargs)
                    children.append(child)
                    return child

                with (
                    patch.object(transport.subprocess, "Popen", side_effect=spawn),
                    patch.object(transport.tempfile, "TemporaryFile", side_effect=temporary_file),
                ):
                    if size <= limit:
                        self.assertEqual(
                            b"x" * size,
                            transport.run_worker(
                                self.request(), "fixture", transport.monotonic_ms() + 2000, response_byte_limit=limit
                            ),
                        )
                        outputs[0].read.assert_called_once_with(limit + 1)
                    else:
                        with self.assertRaisesRegex(review.ReviewError, "response-size"):
                            transport.run_worker(
                                self.request(), "fixture", transport.monotonic_ms() + 2000, response_byte_limit=limit
                            )
                        outputs[0].read.assert_not_called()
                self.assertIsNotNone(children[0].poll())
                outputs[0].close.assert_called_once()

    def test_actual_spooled_worker_deadline_kills_reaps_and_closes_without_reading(self):
        original_spawn = subprocess.Popen
        original_file = transport.tempfile.TemporaryFile
        children, outputs = [], []

        def temporary_file(outputs=outputs, **kwargs):  # pylint: disable=dangerous-default-value
            # Capture this fixture's observed output list.
            proxy = MagicMock(wraps=original_file(**kwargs))
            outputs.append(proxy)
            return proxy

        def spawn(_argv, **kwargs):
            child = original_spawn([sys.executable, "-I", "-c", "import time; time.sleep(30)"], **kwargs)
            children.append(child)
            return child

        with (
            patch.object(transport.subprocess, "Popen", side_effect=spawn),
            patch.object(transport.tempfile, "TemporaryFile", side_effect=temporary_file),
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            transport.run_worker(self.request(), "fixture", transport.monotonic_ms() + 150, response_byte_limit=65536)
        self.assertIsNotNone(children[0].poll())
        outputs[0].read.assert_not_called()
        outputs[0].close.assert_called_once()

    def test_count_and_response_guard_oversized_mock_worker_before_json_decode(self):
        ledger = fixtures.gateway.ResponseBudget(
            fixtures.gateway.config.profile(),
            max_cost_microusd=1_000_000,
            start_ms=transport.monotonic_ms(),
            timeout_ms=1000,
        )
        with (
            patch.object(transport, "run_worker", return_value=b" " * 65537) as worker,
            self.assertRaisesRegex(review.ReviewError, "response-size"),
        ):
            transport.exchange(ledger, self.request(), "fixture", response_byte_limit=65536)
        self.assertEqual(1, worker.call_count)
        self.assertEqual(65536, worker.call_args.kwargs["response_byte_limit"])
        self.assertTrue(ledger.failed)
        for streaming in (False, True):
            with (
                patch.object(transport, "strict_json") as decode,
                self.assertRaisesRegex(review.ReviewError, "response-size"),
            ):
                transport.completed_response(b" " * 65537, streaming=streaming, response_byte_limit=65536)
            decode.assert_not_called()

    def test_single_sse_block_many_comment_lines_nonbmp_does_not_retain_split_lists(self):
        response = {"id": "r", "status": "completed"}
        events = [
            {"type": "response.created", "sequence_number": 0, "response": {"id": "r"}},
            {"type": "response.completed", "sequence_number": 1, "response": response},
        ]
        comment = b":x\n" * 20000 + ":🙂\n\n".encode()
        wire = (
            b"data: "
            + review.canonical(events[0])
            + b"\n\n"
            + comment
            + b"data: "
            + review.canonical(events[1])
            + b"\n\n"
        )
        tracemalloc.start()
        try:
            self.assertEqual(
                response, transport.completed_response(wire, streaming=True, response_byte_limit=len(wire))
            )
            _unused_value_1, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, len(wire) * fixtures.gateway.resources.COPIES)


if __name__ == "__main__":
    unittest.main()
