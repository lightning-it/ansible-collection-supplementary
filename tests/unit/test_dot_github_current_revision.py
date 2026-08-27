"""Tests for the independent dot-github current-revision verifier."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import Any


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "verify-dot-github-current-revision.py"
)
SPEC = importlib.util.spec_from_file_location("dot_github_verifier", SCRIPT)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import contract
    raise RuntimeError("Unable to load the dot-github verifier")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SequencedClient:
    """Return one immutable run through a controlled status sequence."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.paths: list[str] = []

    def get(self, path: str) -> dict[str, Any]:
        self.paths.append(path)
        if len(self.payloads) > 1:
            return self.payloads.pop(0)
        return self.payloads[0]


class ProducerRunConvergenceTests(unittest.TestCase):
    def test_waits_for_the_same_producer_run_to_become_completed(self) -> None:
        client = SequencedClient(
            [
                {"id": 42, "status": "queued"},
                {"id": 42, "status": "in_progress"},
                {"id": 42, "status": "completed", "conclusion": "success"},
            ]
        )
        sleeps: list[float] = []

        result = MODULE.wait_for_producer_run(
            client,
            42,
            attempts=3,
            sleep=sleeps.append,
        )

        self.assertEqual("completed", result["status"])
        self.assertEqual([1, 1], sleeps)
        self.assertEqual(
            ["repos/lightning-it/.github/actions/runs/42"] * 3,
            client.paths,
        )

    def test_rejects_an_unrecognized_nonterminal_status(self) -> None:
        client = SequencedClient([{"id": 42, "status": "waiting"}])

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "protected verifier run status is invalid",
        ):
            MODULE.wait_for_producer_run(
                client,
                42,
                attempts=3,
                sleep=lambda _: None,
            )

    def test_rejects_run_identity_drift_while_waiting(self) -> None:
        client = SequencedClient([{"id": 43, "status": "in_progress"}])

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "protected verifier run ID is not exactly bound",
        ):
            MODULE.wait_for_producer_run(
                client,
                42,
                attempts=3,
                sleep=lambda _: None,
            )

    def test_fails_closed_when_completion_does_not_converge(self) -> None:
        client = SequencedClient([{"id": 42, "status": "in_progress"}])
        sleeps: list[float] = []

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "protected verifier run did not become completed",
        ):
            MODULE.wait_for_producer_run(
                client,
                42,
                attempts=3,
                sleep=sleeps.append,
            )

        self.assertEqual([1, 1], sleeps)
        self.assertEqual(3, len(client.paths))


if __name__ == "__main__":
    unittest.main()
