"""Validate fenced YAML, shell, and Ansible examples in changed Markdown."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError as error:
    raise SystemExit(
        "PyYAML is required for fail-closed embedded YAML validation: python3 -m pip install PyYAML==6.0.3"
    ) from error

SCRIPT = Path(__file__).resolve()
DISTRIBUTED_ROOT = SCRIPT.parents[1]
SHARED_ROOT = SCRIPT.parents[2]
ROOT = (
    SHARED_ROOT
    if DISTRIBUTED_ROOT.name == "default"
    and ((SHARED_ROOT / ".git").exists() or (SHARED_ROOT / "release-model" / "repositories.yml").is_file())
    else DISTRIBUTED_ROOT
)
FENCE_OPEN = re.compile(
    r"^[ \t]*(?P<delimiter>`{3,}|~{3,})[ \t]*(?P<language>yaml|yml|bash|sh|shell|ansible)\b[^\r\n]*$",
    re.IGNORECASE,
)
VALIDATOR_TIMEOUT_SECONDS = 60


def validator_candidate(
    temporary: Path,
    kind: str,
    markdown_path: str,
    fence_index: int,
    suffix: str,
) -> Path:
    path_digest = hashlib.sha256(markdown_path.encode("utf-8", errors="surrogateescape")).hexdigest()[:12]
    return temporary / f"{kind}-{path_digest}-{fence_index}.{suffix}"


def fenced_blocks(source: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    active: tuple[str, str, int] | None = None
    content: list[str] = []
    for line in source.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        if active is None:
            match = FENCE_OPEN.fullmatch(text)
            if match:
                active = match["language"].lower(), match["delimiter"][0], len(match["delimiter"])
                content = []
        elif re.fullmatch(rf"[ \t]*{re.escape(active[1])}{{{active[2]},}}[ \t]*", text):
            blocks.append((active[0], "".join(content)))
            active = None
        else:
            content.append(line)
    if active is not None:
        raise ValueError("unterminated embedded-code fence")
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args()
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as temporary:
        temp = Path(temporary)
        for name in args.paths:
            relative_path = Path(name)
            if (
                not name
                or relative_path.is_absolute()
                or ".." in relative_path.parts
                or relative_path.as_posix() != name
            ):
                failures.append(f"{name}: Markdown path must be normalized and repository-relative")
                continue
            path = ROOT / relative_path
            if path.suffix.lower() != ".md":
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(ROOT.resolve(strict=True))
                if path.is_symlink() or not path.is_file():
                    raise OSError("path is not a non-symlink regular file")
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, ValueError) as error:
                failures.append(f"{name}: unsafe or unreadable Markdown path: {error}")
                continue
            try:
                blocks = fenced_blocks(source)
            except ValueError as error:
                failures.append(f"{name}: {error}")
                continue
            for index, (language, content) in enumerate(blocks, 1):
                label = f"{name}:fence-{index}"
                if language in {"yaml", "yml", "ansible"}:
                    try:
                        yaml.safe_load(content)
                    except yaml.YAMLError as error:
                        failures.append(f"{label}: invalid YAML: {error}")
                        continue
                    if language == "ansible":
                        ansible_lint = shutil.which("ansible-lint")
                        if not ansible_lint:
                            failures.append(f"{label}: ansible-lint is required for Ansible fences")
                            continue
                        candidate = validator_candidate(
                            temp,
                            "ansible",
                            name,
                            index,
                            "yml",
                        )
                        candidate.write_text(content, encoding="utf-8")
                        try:
                            result = subprocess.run(  # noqa: S603 -- resolved executable and test-owned file.
                                [ansible_lint, str(candidate)],
                                text=True,
                                capture_output=True,
                                timeout=VALIDATOR_TIMEOUT_SECONDS,
                                check=False,
                            )
                        except subprocess.TimeoutExpired:
                            failures.append(
                                f"{label}: ansible-lint timed out after {VALIDATOR_TIMEOUT_SECONDS} seconds"
                            )
                            continue
                        if result.returncode:
                            details = "\n".join(
                                output.strip() for output in (result.stdout, result.stderr) if output.strip()
                            )
                            failures.append(f"{label}: ansible-lint failed\n{details}".rstrip())
                else:
                    shellcheck = shutil.which("shellcheck")
                    if not shellcheck:
                        failures.append(f"{label}: ShellCheck is required for shell fences")
                        continue
                    candidate = validator_candidate(
                        temp,
                        "shell",
                        name,
                        index,
                        "sh",
                    )
                    interpreter = "bash" if language == "bash" else "sh"
                    candidate.write_text(
                        f"#!/usr/bin/env {interpreter}\n" + content,
                        encoding="utf-8",
                    )
                    try:
                        result = subprocess.run(  # noqa: S603 -- resolved executable and test-owned file.
                            [shellcheck, str(candidate)],
                            text=True,
                            capture_output=True,
                            timeout=VALIDATOR_TIMEOUT_SECONDS,
                            check=False,
                        )
                    except subprocess.TimeoutExpired:
                        failures.append(f"{label}: ShellCheck timed out after {VALIDATOR_TIMEOUT_SECONDS} seconds")
                        continue
                    if result.returncode:
                        details = "\n".join(
                            output.strip() for output in (result.stdout, result.stderr) if output.strip()
                        )
                        failures.append(f"{label}: ShellCheck failed\n{details}".rstrip())
    for failure in failures:
        print(f"ERROR: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
