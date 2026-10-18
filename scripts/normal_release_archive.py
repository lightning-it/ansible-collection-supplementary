"""Cryptographically bound replay of publication-time native observations.

This module never creates an approval or retries a mutation. Archived API
observations are historical evidence, not simulated fresh native runs.
"""

# Wire identities must reject bool-as-int.
# pylint: disable=unidiomatic-typecheck
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

SNAPSHOT = "normal-release-native-evidence.json"
BUNDLE = "normal-release-native-evidence.sigstore.json"
MAX_BYTES = 50 * 1024 * 1024
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
MAX_READS = 4096
WORKFLOW = ".github/workflows/collection-publish.yml"


def require(value, message):
    if not value:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode() + b"\n"


def release_state(published):
    """Keep every release/asset field except mutable per-asset download counts."""
    require(isinstance(published, dict), "archive-release-response")
    result = copy.deepcopy(published)
    if "assets" in result:
        require(isinstance(result["assets"], list), "archive-release-assets")
        for asset in result["assets"]:
            require(isinstance(asset, dict), "archive-release-asset")
            asset.pop("download_count", None)
    return result


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "archive-duplicate-json-key")
        result[key] = value
    return result


def bounded_file(path, maximum):
    require(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum, "archive-file-bound")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(0 < len(raw) <= maximum, "archive-file-bound")
    return raw


def decode(raw):
    require(0 < len(raw) <= MAX_BYTES, "archive-size-bound")
    # Bound nesting and structural nodes before allocating decoded JSON.
    quoted = escaped = False
    depth = nodes = 0
    for byte in raw:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            nodes += 1
        elif byte in (93, 125):
            depth -= 1
        elif byte in (44, 58):
            nodes += 1
        require(0 <= depth <= 64 and nodes <= 500000, "archive-json-resource-bound")
    value = json.loads(raw, object_pairs_hook=unique)
    require(canonical(value) == raw, "archive-noncanonical-json")
    return value


def binding(repository, repository_id, release, base, head, source):
    require(re.fullmatch(r"lightning-it/[A-Za-z0-9_.-]+", repository), "archive-repository")
    require(type(repository_id) is str and re.fullmatch(r"[1-9][0-9]*", repository_id), "archive-repository-id")
    require(
        all(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) for value in (release, base, head, source)),
        "archive-revision",
    )
    return {
        "repository": repository,
        "repository_id": repository_id,
        "release": release,
        "base": base,
        "head": head,
        "control_source": source,
    }


def artifact_identity(repository, run, name, filename):
    require(
        type(run.get("id")) is int
        and run["id"] > 0
        and type(run.get("run_attempt")) is int
        and run["run_attempt"] > 0
        and re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", "")),
        "archive-artifact-origin",
    )
    if filename == "preparation-inputs.json":
        # The original caller still authenticates the protected producer and
        # requires exact input_record(receipt, prepared) equality on replay.
        require(name == f"normal-release-preparation-{run['run_attempt']}", "archive-preparation-artifact-attempt")
    else:
        require(
            filename in {"control-proof.json", "control-operation.json"}
            and re.fullmatch(r"control-(?:proof|operation)-[1-9][0-9]*", name),
            "archive-artifact-name",
        )
        require(
            name.startswith("control-operation-") == (filename == "control-operation.json"), "archive-artifact-kind"
        )
    return [repository, run["id"], run["run_attempt"], run["head_sha"], name, filename]


def artifact_metadata(value, name):
    require(
        type(value) is dict
        and type(value.get("id")) is int
        and value["id"] > 0
        and value.get("name") == name
        and value.get("expired") is False
        and type(value.get("size_in_bytes")) is int
        and 0 < value["size_in_bytes"] <= MAX_BYTES,
        "archive-artifact-metadata",
    )
    require(
        value.get("digest") is None
        or (type(value["digest"]) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value["digest"])),
        "archive-artifact-digest",
    )


class ArtifactReads:
    """Pause outer capture only for the original authenticated artifact reader."""

    def __init__(self, api, repository, run):
        self.api = api
        self.path = f"repos/{repository}/actions/runs/{run['id']}/artifacts"
        self.inventory = None

    def pages(self, path, key=None):
        require(path == self.path and key == "artifacts" and self.inventory is None, "archive-artifact-read-scope")
        self.inventory = copy.deepcopy(self.api.pages(path, key))
        return copy.deepcopy(self.inventory)


class Record:
    """Record only completed read responses used by the unchanged verifier."""

    def __init__(self, api, expected):
        self.api = api
        self.expected = expected
        self.reads = []
        self.size = 0

    def add(self, kind, args, value):
        entry = {"kind": kind, "args": args, "value": value}
        self.size += len(canonical(entry))
        require(len(self.reads) < MAX_READS and self.size <= MAX_BYTES, "archive-observation-bound")
        self.reads.append(copy.deepcopy(entry))
        return value

    def path(self, path):
        require(type(path) is str and path.startswith(f"repos/{self.expected['repository']}/"), "archive-read-scope")

    def call(self, path, *, method="GET", data=None):
        self.path(path)
        require(method == "GET" and data is None, "archive-read-only")
        return self.add("call", [path], self.api.call(path))

    def pages(self, path, key=None):
        self.path(path)
        return self.add("pages", [path, key], self.api.pages(path, key))

    def file(self, repository, path, revision):
        require(repository == self.expected["repository"], "archive-read-scope")
        raw = self.api.file(repository, path, revision)
        self.add("file", [repository, path, revision], base64.b64encode(raw).decode("ascii"))
        return raw

    def native_job_log(self, repository, job):
        require(repository == self.expected["repository"], "archive-read-scope")
        return self.add("native_job_log", [repository, job], self.api.native_job_log(repository, job))

    def artifact(self, original, _api, repository, run, name, filename):
        require(repository == self.expected["repository"], "archive-read-scope")
        args = artifact_identity(repository, run, name, filename)
        reader = ArtifactReads(self.api, repository, run)
        value = original(reader, repository, run, name, filename)
        require(type(reader.inventory) is list, "archive-artifact-inventory-missing")
        selected = [item for item in reader.inventory if item.get("name") == name and item.get("expired") is False]
        require(len(selected) == 1, "archive-artifact-selection")
        artifact_metadata(selected[0], name)
        self.add("artifact", args, {"metadata": selected[0], "record": value})
        return value

    def finish(self, result):
        value = {
            "version": 1,
            "kind": "normal-release-native-observations",
            "binding": self.expected,
            "reads": self.reads,
            "result": result,
        }
        raw = canonical(value)
        require(len(raw) <= MAX_BYTES, "archive-size-bound")
        return raw


class Replay:
    """No live API or artifact downloader is reachable through this adapter."""

    def __init__(self, value, expected, current_main):
        require(
            type(value) is dict
            and set(value) == {"version", "kind", "binding", "reads", "result"}
            and type(value["version"]) is int
            and value["version"] == 1
            and value["kind"] == "normal-release-native-observations"
            and value["binding"] == expected,
            "archive-binding",
        )
        require(type(value["reads"]) is list and 0 < len(value["reads"]) <= MAX_READS, "archive-observation-bound")
        self.value = value
        self.expected = expected
        self.current_main = current_main
        self.index = 0

    def take(self, kind, args):
        require(self.index < len(self.value["reads"]), "archive-missing-observation")
        entry = self.value["reads"][self.index]
        require(
            type(entry) is dict
            and set(entry) == {"kind", "args", "value"}
            and entry["kind"] == kind
            and entry["args"] == args,
            "archive-observation-order-or-binding",
        )
        self.index += 1
        return copy.deepcopy(entry["value"])

    def call(self, path, *, method="GET", data=None):
        require(method == "GET" and data is None, "archive-read-only")
        value = self.take("call", [path])
        if path == f"repos/{self.expected['repository']}/git/ref/heads/main":
            require(value.get("object", {}).get("sha") == self.expected["release"], "archive-original-main-drift")
            # Only this tip is a separately authenticated current observation.
            value["object"]["sha"] = self.current_main
        return value

    def pages(self, path, key=None):
        return self.take("pages", [path, key])

    def file(self, repository, path, revision):
        return base64.b64decode(self.take("file", [repository, path, revision]), validate=True)

    def native_job_log(self, repository, job):
        return self.take("native_job_log", [repository, job])

    def artifact(self, _original, _api, repository, run, name, filename):
        value = self.take("artifact", artifact_identity(repository, run, name, filename))
        require(type(value) is dict and set(value) == {"metadata", "record"}, "archive-artifact-record")
        artifact_metadata(value["metadata"], name)
        return value["record"]

    def finish(self, result):
        require(self.index == len(self.value["reads"]) and result == self.value["result"], "archive-incomplete-replay")


@contextmanager
def artifact_reader(core, adapter):
    original = core.artifact_record
    core.artifact_record = lambda api, repo, run, name, filename: adapter.artifact(
        original, api, repo, run, name, filename
    )
    try:
        yield
    finally:
        core.artifact_record = original


def verify_files(snapshot, bundle, repository, repository_id, release):
    raw = bounded_file(snapshot, MAX_BYTES)
    bundle_raw = bounded_file(bundle, MAX_BUNDLE_BYTES)
    executable = shutil.which("gh")
    require(executable, "archive-verifier-unavailable")
    result = subprocess.run(  # noqa: S603, RUF100 -- fixed attestation verifier; no shell.
        [
            executable,
            "attestation",
            "verify",
            str(snapshot),
            "--bundle",
            str(bundle),
            "--repo",
            repository,
            "--cert-identity",
            f"https://github.com/{repository}/{WORKFLOW}@refs/heads/main",
            "--source-ref",
            "refs/heads/main",
            "--source-digest",
            release,
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    require(result.returncode == 0, "archive-attestation-verification-failed")
    require(
        bounded_file(snapshot, MAX_BYTES) == raw and bounded_file(bundle, MAX_BUNDLE_BYTES) == bundle_raw,
        "archive-file-drift",
    )
    value = decode(raw)
    require(
        type(value) is dict
        and type(value.get("binding")) is dict
        and value["binding"].get("repository") == repository
        and value["binding"].get("repository_id") == repository_id
        and value["binding"].get("release") == release,
        "archive-binding",
    )
    return value


def download_pair(published, repository, directory):
    require(
        type(published.get("assets")) is list and all(type(asset) is dict for asset in published["assets"]),
        "archive-release-assets-missing",
    )
    executable = shutil.which("gh")
    require(executable, "archive-downloader-unavailable")
    selected = []
    for name, maximum in ((SNAPSHOT, MAX_BYTES), (BUNDLE, MAX_BUNDLE_BYTES)):
        matches = [asset for asset in published["assets"] if asset.get("name") == name]
        require(len(matches) == 1, "archive-release-asset-missing-or-ambiguous")
        asset = matches[0]
        require(
            type(asset.get("id")) is int
            and asset["id"] > 0
            and asset.get("state") == "uploaded"
            and type(asset.get("size")) is int
            and 0 < asset["size"] <= maximum,
            "archive-release-asset-bound",
        )
        selected.append((name, maximum, asset))
    require(len({asset["id"] for _name, _maximum, asset in selected}) == 2, "archive-release-asset-identity")
    for name, maximum, asset in selected:
        with subprocess.Popen(  # noqa: S603, RUF100 -- exact repository asset ID, bounded read, no shell.
            [
                executable,
                "api",
                "--allow-escape-sequences",
                "--header",
                "Accept: application/octet-stream",
                f"repos/{repository}/releases/assets/{asset['id']}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ) as process:
            deadline = time.monotonic() + 60
            raw = bytearray()
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        require(remaining > 0 and selector.select(remaining), "archive-download-timeout")
                        chunk = os.read(process.stdout.fileno(), min(65536, maximum + 1 - len(raw)))
                        if not chunk:
                            break
                        raw.extend(chunk)
                        require(len(raw) <= maximum, "archive-release-download-bound")
                status = process.wait(timeout=max(0.1, deadline - time.monotonic()))
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        require(status == 0 and len(raw) == asset["size"] and len(raw) <= maximum, "archive-release-download")
        (directory / name).write_bytes(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    try:
        verify_files(args.snapshot, args.bundle, args.repository, args.repository_id, args.release)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
