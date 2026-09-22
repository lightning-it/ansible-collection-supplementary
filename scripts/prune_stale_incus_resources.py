"""Non-mutating compatibility entry point for retired cross-run Incus pruning.

A smaller GitHub run ID is not evidence that its resources are abandoned.
Keep this CLI for pinned callers, but leave resource destruction to the exact
owning scenario's cleanup. A separate stale-resource collector requires an
authoritative terminal-run/attempt contract and is not implemented here.
"""

from __future__ import annotations

import argparse
import re

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--current-run-id", required=True)
    args = parser.parse_args()
    if REPOSITORY_RE.fullmatch(args.repository) is None:
        parser.error("repository must be an owner/name slug")
    if RUN_ID_RE.fullmatch(args.current_run_id) is None:
        parser.error("current run ID must be a positive integer")
    print("Cross-run Incus pruning disabled: only exact-owning scenario cleanup may delete resources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
