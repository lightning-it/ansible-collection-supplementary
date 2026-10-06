"""SINGLE memory/framing resources; never an estimate of review token count.

Use the smallest physical, visible cgroup-ancestor and process headroom. Reserve
half for the rest of the runner. Separately account for JSON nodes (1024 bytes
per node across decoder/count/worker copies) and 32 simultaneous wire-byte copies
including Unicode and ASCII serialization. The lexical preflight bounds JSON
allocation before json.loads; full review text remains one untruncated string.
Only the provider's authenticated complete input count admits model inference.
"""
# Exact JSON schema types deliberately reject bool as int and subclasses.
# pylint: disable=unidiomatic-typecheck

from __future__ import annotations

import os
import re
import resource
from pathlib import Path, PurePosixPath

VERSION = "single-json-working-set/v2"
COPIES = 32
MAX_JSON_NODES = 16_384
NODE_BYTES = 1024
ENVELOPE_NODES = 64
MAX_JSON_DEPTH = 64


def cgroup_headroom() -> dict[str, int]:
    memberships = []
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        hierarchy, controllers, location = line.split(":", 2)
        if hierarchy == "0" and not controllers:
            memberships.append(("cgroup2", location))
        elif "memory" in controllers.split(","):
            memberships.append(("cgroup", location))
    if not memberships or len({kind for kind, _unused_value_1 in memberships}) != len(memberships):
        raise ValueError("single-memory-cgroup-membership")
    # In a hybrid hierarchy the explicit v1 memory controller owns the limit.
    # A unified entry may coexist; duplicate entries of either kind remain invalid.
    memory_memberships = [item for item in memberships if item[0] == "cgroup"]
    kind, location = (memory_memberships or memberships)[0]

    def unescape(value):
        return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), value)

    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, separator, after = line.partition(" - ")
        if not separator:
            raise ValueError("single-memory-mountinfo")
        left, right = before.split(), after.split()
        if right[0] == kind and (kind == "cgroup2" or "memory" in right[2].split(",")):
            mounts.append((PurePosixPath(unescape(left[3])), Path(unescape(left[4]))))
    if len(mounts) != 1 or not location.startswith("/") or ".." in PurePosixPath(location).parts:
        raise ValueError("single-memory-cgroup-mount")
    mount_root, mount = mounts[0]
    membership = PurePosixPath(location)
    try:
        relative = membership.relative_to(mount_root)
    except ValueError:
        # A cgroup namespace can expose membership relative to its own root.
        # Prove this process belongs to the proposed visible leaf before use.
        relative = membership.relative_to("/")
        pids = (mount / str(relative) / "cgroup.procs").read_text().splitlines()
        if str(os.getpid()) not in pids:
            raise ValueError("single-memory-cgroup-namespace")
    leaf = mount / str(relative)
    fields = {}
    index = 0
    while True:
        maximum_name, current_name = (
            ("memory.max", "memory.current")
            if kind == "cgroup2"
            else ("memory.limit_in_bytes", "memory.usage_in_bytes")
        )
        try:
            maximum = (leaf / maximum_name).read_text().strip()
        except FileNotFoundError:
            # The real v2 hierarchy root is exempt from resource control and
            # has no memory.max. A child or subtree mount must still expose it.
            # Confirm the root controller interface, rather than treating any
            # missing limit file as unlimited.
            if (
                kind == "cgroup2"
                and leaf == mount
                and mount_root == PurePosixPath("/")
                and "memory" in (leaf / "cgroup.controllers").read_text().split()
            ):
                break
            raise
        if maximum != "max":
            fields[f"cgroup_ancestor_{index}_available_bytes"] = int(maximum) - int((leaf / current_name).read_text())
        if leaf == mount:
            break
        leaf = leaf.parent
        index += 1
    return fields


def memory_contract() -> dict:
    fields = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _unused_value_2, value = line.partition(":")
        if key == "MemAvailable":
            fields["host_available_bytes"] = int(value.split()[0]) * 1024
    if not fields.get("host_available_bytes", 0) > 0:
        raise ValueError("single-memory-evidence-unavailable")
    fields.update(cgroup_headroom())
    limit, _unused_value_3 = resource.getrlimit(resource.RLIMIT_AS)
    if limit != resource.RLIM_INFINITY:
        virtual = int(Path("/proc/self/statm").read_text().split()[0]) * os.sysconf("SC_PAGE_SIZE")
        fields["process_available_bytes"] = limit - virtual
    available = min(fields.values())
    if available <= 0:
        raise ValueError("single-memory-resource-exhausted")
    reserved = available // 2
    nodes = min(MAX_JSON_NODES, reserved // (2 * NODE_BYTES))
    wire = (reserved - (nodes + ENVELOPE_NODES) * NODE_BYTES) // COPIES
    if nodes < ENVELOPE_NODES or wire <= 0:
        raise ValueError("single-memory-resource-exhausted")
    return {
        "version": VERSION,
        "observed": fields,
        "reserved_bytes": reserved,
        "working_set_multiplier": COPIES,
        "node_bytes": NODE_BYTES,
        "max_json_nodes": nodes,
        "envelope_nodes": ENVELOPE_NODES,
        "max_json_depth": MAX_JSON_DEPTH,
        "max_wire_bytes": wire,
    }


def wire_limit() -> int:
    return memory_contract()["max_wire_bytes"]


def preflight_json(payload: bytes | str, node_limit: int, depth_limit: int) -> None:
    """Count containers, scalar values and keys without building a JSON tree.

    JSON validity, duplicate keys and constants are checked by strict_json after
    this allocation guard. String contents never contribute structural nodes.
    """
    if type(payload) is str:
        payload = payload.encode("utf-8")
    if type(payload) is not bytes or type(node_limit) is not int or type(depth_limit) is not int:
        raise ValueError("single-json-resource-shape")
    nodes = depth = index = 0
    length = len(payload)
    delimiters = re.compile(rb"[\s,\]}:]")
    while index < length:
        char = payload[index]
        if char in b" \t\n\r,:":
            index += 1
            continue
        if char in b"}]":
            depth -= 1
            if depth < 0:
                raise ValueError("single-json-depth")
            index += 1
            continue
        nodes += 1
        if nodes > node_limit:
            raise ValueError("single-json-node-budget")
        if char in b"{[":
            depth += 1
            if depth > depth_limit:
                raise ValueError("single-json-depth")
            index += 1
        elif char == 34:
            index += 1
            while True:
                end = payload.find(b'"', index)
                if end < 0:
                    raise ValueError("single-json-string")
                slash = end - 1
                while slash >= 0 and payload[slash] == 92:
                    slash -= 1
                index = end + 1
                if (end - slash - 1) % 2 == 0:
                    break
        else:
            end = delimiters.search(payload, index)
            index = end.start() if end else length
    if depth != 0:
        raise ValueError("single-json-depth")
