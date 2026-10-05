# Managed by lightning-it/shared-assets-lit. Do not edit downstream copies.
"""Regression tests for the reciprocal dot-github verifier."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify-dot-github-current-revision.py"
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
    def test_waits_for_the_same_nonterminal_run_to_complete(self) -> None:
        client = SequencedClient(
            [
                {"id": 42, "status": "pending"},
                {"id": 42, "status": "requested"},
                {"id": 42, "status": "waiting"},
                {"id": 42, "status": "queued"},
                {"id": 42, "status": "in_progress"},
                {"id": 42, "status": "completed", "conclusion": "success"},
            ]
        )
        sleeps: list[float] = []

        result = MODULE.wait_for_completed_producer(
            client,
            42,
            attempts=6,
            sleep=sleeps.append,
        )

        self.assertEqual("completed", result["status"])
        self.assertEqual([2, 2, 2, 2, 2], sleeps)
        self.assertEqual(
            ["repos/lightning-it/.github/actions/runs/42"] * 6,
            client.paths,
        )

    def test_rejects_an_unrecognized_nonterminal_status(self) -> None:
        client = SequencedClient([{"id": 42, "status": "unknown"}])

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "verifier run status is invalid: 'unknown'",
        ):
            MODULE.wait_for_completed_producer(
                client,
                42,
                attempts=2,
                sleep=lambda _: None,
            )

    def test_rejects_a_malformed_nonterminal_status(self) -> None:
        client = SequencedClient([{"id": 42, "status": []}])

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            r"verifier run status is invalid: \[\]",
        ):
            MODULE.wait_for_completed_producer(
                client,
                42,
                attempts=2,
                sleep=lambda _: None,
            )

    def test_rejects_run_identity_drift_while_waiting(self) -> None:
        client = SequencedClient([{"id": 43, "status": "in_progress"}])

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "protected verifier run ID is not exactly bound",
        ):
            MODULE.wait_for_completed_producer(
                client,
                42,
                attempts=2,
                sleep=lambda _: None,
            )

    def test_fails_closed_when_completion_does_not_converge(self) -> None:
        client = SequencedClient([{"id": 42, "status": "in_progress"}])
        sleeps: list[float] = []

        with self.assertRaisesRegex(
            MODULE.VerificationError,
            "protected verifier run did not complete",
        ):
            MODULE.wait_for_completed_producer(
                client,
                42,
                attempts=2,
                sleep=sleeps.append,
            )

        self.assertEqual([2], sleeps)
        self.assertEqual(2, len(client.paths))


class PilotEventModeTests(unittest.TestCase):
    def test_main_enables_single_observation_only_for_exact_target_and_enabled_flag(self):
        for repository, flag, attempts in (
            ("lightning-it/.github", "enabled", 1),
            ("lightning-it/.github", "disabled", 60),
            ("lightning-it/.github", "", 60),
            ("lightning-it/.github", "true", 60),
            ("lightning-it/other", "enabled", 60),
        ):
            with (
                self.subTest(repository=repository, flag=flag),
                mock.patch.dict(
                    MODULE.os.environ,
                    {
                        "REPOSITORY": repository,
                        "LI219_EVENT_MODE": flag,
                    },
                    clear=True,
                ),
                mock.patch.object(MODULE, "GitHubClient"),
                mock.patch.object(MODULE, "verify") as verify,
                mock.patch("builtins.print"),
            ):
                self.assertEqual(0, MODULE.main())
                self.assertEqual(attempts, verify.call_args.kwargs["attempts"])

    def test_delayed_visibility_is_blocked_then_observed_by_later_evaluation(self):
        clock = {"seconds": 0}
        base, head = "a" * 40, "b" * 40
        reservation = {
            "name": MODULE.RESERVATION_NAME,
            "external_id": f"rep60-required-workflow:v3:42:7:{base}:{head}",
            "status": "completed",
            "conclusion": "success",
        }
        reads = []

        class DelayedClient:
            def get(self, path):
                reads.append(path)
                visible = clock["seconds"] >= 180
                if "/check-runs?" in path:
                    return {
                        "total_count": 1 if visible else 0,
                        "check_runs": [reservation] if visible else [],
                    }
                return {
                    "id": 42,
                    "status": "completed" if visible else "in_progress",
                    "conclusion": "success" if visible else None,
                }

        client = DelayedClient()
        sleep = mock.Mock(side_effect=AssertionError("event mode must not sleep"))
        with self.assertRaisesRegex(MODULE.VerificationError, "did not become successful"):
            MODULE.wait_for_reservation(client, 7, base, head, attempts=1, sleep=sleep)
        with self.assertRaisesRegex(MODULE.VerificationError, "did not complete"):
            MODULE.wait_for_completed_producer(client, 42, attempts=1, sleep=sleep)
        self.assertEqual(2, len(reads))
        # Completion/reconciliation starts a later evaluation; no polling or real wait.
        clock["seconds"] = 180
        self.assertEqual(
            reservation,
            MODULE.wait_for_reservation(
                client,
                7,
                base,
                head,
                attempts=1,
                sleep=sleep,
            ),
        )
        self.assertEqual(
            "success",
            MODULE.wait_for_completed_producer(
                client,
                42,
                attempts=1,
                sleep=sleep,
            )["conclusion"],
        )
        self.assertEqual(4, len(reads))
        sleep.assert_not_called()

    def test_legacy_reservation_wait_keeps_sixty_observations(self):
        client = SequencedClient([{"total_count": 0, "check_runs": []}])
        sleeps = []
        with self.assertRaises(MODULE.VerificationError):
            MODULE.wait_for_reservation(
                client,
                7,
                "a" * 40,
                "b" * 40,
                attempts=60,
                sleep=sleeps.append,
            )
        self.assertEqual(60, len(client.paths))
        self.assertEqual([10] * 59, sleeps)

    def test_legacy_run_wait_keeps_sixty_observations(self):
        client = SequencedClient([{"id": 42, "status": "in_progress"}])
        sleeps = []
        with self.assertRaises(MODULE.VerificationError):
            MODULE.wait_for_completed_producer(client, 42, attempts=60, sleep=sleeps.append)
        self.assertEqual(60, len(client.paths))
        self.assertEqual([2] * 59, sleeps)


if __name__ == "__main__":
    unittest.main()
