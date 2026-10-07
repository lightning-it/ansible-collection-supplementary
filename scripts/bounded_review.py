"""Inert REP-120 generic coverage kernel; never invokes a reviewer or publishes a gate.

The protected caller owns materialization and authenticates review evidence. This
module checks byte coverage, input identity and finite admission, not that authority.
"""
# Exact JSON schema types deliberately reject bool as int and subclasses.
# pylint: disable=unidiomatic-typecheck

from __future__ import annotations

import bisect
import hashlib
import json
import os
import re
import selectors
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

VERSION = "bounded-review/v1"
FORMAT = "git-diff-binary-full-index-no-renames-v1"
MAX_UNIT_BYTES = 199_999
MAX_UNITS = 64
MAX_TOTAL_BYTES = MAX_UNITS * MAX_UNIT_BYTES
OID = re.compile(r"[0-9a-f]{40}")
HUNK = re.compile(rb"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n")
INDEX = re.compile(rb"index ([0-9a-f]{40})\.\.([0-9a-f]{40})(?: (100644|100755))?\n")
SCHEMA = {
    "version": VERSION,
    "manifest": ["version", "binding", "assets", "policy", "total_bytes", "diff_sha256", "files", "units"],
    "review": ["manifest_sha256", "subject", "payload_sha256", "verdict", "findings", "semantic_coverage"],
    "aggregate": ["manifest_sha256", "diff_sha256", "unit_count", "coverage"],
}


class ReviewError(ValueError):
    """A terminal, content-free fail-closed disposition."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ReviewError(code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def keys(value: Any, expected: set[str], code: str) -> None:
    require(type(value) is dict and set(value) == expected, code)


def integer(value: Any, low: int, high: int, code: str) -> None:
    require(type(value) is int and low <= value <= high, code)


def text(payload: bytes) -> None:
    require(type(payload) is bytes and b"\0" not in payload, "binary-input")
    try:
        payload.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ReviewError("non-utf8-input") from error


def validate_unit(payload: bytes) -> None:
    text(payload)
    integer(len(payload), 1, MAX_UNIT_BYTES, "unit-byte-boundary")


def policy() -> dict[str, Any]:
    """Compatibility policy only. A new limit requires separate measured acceptance."""
    return {
        "version": "compatibility-199999/v1",
        "unit_limit": MAX_UNIT_BYTES,
        "max_units": MAX_UNITS,
        "max_total_bytes": MAX_TOTAL_BYTES,
        "max_review_seconds": 7200,
        "per_review_seconds": 100,
        "max_cost_microusd": 66_000_000,
        "per_review_cost_microusd": 1_000_000,
        "max_wip": 1,
        "limit_basis": "frozen-compatibility-no-new-limit-acceptance",
        "benchmark": {"version": "not-accepted", "sha256": sha(b"no provider capacity benchmark claimed")},
        "safety_reserve": "not-measured-production-activation-blocked",
        "scope": "generic-text-coverage-only",
        "semantic_groups": [],
    }


def validate_policy(value: dict[str, Any]) -> None:
    expected = policy()
    keys(value, set(expected), "policy-shape")
    # Only budgets may be tightened. No caller can activate another unit limit.
    budgets = {
        "max_units",
        "max_total_bytes",
        "max_review_seconds",
        "per_review_seconds",
        "max_cost_microusd",
        "per_review_cost_microusd",
        "max_wip",
    }
    for name in set(expected) - budgets - {"semantic_groups"}:
        require(canonical(value[name]) == canonical(expected[name]), "unsupported-limit-policy")
    for name in budgets:
        integer(value[name], 1, expected[name], "invalid-budget")
    groups = value["semantic_groups"]
    require(type(groups) is list and len(groups) <= MAX_UNITS, "semantic-groups")
    seen = set()
    for group in groups:
        require(type(group) is list and 1 <= len(group) <= 128, "semantic-group")
        for path in group:
            require(type(path) is str and path not in seen, "semantic-group-path")
            validate_path(path)
            seen.add(path)


def assets(prompt: bytes, prompt_version: str) -> dict[str, Any]:
    text(prompt)
    require(0 < len(prompt) <= 1_000_000, "prompt-boundary")
    require(type(prompt_version) is str and 0 < len(prompt_version) <= 100, "prompt-version")
    return {
        "prompt": {"version": prompt_version, "sha256": sha(prompt), "bytes": len(prompt)},
        "schema": {"version": VERSION, "sha256": sha(canonical(SCHEMA))},
        "partitioner": {"version": VERSION, "sha256": sha(Path(__file__).read_bytes())},
    }


def validate_binding(value: dict[str, Any]) -> None:
    keys(value, {"repository", "base", "head", "merge_base", "integration_tree", "format", "scope"}, "binding-shape")
    require(
        type(value["repository"]) is str
        and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value["repository"]) is not None,
        "repository",
    )
    for name in ("base", "head", "merge_base", "integration_tree"):
        require(type(value[name]) is str and OID.fullmatch(value[name]) is not None, "revision")
    require(value["format"] == FORMAT and value["scope"] == "generic", "unsupported-scope")


def validate_path(name: str) -> None:
    """Validate an already decoded path without interpreting Git quote syntax."""
    require(type(name) is str, "unsafe-path")
    try:
        raw = name.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ReviewError("non-utf8-path") from error
    require(0 < len(raw) <= 32768, "path-length")
    text(raw)
    require(
        not name.startswith("/") and all(part not in ("", ".", "..", ".git") for part in name.split("/")),
        "unsafe-path",
    )


def path_value(raw: bytes, prefix: bytes = b"") -> str:
    """Decode Git's C-quoted paths without shell or permissive escape parsing."""
    require(0 < len(raw) <= 32768, "path-length")
    if raw.startswith(b'"'):
        require(raw.endswith(b'"'), "path-quote")
        source, decoded, index = raw[1:-1], bytearray(), 0
        escapes = {
            ord("a"): 7,
            ord("b"): 8,
            ord("t"): 9,
            ord("n"): 10,
            ord("v"): 11,
            ord("f"): 12,
            ord("r"): 13,
            ord('"'): 34,
            ord("\\"): 92,
        }
        while index < len(source):
            item = source[index]
            index += 1
            if item == 92:
                require(index < len(source), "path-escape")
                if source[index] in escapes:
                    item = escapes[source[index]]
                    index += 1
                else:
                    octal = source[index : index + 3]
                    require(len(octal) == 3 and re.fullmatch(rb"[0-3][0-7]{2}", octal) is not None, "path-escape")
                    item = int(octal, 8)
                    index += 3
            decoded.append(item)
        raw = bytes(decoded)
    require(raw.startswith(prefix), "path-prefix")
    raw = raw[len(prefix) :]
    text(raw)
    name = raw.decode("utf-8")
    validate_path(name)
    return name


def inventory(payload: bytes) -> list[dict[str, Any]]:
    """Parse every full-index record and hunk; unknown/binary/mixed records fail."""
    text(payload)
    require(0 < len(payload) <= MAX_TOTAL_BYTES and payload.endswith(b"\n"), "diff-boundary")
    # Split on LF only: CR and Unicode separators are actual payload bytes.
    lines = [line + b"\n" for line in payload.split(b"\n")[:-1]]
    starts, offset = [], 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    starts.append(offset)
    files, i, seen = [], 0, set()
    while i < len(lines):
        start = i
        require(lines[i].startswith(b"diff --git "), "malformed-file-header")
        header = lines[i][11:-1]
        # Under --no-renames the encoded paths differ only in their equal-length
        # prefixes. The midpoint is unambiguous even for names containing ' b/'.
        midpoint = len(header) // 2
        require(len(header) % 2 == 1 and header[midpoint : midpoint + 1] == b" ", "malformed-path-header")
        old_path = path_value(header[:midpoint], b"a/")
        require(old_path == path_value(header[midpoint + 1 :], b"b/"), "rename-record")
        require(old_path not in seen, "duplicate-path")
        seen.add(old_path)
        i += 1
        mode_old = mode_new = None
        operation = "modify"
        mode_fields = []
        for marker, field in (
            (b"old mode ", "old"),
            (b"new mode ", "new"),
            (b"new file mode ", "add"),
            (b"deleted file mode ", "delete"),
        ):
            if i < len(lines) and lines[i].startswith(marker):
                mode_fields.append(field)
                mode = lines[i][len(marker) : -1].decode("ascii", errors="replace")
                require(mode in ("100644", "100755"), "unsupported-mode")
                if field in ("old", "delete"):
                    mode_old = mode
                else:
                    mode_new = mode
                if field in ("add", "delete"):
                    operation = field
                i += 1
        require(mode_fields in ([], ["old", "new"], ["add"], ["delete"]), "contradictory-mode-headers")
        require(mode_fields != ["old", "new"] or mode_old != mode_new, "unchanged-mode-headers")
        require(i < len(lines), "missing-index")
        index_record = INDEX.fullmatch(lines[i])
        require(index_record is not None, "missing-full-index-or-unsupported-change")
        old_blob, new_blob = index_record[1].decode(), index_record[2].decode()
        if index_record[3]:
            require(mode_old is None and mode_new is None, "ambiguous-mode")
            mode_old = mode_new = index_record[3].decode()
        require(
            (mode_old is not None or operation == "add") and (mode_new is not None or operation == "delete"),
            "missing-mode",
        )
        require(
            (old_blob == "0" * 40) == (operation == "add") and (new_blob == "0" * 40) == (operation == "delete"),
            "blob-operation-mismatch",
        )
        i += 1
        hunks = []
        if i < len(lines) and lines[i].startswith(b"--- "):
            require(i + 1 < len(lines) and lines[i + 1].startswith(b"+++ "), "file-markers")
            for marker_line, prefix, absent in (
                (lines[i][4:-1], b"a/", operation == "add"),
                (lines[i + 1][4:-1], b"b/", operation == "delete"),
            ):
                require(
                    marker_line == b"/dev/null"
                    if absent
                    else path_value(marker_line.removesuffix(b"\t"), prefix) == old_path,
                    "file-marker-path",
                )
            i += 2
            previous_old = previous_new = -1
            while i < len(lines) and lines[i].startswith(b"@@ "):
                hunk_start = i
                hunk = HUNK.fullmatch(lines[i])
                require(hunk is not None, "malformed-hunk")
                old_start, old_count = int(hunk[1]), int(hunk[2] or b"1")
                new_start, new_count = int(hunk[3]), int(hunk[4] or b"1")
                require(old_start >= previous_old and new_start >= previous_new, "hunk-order")
                require(old_count + new_count > 0, "empty-hunk")
                previous_old, previous_new = old_start + old_count, new_start + new_count
                i += 1
                old_left, new_left = old_count, new_count
                while old_left or new_left:
                    require(i < len(lines), "truncated-hunk")
                    tag = lines[i][:1]
                    require(tag in (b" ", b"-", b"+"), "malformed-hunk-line")
                    old_left -= tag in (b" ", b"-")
                    new_left -= tag in (b" ", b"+")
                    require(old_left >= 0 and new_left >= 0, "hunk-count")
                    i += 1
                    if i < len(lines) and lines[i] == b"\\ No newline at end of file\n":
                        i += 1
                hunks.append(
                    {
                        "start": starts[hunk_start],
                        "end": starts[i],
                        "old_start": old_start,
                        "old_count": old_count,
                        "new_start": new_start,
                        "new_count": new_count,
                    }
                )
            require(bool(hunks), "missing-hunk")
        else:
            # Only Git's empty add/delete records have an index without hunks.
            empty_blob = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
            require(
                (operation == "add" and new_blob == empty_blob) or (operation == "delete" and old_blob == empty_blob),
                "binary-or-unsupported-record",
            )
        require(i == len(lines) or lines[i].startswith(b"diff --git "), "binary-or-trailing-record")
        files.append(
            {
                "path": old_path,
                "operation": operation,
                "old_blob": old_blob,
                "new_blob": new_blob,
                "old_mode": mode_old,
                "new_mode": mode_new,
                "start": starts[start],
                "end": starts[i],
                "hunks": hunks,
            }
        )
    return files


def partition(
    payload: bytes, boundaries: list[int], max_units: int, groups: list[tuple[int, int]] | None = None
) -> list[bytes]:
    """Prefer records/hunks only when the remaining unit budget can cover the tail."""
    text(payload)
    require(bool(payload), "empty-input")
    integer(max_units, 1, MAX_UNITS, "unit-count-budget")
    groups = groups or []
    cuts = sorted(cut for cut in set(boundaries + [len(payload)]) if not any(a < cut < b for a, b in groups))

    def farthest(start: int) -> int:
        end = min(start + MAX_UNIT_BYTES, len(payload))
        for a, b in groups:
            if a < end < b:
                end = a
        while end < len(payload) and payload[end] & 0xC0 == 0x80:
            end -= 1
        return end

    def fits(start: int, slots: int) -> bool:
        # Taking the farthest legal endpoint minimizes the required units. Every
        # earlier endpoint leaves at least as much payload with the same bound.
        # UTF-8 and indivisible groups are hard constraints; file/hunk and CRLF
        # boundaries are preferences, never a reason to reject a feasible input.
        for _unused_value_1 in range(slots):
            if start == len(payload):
                return True
            end = farthest(start)
            if end <= start:
                return False
            start = end
        return start == len(payload)

    require(fits(0, max_units), "unit-count-budget")
    result, start = [], 0
    while start < len(payload):
        end = farthest(start)
        remaining = max_units - len(result) - 1
        position = bisect.bisect_right(cuts, end) - 1
        if position >= 0 and cuts[position] > start and fits(cuts[position], remaining):
            end = cuts[position]
        elif (
            end - 1 > start
            and payload[end - 1 : end + 1] == b"\r\n"
            and not any(a < end - 1 < b for a, b in groups)
            and fits(end - 1, remaining)
        ):
            end -= 1
        chunk = payload[start:end]
        validate_unit(chunk)
        result.append(chunk)
        require(len(result) <= max_units, "unit-count-budget")
        start = end
    return result


def plan(
    payload: bytes, binding: dict[str, Any], prompt: bytes, prompt_version: str, limits: dict[str, Any]
) -> tuple[dict[str, Any], list[bytes]]:
    validate_binding(binding)
    validate_policy(limits)
    require(type(payload) is bytes and 0 < len(payload) <= limits["max_total_bytes"], "candidate-budget")
    files = inventory(payload)
    # File boundaries take priority; only files exceeding the bound need hunks.
    boundaries = [file["end"] for file in files]
    for file in files:
        if file["end"] - file["start"] > MAX_UNIT_BYTES:
            boundaries.extend(hunk["end"] for hunk in file["hunks"])
    grouped_ranges = []
    by_path = {file["path"]: file for file in files}
    for group in limits["semantic_groups"]:
        require(all(path in by_path for path in group), "missing-semantic-group-path")
        start = min(by_path[path]["start"] for path in group)
        end = max(by_path[path]["end"] for path in group)
        grouped_ranges.append((start, end))
    merged_ranges: list[tuple[int, int]] = []
    for start, end in sorted(grouped_ranges):
        if merged_ranges and start < merged_ranges[-1][1]:
            start, end = merged_ranges[-1][0], max(end, merged_ranges.pop()[1])
        require(end - start <= MAX_UNIT_BYTES, "semantic-group-over-limit")
        merged_ranges.append((start, end))
        boundaries.extend((start, end))
    chunks = partition(payload, boundaries, limits["max_units"], merged_ranges)
    reviews = len(chunks) + 1  # exactly one manifest/integration review
    require(reviews * limits["per_review_seconds"] <= limits["max_review_seconds"], "time-admission")
    require(reviews * limits["per_review_cost_microusd"] <= limits["max_cost_microusd"], "cost-admission")
    units, start = [], 0
    for number, chunk in enumerate(chunks):
        end = start + len(chunk)
        spans = []
        for file_number, file in enumerate(files):
            if start < file["end"] and end > file["start"]:
                spans.append(
                    {
                        "file": file_number,
                        "start": max(start, file["start"]),
                        "end": min(end, file["end"]),
                        "hunks": [n for n, h in enumerate(file["hunks"]) if start < h["end"] and end > h["start"]],
                    }
                )
        units.append(
            {"ordinal": number, "start": start, "end": end, "bytes": len(chunk), "sha256": sha(chunk), "spans": spans}
        )
        start = end
    manifest = {
        "version": VERSION,
        "binding": binding,
        "assets": assets(prompt, prompt_version),
        "policy": {"value": limits, "sha256": sha(canonical(limits))},
        "total_bytes": len(payload),
        "diff_sha256": sha(payload),
        "files": files,
        "units": units,
    }
    # Detach caller-owned objects; mutation cannot silently update this snapshot.
    return json.loads(canonical(manifest)), chunks


def verify(
    manifest: dict[str, Any],
    chunks: list[bytes],
    payload: bytes,
    binding: dict[str, Any],
    prompt: bytes,
    prompt_version: str,
    limits: dict[str, Any],
) -> str:
    """Re-plan from independently current protected input, never manifest claims."""
    expected, expected_chunks = plan(payload, binding, prompt, prompt_version, limits)
    require(canonical(manifest) == canonical(expected), "manifest-drift")
    require(type(chunks) is list and len(chunks) == len(expected_chunks), "missing-or-extra-unit")
    for chunk, expected_chunk in zip(chunks, expected_chunks, strict=True):
        validate_unit(chunk)
        require(chunk == expected_chunk, "unit-content-or-order-drift")
    require(b"".join(chunks) == payload, "reconstruction-failure")
    return sha(canonical(expected))


def aggregate(
    manifest: dict[str, Any],
    chunks: list[bytes],
    payload: bytes,
    binding: dict[str, Any],
    prompt: bytes,
    prompt_version: str,
    limits: dict[str, Any],
    reviews: list[dict[str, Any]],
    admission: Admission,
) -> dict[str, Any]:
    """Check already authenticated receipts; this return value is NOT a review.

    The caller must authenticate each result and enforce Admission before dispatch.
    JSON fields, hashes and a claimed reviewer identity are not authentication.
    """
    digest = verify(manifest, chunks, payload, binding, prompt, prompt_version, limits)
    require(
        admission.manifest_sha256 == digest
        and not admission.failed
        and admission.active is None
        and admission.next == len(chunks) + 1,
        "incomplete-admission",
    )
    require(type(reviews) is list and len(reviews) == len(chunks) + 1, "review-cardinality")
    for number, review in enumerate(reviews):
        validate_review(manifest, number, review)
    return {"manifest_sha256": digest, "diff_sha256": sha(payload), "unit_count": len(chunks), "coverage": "PASS"}


def validate_review(manifest: dict[str, Any], number: int, review: dict[str, Any]) -> None:
    """Validate one already authenticated result before admitting more work."""
    integer(number, 0, len(manifest["units"]), "review-ordinal")
    keys(review, set(SCHEMA["review"]), "review-shape")
    integration = number == len(manifest["units"])
    require(review["manifest_sha256"] == sha(canonical(manifest)), "stale-review")
    require(review["subject"] == ("integration" if integration else f"unit:{number}"), "review-order-or-duplicate")
    require(
        review["payload_sha256"] == (manifest["diff_sha256"] if integration else manifest["units"][number]["sha256"]),
        "substituted-review",
    )
    require(review["verdict"] == "PASS" and review["findings"] == [], "review-failed")
    require(
        review["semantic_coverage"] == ("complete-cross-unit" if integration else "complete-unit"),
        "unevaluated-semantic-risk",
    )


class Admission:
    """One-use serial reservation ledger for a protected caller (no retries).

    Persist and lock this state in the caller before external dispatch; an in-memory
    instance alone cannot deduplicate separate processes or workflow runs.
    """

    def __init__(self, manifest: dict[str, Any], *, start_seconds: int):
        validate_policy(manifest["policy"]["value"])
        integer(start_seconds, 0, 2**63 - 1, "clock")
        self.manifest_sha256 = sha(canonical(manifest))
        self.limits = json.loads(canonical(manifest["policy"]["value"]))
        self.count = len(manifest["units"]) + 1
        integer(self.count, 2, self.limits["max_units"] + 1, "unit-count-budget")
        self.started = self.last = start_seconds
        self.next = self.reserved_cost = 0
        self.active: int | None = None
        self.failed = False

    def reserve(self, ordinal: int, *, now_seconds: int) -> None:
        try:
            integer(now_seconds, self.last, 2**63 - 1, "clock")
            integer(ordinal, 0, self.count - 1, "review-ordinal")
            require(not self.failed and self.active is None and ordinal == self.next, "wip-or-consumed")
            require(
                now_seconds + self.limits["per_review_seconds"] <= self.started + self.limits["max_review_seconds"],
                "time-admission",
            )
            require(
                self.reserved_cost + self.limits["per_review_cost_microusd"] <= self.limits["max_cost_microusd"],
                "cost-admission",
            )
        except ReviewError:
            self.failed = True
            raise
        self.reserved_cost += self.limits["per_review_cost_microusd"]
        self.active = now_seconds
        self.next += 1
        self.last = now_seconds

    def finish(self, *, now_seconds: int, cost_microusd: int, passed: bool) -> None:
        try:
            integer(now_seconds, self.last, 2**63 - 1, "clock")
            integer(cost_microusd, 0, self.limits["per_review_cost_microusd"], "cost-overrun")
            require(not self.failed and self.active is not None and passed is True, "review-failed")
            require(now_seconds - self.active <= self.limits["per_review_seconds"], "review-timeout")
            require(now_seconds - self.started <= self.limits["max_review_seconds"], "total-timeout")
        except ReviewError:
            self.failed = True
            raise
        self.active = None
        self.last = now_seconds


def git(repo: Path, arguments: list[str], *, home: Path, bound: int = MAX_TOTAL_BYTES) -> bytes:
    """Bound stdout, stderr and time; never inherit credentials or Git redirects."""
    environment = {
        "PATH": os.defpath,
        "HOME": str(home),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
    }
    command = [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "protocol.file.allow=always",
        "-c",
        "protocol.ext.allow=never",
        "-c",
        "user.name=Coverage fixture",
        "-c",
        "user.email=coverage@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "core.quotePath=true",
        "-c",
        "safe.directory=/workspace",
        "-C",
        str(repo),
        *arguments,
    ]
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment) as process:
        output = bytearray()
        stderr_size = 0
        deadline = time.monotonic() + 120
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                selector.register(process.stderr, selectors.EVENT_READ)
                while selector.get_map():
                    require(time.monotonic() < deadline, "git-timeout")
                    for key, _unused_value_2 in selector.select(0.1):
                        block = os.read(key.fileobj.fileno(), 65536)
                        if not block:
                            selector.unregister(key.fileobj)
                        elif key.fileobj is process.stdout:
                            output.extend(block)
                            require(len(output) <= bound, "git-output-budget")
                        else:
                            stderr_size += len(block)
                            require(stderr_size <= 65536, "git-diagnostic-budget")
            require(process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0, "git-failed")
        except BaseException:
            process.kill()
            process.wait()
            raise
    return bytes(output)


def capture(repo: Path, repository: str, base: str, head: str) -> tuple[bytes, dict[str, Any]]:
    """Offline object materialization in a private clone, never a candidate checkout.

    Live repository identity, protected refs and source authority are the caller's
    responsibility. The supplied OIDs are rechecked; no network fetch is performed.
    """
    for revision in (base, head):
        require(type(revision) is str and OID.fullmatch(revision) is not None, "revision")
    with tempfile.TemporaryDirectory(prefix="bounded-review-") as directory:
        home = Path(directory)
        source = home / "objects"
        git(home, ["clone", "--bare", "--shared", "--", str(repo.resolve()), str(source)], home=home)
        for revision in (base, head):
            require(
                git(source, ["rev-parse", "--verify", revision + "^{commit}"], home=home).strip().decode() == revision,
                "commit-binding",
            )
        # A local clone initially inherits the source's mutable HEAD. Pin its
        # default attribute tree to the bound base before merge/diff operations.
        git(source, ["symbolic-ref", "HEAD", "refs/heads/coverage-base"], home=home)
        git(source, ["update-ref", "refs/heads/coverage-base", base], home=home)
        merge_base = git(source, ["merge-base", "--all", base, head], home=home).strip().decode()
        require(OID.fullmatch(merge_base) is not None, "ambiguous-merge-base")
        # Requires merge-tree --write-tree in the pinned Devtools Git. No checkout,
        # hooks, filters or candidate-supplied custom driver configuration is used.
        tree = git(source, ["merge-tree", "--write-tree", base, head], home=home).strip().decode()
        require(OID.fullmatch(tree) is not None, "integration-conflict")
        diff_args = [
            "diff",
            "--binary",
            "--full-index",
            "--no-renames",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--diff-algorithm=myers",
            "--no-indent-heuristic",
            "--unified=3",
            "--inter-hunk-context=0",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            base,
            tree,
            "--",
        ]
        payload = git(source, diff_args, home=home)
        files = inventory(payload)
        # Text-looking patches can conceal binary blobs via attributes or contain
        # invalid UTF-8 outside the changed lines. Check every complete touched blob.
        blobs = {file[key] for file in files for key in ("old_blob", "new_blob")} - {"0" * 40}
        require(len(blobs) <= 8192, "blob-count-budget")
        total = 0
        for blob in sorted(blobs):
            size = int(git(source, ["cat-file", "-s", blob], home=home, bound=100))
            total += size
            require(total <= 4 * MAX_TOTAL_BYTES, "blob-work-budget")
            data = git(source, ["cat-file", "blob", blob], home=home, bound=max(1, size))
            require(
                len(data) == size and hashlib.sha1(f"blob {size}\0".encode() + data).hexdigest() == blob,
                "blob-identity",
            )
            text(data)
        binding = {
            "repository": repository,
            "base": base,
            "head": head,
            "merge_base": merge_base,
            "integration_tree": tree,
            "format": FORMAT,
            "scope": "generic",
        }
        validate_binding(binding)
        return payload, binding
