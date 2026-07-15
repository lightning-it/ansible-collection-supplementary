#!/usr/bin/env python3
"""Redact credential-shaped values from controller-side text evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any

SENSITIVE_ENV_NAME = re.compile(
    r"(?:PASSWORD|PASSWD|PASSPHRASE|SECRET|TOKEN|API_?KEY|PRIVATE_?KEY|"
    r"CREDENTIAL|AUTHORIZATION|COOKIE|SESSION)",
    re.IGNORECASE,
)
PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?"
    r"-----END [^-\r\n]*PRIVATE KEY-----",
    re.DOTALL,
)
KEY_VALUE_SECRET = re.compile(
    r"(?i)(\b(?:password|passwd|passphrase|secret|token|api[_-]?key|"
    r"private[_-]?key|credential|authorization|cookie|session(?:_secret)?|"
    r"client[_-]?secret|bind[_-]?credential)\b\s*[=:]\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;]+)",
)
PROSE_SECRET = re.compile(
    r"(?i)(\b(?:password|passwd|passphrase|secret|token|credential)\b"
    r"\s+(?:is|was)\s+)[^\s,;]+",
)
BEARER_TOKEN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
JWT = re.compile(
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
    r"[A-Za-z0-9_-]{8,}\b",
)
URL_CREDENTIAL = re.compile(
    r"(?i)(\b[a-z][a-z0-9+.-]*://[^\s/:@]+:)[^\s/@]+(@)",
)
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def _is_sensitive_name(value: object) -> bool:
    return isinstance(value, str) and bool(SENSITIVE_ENV_NAME.search(value))


def _sanitize_json(value: Any, explicit_names: list[str]) -> Any:
    """Redact secrets represented as JSON keys or name/value records."""

    if isinstance(value, list):
        return [_sanitize_json(item, explicit_names) for item in value]
    if not isinstance(value, dict):
        return value

    sensitive_value_record = any(
        key.lower() in {"name", "key", "field"} and _is_sensitive_name(item) for key, item in value.items()
    )
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if _is_sensitive_name(key) or (sensitive_value_record and key.lower() in {"value", "content", "data"}):
            sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = _sanitize_json(item, explicit_names)
    return sanitized


def _sanitize_json_document(text: str, explicit_names: list[str]) -> str:
    """Sanitize a complete JSON document while preserving its JSON validity."""

    trailing_newline = text.endswith("\n")
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return text
    rendered = json.dumps(
        _sanitize_json(document, explicit_names),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return rendered + ("\n" if trailing_newline else "")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--secret-env",
        action="append",
        default=[],
        metavar="NAME",
        help="also redact the exact value of this environment variable",
    )
    return parser


def _secret_values(explicit_names: list[str]) -> list[str]:
    names = set(explicit_names)
    names.update(name for name in os.environ if SENSITIVE_ENV_NAME.search(name))
    values = {os.environ[name] for name in names if name in os.environ and os.environ[name]}
    return sorted(values, key=len, reverse=True)


def sanitize(text: str, explicit_names: list[str]) -> str:
    """Return text with exact and credential-shaped secrets removed."""

    sanitized = _sanitize_json_document(text, explicit_names)
    sanitized = ANSI_ESCAPE.sub("", sanitized)
    for value in _secret_values(explicit_names):
        sanitized = sanitized.replace(value, "[REDACTED]")

    sanitized = PRIVATE_KEY.sub("[REDACTED PRIVATE KEY]", sanitized)
    sanitized = URL_CREDENTIAL.sub(r"\1[REDACTED]\2", sanitized)
    sanitized = BEARER_TOKEN.sub(r"\1[REDACTED]", sanitized)
    sanitized = JWT.sub("[REDACTED JWT]", sanitized)
    sanitized = KEY_VALUE_SECRET.sub(r"\1[REDACTED]", sanitized)
    return PROSE_SECRET.sub(r"\1[REDACTED]", sanitized)


def main() -> int:
    args = _parser().parse_args()
    sys.stdout.write(sanitize(sys.stdin.read(), args.secret_env))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
