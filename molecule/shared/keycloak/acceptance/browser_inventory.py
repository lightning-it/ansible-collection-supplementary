"""Inventory the exact Playwright Chromium runtime used by Acceptance tests."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
from pathlib import Path

SAFE_CELL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}")
SAFE_PROFILE = re.compile(r"[a-z][a-z0-9-]{0,62}")
FULL_SHA = re.compile(r"[0-9a-f]{40}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(*argv: str) -> str:
    result = subprocess.run(  # noqa: S603 -- argv is a fixed executable or resolved browser path.
        argv,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout.strip()


def _operating_system(target: str) -> dict[str, str]:
    release = platform.freedesktop_os_release()
    os_id = release.get("ID", "").lower()
    version_id = release.get("VERSION_ID", "")
    if target == "ubuntu-24.04":
        valid = os_id == "ubuntu" and version_id == "24.04"
    elif target in {"rhel-9", "rhel-10"}:
        major = target.removeprefix("rhel-")
        valid = os_id == "rhel" and re.fullmatch(rf"{major}(?:\.[0-9]+)*", version_id) is not None
    else:
        valid = False
    if not valid:
        raise RuntimeError(f"target {target!r} differs from operating system {os_id!r} {version_id!r}")
    return {"id": os_id, "version_id": version_id, "distro": target}


def _os_packages(os_id: str) -> list[dict[str, str]]:
    if os_id == "ubuntu":
        output = _run(
            "dpkg-query",
            "-W",
            "-f=${db:Status-Status}\\t${Package}\\t${Version}\\t${Architecture}\\t"
            "${source:Package}\\t${source:Version}\\n",
        )
    elif os_id == "rhel":
        output = _run(
            "rpm",
            "-qa",
            "--qf",
            "%{NAME}\\t%{VERSION}-%{RELEASE}\\t%{ARCH}\\t%{SOURCERPM}\\t%{EPOCHNUM}\\n",
        )
    else:  # pragma: no cover - _operating_system rejects this first.
        raise RuntimeError(f"unsupported target operating system: {os_id}")
    packages: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in output.splitlines():
        fields = line.split("\t")
        if os_id == "ubuntu":
            if len(fields) != 6 or not fields[0]:
                raise RuntimeError("dpkg-query returned a malformed package-database record")
            status = fields.pop(0)
            if status != "installed":
                continue
            if not all(fields):
                raise RuntimeError("dpkg-query returned a malformed installed-package record")
        elif len(fields) == 5 and all(fields):
            epoch = fields.pop()
            source_rpm = fields.pop()
            if fields[2] == "(none)" or source_rpm == "(none)":
                continue
            source_match = re.fullmatch(r"(.+)-([^-]+-[^-]+)\.src\.rpm", source_rpm)
            if source_match is None:
                raise RuntimeError("rpm returned an installed package without an exact source-RPM identity")
            fields.extend(source_match.groups())
            if re.fullmatch(r"[0-9]+", epoch) is None:
                raise RuntimeError("rpm returned an installed package with a malformed epoch")
            if epoch != "0":
                fields[1] = f"{epoch}:{fields[1]}"
        if len(fields) != 5 or not all(fields):
            raise RuntimeError("package manager returned a malformed installed-package record")
        identity = (fields[0], fields[1], fields[2])
        if identity in seen:
            raise RuntimeError(f"dpkg-query returned a duplicate package record: {fields[0]}")
        seen.add(identity)
        packages.append(
            {
                "name": fields[0],
                "version": fields[1],
                "architecture": fields[2],
                "source_name": fields[3],
                "source_version": fields[4],
            }
        )
    if not packages:
        raise RuntimeError("the target operating-system package inventory is empty")
    return sorted(packages, key=lambda item: (item["name"], item["architecture"], item["version"]))


def _browser_version(version_output: str, *, channel: str) -> str:
    labels = {"chrome": "Google Chrome"}
    if channel not in labels:
        raise ValueError("unsupported Playwright browser channel")
    match = re.fullmatch(rf"{re.escape(labels[channel])}\s+([0-9]+(?:\.[0-9]+){{1,3}})", version_output)
    if match is None:
        raise RuntimeError(f"unexpected Playwright Chrome version output: {version_output!r}")
    return match.group(1)


def inventory(
    *,
    profile: str,
    scenario: str,
    target: str,
    source_commit: str,
    browser_channel: str,
    executable_path: str,
) -> dict[str, object]:
    if SAFE_PROFILE.fullmatch(profile) is None:
        raise ValueError("unsafe profile identity")
    if SAFE_CELL.fullmatch(scenario) is None or SAFE_CELL.fullmatch(target) is None:
        raise ValueError("unsafe scenario or target identity")
    if FULL_SHA.fullmatch(source_commit) is None:
        raise ValueError("source commit must be a lowercase full SHA")

    if browser_channel != "chrome":
        raise ValueError("unsupported Playwright browser channel")
    executable = Path(executable_path).resolve(strict=True)
    if executable != Path("/opt/google/chrome/chrome"):
        raise RuntimeError("Playwright Chrome executable resolved to an unexpected path")
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("Playwright Chrome executable is absent or not executable")
    version_output = _run(str(executable), "--version")
    browser_version = _browser_version(version_output, channel=browser_channel)

    operating_system = _operating_system(target)
    return {
        "schema_version": 1,
        "source": "playwright-target-runtime",
        "profile": profile,
        "scenario": scenario,
        "target": target,
        "source_commit": source_commit,
        "playwright_version": importlib.metadata.version("playwright"),
        "chromium": {
            "name": "chromium",
            "channel": browser_channel,
            "version": browser_version,
            "executable": executable.as_posix(),
            "sha256": _sha256(executable),
        },
        "operating_system": operating_system,
        "os_packages": _os_packages(operating_system["id"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--browser-channel", required=True)
    parser.add_argument("--executable", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            inventory(
                profile=args.profile,
                scenario=args.scenario,
                target=args.target,
                source_commit=args.source_commit,
                browser_channel=args.browser_channel,
                executable_path=args.executable,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
