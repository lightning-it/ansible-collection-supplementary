"""Exercise the single-review protected gateway without any provider traffic."""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import exact_revision_gateway as gateway  # noqa: E402 -- load the actual repository module after the scoped path binding.


class SingleReviewGatewayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "review"
        self.directory.mkdir(mode=0o700)
        self.root = Path(self.temporary.name) / "installed"
        self.payload = b"diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n"
        prompt = (ROOT / ".github/codex/prompts/review-exact-head.md").read_bytes()
        schema = (ROOT / ".github/codex/schemas/exact-head-review.schema.json").read_bytes()
        self.metadata = {key: "a" * (64 if key.endswith("sha256") else 40) for key in gateway.BINDINGS}
        self.metadata.update(
            schema_version=7,
            diff_sha256=gateway.review.sha(self.payload),
            review_bytes=len(self.payload),
            prompt_sha256=gateway.review.sha(prompt),
            schema_sha256=gateway.review.sha(schema),
        )
        import hashlib

        policy_files = []
        agents = "Complete deterministic checks regardless of diff size; no automatic splitting.\n"
        marker = f"<!-- AGENTS_SHA256: {gateway.review.sha(agents.encode())} -->\n"
        for path, content in (
            (".github/copilot-instructions.md", "Follow protected AGENTS.md.\n" + marker),
            ("AGENTS.md", agents),
        ):
            encoded = content.encode()
            policy_files.append(
                {
                    "path": path,
                    "content": content,
                    "sha256": gateway.review.sha(encoded),
                    "blob_sha": hashlib.sha1(b"blob " + str(len(encoded)).encode() + b"\0" + encoded).hexdigest(),  # noqa: S324 -- reproduce Git object IDs in the fixture.
                }
            )
        instructions = {"version": 1, "source_sha": self.metadata["base_sha"], "files": policy_files}
        self.metadata.update(
            trusted_workflow_sha=self.metadata["base_sha"],
            review_instructions=instructions,
            instructions_sha256=gateway.review.sha(gateway.review.canonical(instructions)),
        )
        for name, data in (
            ("change.patch", self.payload),
            ("review-prompt.md", prompt),
            ("review-schema.json", schema),
            ("review-metadata.json", gateway.review.canonical(self.metadata)),
        ):
            (self.directory / name).write_bytes(data)
        gateway.prepare(self.root, self.directory, 42, os.getuid())
        self.state, self.prompt = gateway.context(self.root, 42, uid=os.getuid())
        self.reviewer = gateway.Reviewer(self.state, self.prompt, self.root / "public")
        self.result = {key: self.metadata[key] for key in gateway.BINDINGS}
        self.result.update(verdict="PASS", summary="No findings", findings=[])

    def request(self):
        return {
            "model": gateway.config.profile()["model"],
            "input": self.prompt,
            "instructions": "Protected action instructions",
            "tools": [],
            "text": {"format": {"type": "json_schema", "name": "review", "schema": {"type": "object"}}},
        }

    def response(self):
        return {
            "id": "resp_fixture",
            "model": gateway.config.profile()["model"],
            "status": "completed",
            "service_tier": "default",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": json.dumps(self.result)}],
                }
            ],
        }

    def large_subject(self):
        import shutil

        shutil.rmtree(self.root)
        self.payload = b"diff --git a/a b/a\n" + b"+complete input line\n" * 120_000
        self.metadata.update(diff_sha256=gateway.review.sha(self.payload), review_bytes=len(self.payload))
        (self.directory / "change.patch").write_bytes(self.payload)
        (self.directory / "review-metadata.json").write_bytes(gateway.review.canonical(self.metadata))
        gateway.prepare(self.root, self.directory, 42, os.getuid())
        self.state, self.prompt = gateway.context(self.root, 42, uid=os.getuid())
        self.reviewer = gateway.Reviewer(self.state, self.prompt, self.root / "public")
        self.result.update({key: self.metadata[key] for key in gateway.BINDINGS})

    def test_large_actual_http_and_worker_path_uses_full_tokens_once(self):
        import http.client
        import io
        import threading
        import tracemalloc

        self.large_subject()
        request = self.request()
        request["instructions"] += " complete system context" * 30_000
        body = gateway.review.canonical(request)
        self.assertGreater(len(body), 2_100_000)
        calls = []
        case = self

        class Process:
            returncode = None

            def __init__(self, argv, **kwargs):
                case.assertIn("--worker", argv)
                index = argv.index("--worker")
                self.limit = int(argv[index + 1])
                suffix = argv.index("--response-byte-limit") if "--response-byte-limit" in argv else len(argv)
                self.response_limit = int(argv[suffix + 1]) if suffix < len(argv) else None
                self.destination = kwargs["stdout"] if self.response_limit is not None else None
                self.json_limits = tuple(int(value) for value in argv[index + 2 : suffix])

            def communicate(self, message=None, timeout=None):
                if message is None:
                    return b"", b""
                self.encoded_size = len(message)
                case.assertLessEqual(len(message), self.limit)
                output = io.BytesIO()
                with (
                    patch.object(gateway.transport.sys, "stdin", type("Input", (), {"buffer": io.BytesIO(message)})()),
                    patch.object(gateway.transport.sys, "stdout", type("Output", (), {"buffer": output})()),
                ):
                    self.returncode = gateway.transport.worker(
                        self.limit, self.json_limits, response_byte_limit=self.response_limit
                    )
                if self.destination is not None:
                    self.destination.write(output.getvalue())
                    self.destination.flush()
                    return None, None
                return output.getvalue(), b""

            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode

        def upstream(payload, credential, timeout, *, counting=False, response_byte_limit=None):
            calls.append((counting, copy.deepcopy(payload)))
            if counting:
                return gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 170_000})
            response = self.response()
            response["usage"] = {"input_tokens": 170_000, "output_tokens": 5, "total_tokens": 170_005}
            return gateway.review.canonical(response)

        tracemalloc.start()
        with (
            gateway.http.server.HTTPServer(("127.0.0.1", 0), gateway.handler_for(self.reviewer)) as server,
            patch.object(gateway.transport.subprocess, "Popen", side_effect=Process),
            patch.object(gateway.transport, "fetch_once", side_effect=upstream),
        ):
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            client = http.client.HTTPConnection(*server.server_address, timeout=20)
            client.request(
                "POST", "/responses", body, {"Authorization": "Bearer fixture", "Content-Type": "application/json"}
            )
            response = client.getresponse()
            response.read()
            self.assertEqual(200, response.status)
            client.close()
            thread.join(20)
            self.assertFalse(thread.is_alive())
        _unused_value_1, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertLess(peak, len(body) * gateway.resources.COPIES)
        self.assertEqual([True, False], [item[0] for item in calls])
        self.assertEqual(calls[0][1], gateway.transport.count_request(calls[1][1]))
        self.assertIn(self.payload.decode(), calls[0][1]["input"])
        self.assertEqual(request["instructions"], calls[0][1]["instructions"])
        self.assertEqual(1, json.loads((self.root / "public/receipt.json").read_text())["provider"]["request_count"])
        self.resource_observation = {
            "wire_bytes": len(body),
            "subject_bytes": len(self.payload),
            "traced_peak_bytes": peak,
            "memory_contract": self.state["resource_contract"],
            "input_tokens": 170_000,
            "model_requests": 1,
            "count_requests": 1,
        }

    def test_oversized_http_framing_fails_before_token_or_model_effect(self):
        import http.client
        import threading

        with (
            gateway.http.server.HTTPServer(("127.0.0.1", 0), gateway.handler_for(self.reviewer)) as server,
            patch.object(gateway.transport, "run_worker") as worker,
        ):
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            client = http.client.HTTPConnection(*server.server_address, timeout=10)
            client.request(
                "POST",
                "/responses",
                b"",
                {
                    "Authorization": "Bearer fixture",
                    "Content-Type": "application/json",
                    "Content-Length": str(gateway.state_limit(self.state) + 1),
                },
            )
            response = client.getresponse()
            response.read()
            self.assertEqual(502, response.status)
            client.close()
            thread.join(10)
            worker.assert_not_called()

    def test_single_cannot_make_a_second_model_call_after_tool_output(self):
        response = self.response()
        response["output"] = [{"type": "function_call", "name": "inspect", "arguments": "{}", "call_id": "one"}]
        with patch.object(
            gateway.transport,
            "run_worker",
            side_effect=[
                gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10}),
                gateway.review.canonical(response),
            ],
        ) as worker:
            self.reviewer.submit(self.request(), "fixture")
            request = self.request()
            request["instructions"] += " second turn"
            with self.assertRaises(gateway.review.ReviewError):
                self.reviewer.submit(request, "fixture")
            self.assertEqual(2, worker.call_count)
        self.assertFalse((self.root / "public/receipt.json").exists())

    def test_hidden_payload_and_duplicate_prompt_fail_before_count(self):
        for extra in ({"hidden_context": "not counted"}, {"input": self.prompt * 2}):
            reviewer = gateway.Reviewer(self.state, self.prompt, self.root / "public")
            with patch.object(gateway.transport, "run_worker") as worker, self.assertRaises(gateway.review.ReviewError):
                reviewer.submit(self.request() | extra, "fixture")
            worker.assert_not_called()
            (self.root / "public/failure.json").unlink()

    def test_full_context_count_precedes_paid_call_and_root_receipt_wins(self):
        calls = []

        def worker(
            request,
            credential,
            deadline,
            *,
            counting=False,
            input_limit=None,
            json_limits=None,
            response_byte_limit=None,
        ):
            calls.append((counting, copy.deepcopy(request)))
            if counting:
                return gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10})
            return gateway.review.canonical(self.response())

        # Real transport + budget; only fixed-network worker is simulated.
        with patch.object(gateway.transport, "run_worker", side_effect=worker):
            self.reviewer.submit(self.request(), "fixture-secret")
        self.assertEqual([item[0] for item in calls], [True, False])
        self.assertEqual(calls[0][1], gateway.transport.count_request(calls[1][1]))
        self.assertIn(self.payload.decode(), calls[0][1]["input"])
        self.assertEqual(calls[1][1]["truncation"], "disabled")
        (self.directory / "result.json").write_text('{"verdict":"forged"}')
        original = gateway.read_owned
        with (
            patch.object(gateway, "root_for", return_value=self.root),
            patch.object(gateway, "read_owned", wraps=gateway.read_owned) as read,
        ):
            # Non-root tests exercise the same checks using the test owner.
            read.side_effect = lambda p, uid, size: original(p, os.getuid(), size)
            with patch.object(gateway, "owned_directory", side_effect=lambda p, uid: None):
                gateway.collect(self.directory, 42)
        self.assertEqual(json.loads((self.directory / "result.json").read_text()), self.result)
        self.assertNotIn("fixture-secret", (self.root / "public/receipt.json").read_text())
        with patch.object(gateway.transport, "run_worker") as worker, self.assertRaises(gateway.review.ReviewError):
            self.reviewer.submit(self.request(), "fixture-secret")
        worker.assert_not_called()

    def test_json_node_and_depth_abuse_fail_in_actual_http_before_count(self):
        import http.client
        import threading

        for schema in ({"enum": [{}] * 80_000}, {"enum": "[" * 65}):
            request = self.request()
            request["text"]["format"]["schema"] = schema
            body = gateway.review.canonical(request)
            if schema == {"enum": "[" * 65}:
                body = b"[" * 65 + b"0" + b"]" * 65
            reviewer = gateway.Reviewer(self.state, self.prompt, self.root / "public")
            with (
                gateway.http.server.HTTPServer(("127.0.0.1", 0), gateway.handler_for(reviewer)) as server,
                patch.object(gateway.transport, "run_worker") as worker,
            ):
                thread = threading.Thread(target=server.handle_request)
                thread.start()
                client = http.client.HTTPConnection(*server.server_address, timeout=10)
                client.request(
                    "POST", "/responses", body, {"Authorization": "Bearer fixture", "Content-Type": "application/json"}
                )
                response = client.getresponse()
                response.read()
                self.assertEqual(502, response.status)
                client.close()
                thread.join(10)
                worker.assert_not_called()
            (self.root / "public/failure.json").unlink()

    def test_json_allocation_guard_cannot_be_bypassed_by_utf16_or_utf32(self):
        for encoding in ("utf-16", "utf-32"):
            body = json.dumps({"enum": [{}] * 80_000}).encode(encoding)
            with self.subTest(encoding=encoding), self.assertRaises((UnicodeError, ValueError)):
                gateway.transport.strict_json(body, json_limits=(16384, 64))

    def small_current_memory(self):
        current = copy.deepcopy(self.state["resource_contract"])
        current.update(
            observed={"fixture_available_bytes": 8 * 1024**2}, reserved_bytes=4 * 1024**2, max_json_nodes=2048
        )
        current["max_wire_bytes"] = (current["reserved_bytes"] - (2048 + 64) * 1024) // 32
        return current

    def test_fresh_memory_snapshot_limits_json_nodes_before_actual_http_parse(self):
        import http.client
        import threading

        current = self.small_current_memory()
        request = self.request()
        request["text"]["format"]["schema"] = {"enum": [{}] * 10_000}
        body = gateway.review.canonical(request)
        self.assertLess(len(body), current["max_wire_bytes"])
        with (
            gateway.http.server.HTTPServer(("127.0.0.1", 0), gateway.handler_for(self.reviewer)) as server,
            patch.object(gateway.resources, "memory_contract", return_value=current) as snapshot,
            patch.object(gateway.transport, "run_worker") as worker,
        ):
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            client = http.client.HTTPConnection(*server.server_address, timeout=10)
            client.request(
                "POST", "/responses", body, {"Authorization": "Bearer fixture", "Content-Type": "application/json"}
            )
            response = client.getresponse()
            response.read()
            self.assertEqual(502, response.status)
            client.close()
            thread.join(10)
            self.assertEqual(1, snapshot.call_count)
            worker.assert_not_called()

    def test_fresh_node_admission_is_bound_to_both_workers_and_receipt(self):
        current = self.small_current_memory()

        def worker(
            request,
            credential,
            deadline,
            *,
            counting=False,
            input_limit=None,
            json_limits=None,
            response_byte_limit=None,
        ):
            self.assertEqual((current["max_json_nodes"] + gateway.resources.ENVELOPE_NODES, 65), json_limits)
            return gateway.review.canonical(
                {"object": "response.input_tokens", "input_tokens": 10} if counting else self.response()
            )

        with (
            patch.object(gateway.resources, "memory_contract", return_value=current) as snapshot,
            patch.object(gateway.transport, "run_worker", side_effect=worker),
        ):
            self.reviewer.submit(self.request(), "fixture")
            self.assertEqual(1, snapshot.call_count)
        receipt = json.loads((self.root / "public/receipt.json").read_text())
        self.assertEqual(current, receipt["admission_resources"]["observed_contract"])
        self.assertEqual(2048, receipt["admission_resources"]["node_limit"])

    def test_over_budget_never_calls_response_endpoint(self):
        def worker(
            request,
            credential,
            deadline,
            *,
            counting=False,
            input_limit=None,
            json_limits=None,
            response_byte_limit=None,
        ):
            self.assertTrue(counting)
            return gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 400_001})

        with (
            patch.object(gateway.transport, "run_worker", side_effect=worker) as worker,
            self.assertRaises(gateway.review.ReviewError),
        ):
            self.reviewer.submit(self.request(), "fixture")
        self.assertEqual(worker.call_count, 1)
        self.assertTrue((self.root / "public/failure.json").exists())
        self.assertFalse((self.root / "public/receipt.json").exists())

    def test_unknown_response_terminal_no_second_count_or_model(self):
        def worker(
            request,
            credential,
            deadline,
            *,
            counting=False,
            input_limit=None,
            json_limits=None,
            response_byte_limit=None,
        ):
            if counting:
                return gateway.review.canonical({"object": "response.input_tokens", "input_tokens": 10})
            raise TimeoutError

        with patch.object(gateway.transport, "run_worker", side_effect=worker) as worker:
            with self.assertRaises(TimeoutError):
                self.reviewer.submit(self.request(), "fixture")
            with self.assertRaises(gateway.review.ReviewError):
                self.reviewer.submit(self.request(), "fixture")
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(json.loads((self.root / "public/failure.json").read_text())["provider_state"], "unknown")

    def test_missing_full_input_blocks_before_count(self):
        with patch.object(gateway.transport, "run_worker") as worker, self.assertRaises(gateway.review.ReviewError):
            self.reviewer.submit({"model": gateway.config.profile()["model"], "input": "summary only"}, "fixture")
        worker.assert_not_called()

    def test_malformed_or_wrong_binding_never_yields_receipt(self):
        self.result["head_sha"] = "b" * 40

        def worker(
            request,
            credential,
            deadline,
            *,
            counting=False,
            input_limit=None,
            json_limits=None,
            response_byte_limit=None,
        ):
            return gateway.review.canonical(
                {"object": "response.input_tokens", "input_tokens": 10} if counting else self.response()
            )

        with (
            patch.object(gateway.transport, "run_worker", side_effect=worker),
            self.assertRaises(gateway.review.ReviewError),
        ):
            self.reviewer.submit(self.request(), "fixture")
        self.assertFalse((self.root / "public/receipt.json").exists())

    def test_protected_closure_drift_rejected(self):
        path = self.root / "code/bounded_review_config.py"
        path.chmod(0o644)
        path.write_text("changed")
        with self.assertRaises(gateway.review.ReviewError):
            gateway.context(self.root, 42, uid=os.getuid())

    def test_omitted_default_and_explicit_single_use_actual_shell_gateway(self):
        import yaml

        workflow = yaml.safe_load((ROOT / ".github/workflows/release-bot-exact-head-review.yml").read_text())
        inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["bounded_mode"]["default"], "single")
        steps = workflow["jobs"]["exact-revision-codex-review"]["steps"]
        install = next(step for step in steps if step.get("id") == "bounded-subject")
        self.assertNotIn("!= ''", install["if"])
        self.assertIn("exact_revision_gateway.py install", install["run"])
        self.assertNotIn("bounded_review_controller.py", install["run"].split("else")[0])
        barrier = next(step for step in steps if step["name"].startswith("Require complete-request"))
        for value, expected in (("", 1), ("false", 1), ("true", 0)):
            result = subprocess.run(  # noqa: S603 -- fixed repository/fixture command and isolated environment.
                ["bash", "-c", barrier["run"]],  # noqa: S607 -- fixed executable from the pinned runtime.
                env={**os.environ, "BUDGETED_GATEWAY_INSTALLED": value},
                capture_output=True,
                check=False,  # The test asserts the exact return code.
            )
            self.assertEqual(result.returncode, expected)
        for name in gateway.CLOSURE:
            if (ROOT / "default/scripts").is_dir():
                self.assertEqual((ROOT / "scripts" / name).read_bytes(), (ROOT / "default/scripts" / name).read_bytes())

    def test_default_and_single_execute_install_shell_without_unit_dispatch(self):
        import yaml

        workflow = yaml.safe_load((ROOT / ".github/workflows/release-bot-exact-head-review.yml").read_text())
        job = workflow["jobs"]["exact-revision-codex-review"]
        self.assertIn("|| 'single'", job["env"]["BOUNDED_MODE"])
        steps = job["steps"]
        shell = next(step["run"] for step in steps if step.get("id") == "bounded-subject")
        binary = Path(self.temporary.name) / "bin"
        binary.mkdir()
        for name, text in {
            "sudo": '#!/bin/bash\nprintf "%s\\n" "$*" >>"$CALLS"\n',
            "python3": "#!/bin/bash\nexit 99\n",
            "jq": "#!/bin/bash\necho 42555\n",
        }.items():
            (binary / name).write_text(text)
            (binary / name).chmod(0o755)
        default = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]["bounded_mode"]["default"]
        for mode in (default, "single"):
            calls = Path(self.temporary.name) / "install-calls"
            output = Path(self.temporary.name) / "install-output"
            calls.write_text("")
            output.write_text("")
            result = subprocess.run(  # noqa: S603 -- fixed repository/fixture command and isolated environment.
                ["bash", "-c", shell],  # noqa: S607 -- fixed executable from the pinned runtime.
                text=True,
                capture_output=True,
                env={
                    **os.environ,
                    "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                    "BOUNDED_MODE": mode,
                    "GITHUB_RUN_ID": "42",
                    "CALLS": str(calls),
                    "GITHUB_OUTPUT": str(output),
                },
                check=False,  # The test asserts the exact return code.
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                calls.read_text().splitlines(),
                ["-n python3 -E -s trusted-controller/exact_revision_gateway.py install --run-id 42"],
            )
            self.assertIn("endpoint=http://127.0.0.1:42555/responses", output.read_text())
            self.assertIn("installed=true", output.read_text())

    def test_actual_collection_shell_consumes_without_engine_after_drop_sudo(self):
        import yaml

        workflow = yaml.safe_load((ROOT / ".github/workflows/release-bot-exact-head-review.yml").read_text())
        steps = workflow["jobs"]["exact-revision-codex-review"]["steps"]
        shell = next(step["run"] for step in steps if step.get("id") == "bounded-collect")
        install_index = next(i for i, step in enumerate(steps) if step.get("id") == "bounded-subject")
        action_index = next(
            i for i, step in enumerate(steps) if step.get("uses", "").startswith("openai/codex-action@")
        )
        collect_index = next(i for i, step in enumerate(steps) if step.get("id") == "bounded-collect")
        self.assertLess(install_index, action_index)
        self.assertLess(action_index, collect_index)
        self.assertEqual("drop-sudo", steps[action_index]["with"]["safety-strategy"])
        enforce = next(
            step for step in steps if step["name"] == "Re-prove exact revision and enforce the Codex verdict"
        )
        self.assertNotIn("if", enforce)  # Default success gating: no failed-collection fallback.
        binary = Path(self.temporary.name) / "post-drop-bin"
        binary.mkdir()
        calls = binary / "calls"
        (binary / "python3").write_text('#!/bin/bash\nprintf "%s\\n" "$*" >>"$CALLS"\n')
        for name in ("docker", "sudo"):
            (binary / name).write_text("#!/bin/bash\nexit 99\n")
        for path in binary.iterdir():
            path.chmod(0o755)
        result = subprocess.run(  # noqa: S603 -- fixed repository/fixture command and isolated environment.
            ["bash", "-c", shell],  # noqa: S607 -- fixed executable from the pinned runtime.
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                "BOUNDED_MODE": "single",
                "GITHUB_RUN_ID": "42",
                "CALLS": str(calls),
                "BASH_ENV": os.devnull,
            },
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            ["-B -E -s /run/exact-review-42/code/exact_revision_gateway.py consume --run-id 42"],
            calls.read_text().splitlines(),
        )

    def test_actual_production_dispatchers_select_single(self):
        import re

        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text()
            if path.name == "release-bot-exact-head-review.yml":
                continue
            for dispatch in re.finditer(r"gh workflow run release-bot-exact-head-review.yml (?:\\\n[^\n]+)+", text):
                command = dispatch.group()
                self.assertIn("-f bounded_mode=single", command, path.name)
                self.assertNotIn("bounded_mode=parent", command)
