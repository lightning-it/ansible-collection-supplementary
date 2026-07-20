"""Reduce a Playwright action trace to secret-free failure diagnostics."""

from __future__ import annotations

import json
import re
import stat
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

MAX_MEMBERS = 64
MAX_MEMBER_BYTES = 16 * 1024 * 1024
SENSITIVE_KEY = re.compile(
    r"(?i)(authorization|cookie|credential|header|password|post.?data|request.?body|"
    r"response.?body|secret|storage|token|value|text)"
)
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
AUTHORIZATION = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
COOKIE_ASSIGNMENT = re.compile(r"(?i)\b(?:cookie|set-cookie)\s*[:=][^\r\n,}]+")
HTTP_URL = re.compile(r"https?://[^\s\"'<>]+")


class TraceSanitizationError(RuntimeError):
    """Raised when a raw trace cannot be made safe for evidence."""


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "[REDACTED-URL]"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _sanitize_string(value: str, secrets: tuple[str, ...]) -> str:
    sanitized = value
    for secret in secrets:
        sanitized = sanitized.replace(secret, "[REDACTED]")
    sanitized = JWT.sub("[REDACTED-JWT]", sanitized)
    sanitized = AUTHORIZATION.sub("[REDACTED-AUTHORIZATION]", sanitized)
    sanitized = COOKIE_ASSIGNMENT.sub("[REDACTED-COOKIE]", sanitized)
    return HTTP_URL.sub(lambda match: _safe_url(match.group(0)), sanitized)


def _sanitize_value(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_value(item, secrets)
            for key, item in value.items()
            if SENSITIVE_KEY.search(str(key)) is None
        }
    if isinstance(value, list):
        return [_sanitize_value(item, secrets) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value, secrets)
    return value


def _sanitize_json_lines(raw: bytes, secrets: tuple[str, ...], member: str) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TraceSanitizationError(f"trace metadata is not UTF-8: {member}") from error
    rendered: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise TraceSanitizationError(f"invalid trace JSON at {member}:{line_number}") from error
        rendered.append(json.dumps(_sanitize_value(payload, secrets), separators=(",", ":"), sort_keys=True))
    if not rendered:
        raise TraceSanitizationError(f"trace metadata is empty: {member}")
    return ("\n".join(rendered) + "\n").encode("utf-8")


def _allowed_member(path: PurePosixPath) -> bool:
    return path.name.endswith(".trace") or path.name.endswith(".stacks")


def sanitize_trace(source: Path, destination: Path, *, secrets: Iterable[str]) -> None:
    """Keep sanitized action/stack metadata and discard all network/resources."""

    secret_values = tuple(sorted({value for value in secrets if len(value) >= 4}, key=len, reverse=True))
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    retained = 0
    try:
        with (
            zipfile.ZipFile(source) as archive,
            zipfile.ZipFile(
                temporary,
                mode="w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as output,
        ):
            members = archive.infolist()
            if not members or len(members) > MAX_MEMBERS:
                raise TraceSanitizationError("raw trace has an invalid member count")
            for member in members:
                path = PurePosixPath(member.filename)
                mode = member.external_attr >> 16
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or member.is_dir()
                    or stat.S_ISLNK(mode)
                    or member.file_size > MAX_MEMBER_BYTES
                    or not _allowed_member(path)
                ):
                    continue
                sanitized = _sanitize_json_lines(archive.read(member), secret_values, path.as_posix())
                for secret in secret_values:
                    if secret.encode("utf-8") in sanitized:
                        raise TraceSanitizationError(f"known secret remains in sanitized trace member: {path}")
                if JWT.search(sanitized.decode("utf-8")) or AUTHORIZATION.search(sanitized.decode("utf-8")):
                    raise TraceSanitizationError(f"token material remains in sanitized trace member: {path}")
                target = zipfile.ZipInfo(path.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                target.compress_type = zipfile.ZIP_DEFLATED
                target.external_attr = 0o600 << 16
                output.writestr(target, sanitized)
                retained += 1
        if retained == 0:
            raise TraceSanitizationError("raw trace contained no action metadata")
        temporary.chmod(0o600)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
