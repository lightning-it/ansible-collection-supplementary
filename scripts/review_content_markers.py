"""Pure, fail-closed Copilot review-content classification for REP-120.

The caller must separately authenticate and collect the exact review and all
its inline comments. This module does not issue a review receipt.
"""

from __future__ import annotations

FAILURE_MARKERS = (
    "unabletoreviewthispullrequest",
    "wasnotabletoreviewthispullrequest",
    "nofilestoreview",
    "unabletoreviewanyfiles",
    "notabletoreviewanyfiles",
    "wasnotabletoreviewanyfiles",
    "quotaexhausted",
    "quotaexceeded",
    "premiumrequestquota",
    "premiumrequestsquota",
    "suppressedcomment",
    "encounteredanerror",
)


class ReviewContentError(ValueError):
    """The selected review has malformed or unsuccessful content."""


def normalize(value: str) -> str:
    """Match the protected gate's ASCII fold, contraction and Unicode whitespace rules."""
    ascii_lower = "".join(chr(ord(char) + 32) if "A" <= char <= "Z" else char for char in value)
    expanded = ascii_lower.replace("n't", " not").replace("n’t", " not")
    return "".join(char for char in expanded if not char.isspace())


def require_usable_review_content(review_body: object, inline_bodies: object) -> None:
    """Reject malformed, empty, or known unsuccessful Copilot review content."""
    if review_body is not None and type(review_body) is not str:
        raise ReviewContentError("review-body-shape")
    if type(inline_bodies) is not list or any(type(body) is not str for body in inline_bodies):
        raise ReviewContentError("inline-body-shape")
    parts = [normalize(review_body or ""), *(normalize(body) for body in inline_bodies)]
    if not any(parts):
        raise ReviewContentError("review-content-empty")
    if any(marker in part for part in parts for marker in FAILURE_MARKERS):
        raise ReviewContentError("review-content-failed")
