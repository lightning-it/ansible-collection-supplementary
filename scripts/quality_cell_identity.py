"""Create bounded, collision-resistant identities for isolated quality cells."""

from __future__ import annotations

import argparse
import hashlib
import re


def bounded_identity(value: str, *, maximum: int, owner: bool = False) -> str:
    """Preserve a readable prefix and hash the complete, untruncated identity."""
    if maximum < 33:
        raise ValueError("maximum identity length is too small")
    allowed = r"[^A-Za-z0-9._/-]" if owner else r"[^A-Za-z0-9.-]"
    sanitized = re.sub(allowed, "-", value)
    if not sanitized or not sanitized[0].isalnum():
        raise ValueError("identity must begin with an alphanumeric character")
    digest = hashlib.sha256(
        (("owner" if owner else "instance") + "\0" + value).encode()
    ).hexdigest()[:24]
    prefix = sanitized[: maximum - len(digest) - 1].rstrip("-._/")
    if not prefix:
        raise ValueError("identity has no safe readable prefix")
    result = f"{prefix}-{digest}"
    if len(result) > maximum:
        raise AssertionError("bounded identity exceeds its declared maximum")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    print(bounded_identity(args.instance, maximum=63))
    print(bounded_identity(args.owner, maximum=255, owner=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
