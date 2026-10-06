"""Fail-closed per-review admission at the Responses API request boundary.

The protected runtime must own this object and its upstream transport. The
reviewer's prompt or reported cost is never spending authority. Prices and model
capacity come from a separately verified, manifest-bound provider profile. This
module does not select a model, accept a profile, authenticate a reviewer, or send
requests. A controller reservation must already exist before constructing it.
"""
# Exact JSON schema types deliberately reject bool as int and subclasses.
# pylint: disable=unidiomatic-typecheck

from __future__ import annotations

import json
from typing import Any

from bounded_review import ReviewError, canonical, integer, keys, require, sha

PROFILE_KEYS = {
    "version",
    "model",
    "context_tokens",
    "max_input_tokens",
    "max_output_tokens",
    "input_microusd_per_million_tokens",
    "output_microusd_per_million_tokens",
    "capacity_evidence_sha256",
    "pricing_evidence_sha256",
}

# Reject new or stateful API features until their billing and input semantics
# have been reviewed. In particular, a stored prompt can inject hosted tools.
REQUEST_KEYS = {
    "model",
    "input",
    "instructions",
    "tools",
    "tool_choice",
    "parallel_tool_calls",
    "max_output_tokens",
    "reasoning",
    "text",
    "temperature",
    "top_p",
    "stream",
    "stream_options",
    "store",
    "background",
    "truncation",
    "service_tier",
    "previous_response_id",
    "conversation",
    "include",
    "metadata",
    "prompt_cache_key",
    "safety_identifier",
    "client_metadata",
}


def validate_profile(profile: dict[str, Any]) -> None:
    keys(profile, PROFILE_KEYS, "provider-profile-shape")
    require(profile["version"] == "responses-budget/v2", "provider-profile-version")
    require(type(profile["model"]) is str and 0 < len(profile["model"]) <= 128, "provider-model")
    integer(profile["context_tokens"], 1, 10_000_000, "provider-context")
    integer(profile["max_input_tokens"], 1, profile["context_tokens"], "provider-input-bound")
    integer(profile["max_output_tokens"], 1, profile["context_tokens"], "provider-output-bound")
    for name in ("input_microusd_per_million_tokens", "output_microusd_per_million_tokens"):
        integer(profile[name], 1, 1_000_000_000, "provider-price")
    for name in ("capacity_evidence_sha256", "pricing_evidence_sha256"):
        value = profile[name]
        require(
            type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value), "provider-evidence"
        )


def cost(profile: dict[str, Any], input_tokens: int, output_tokens: int) -> int:
    # Charge all input at the uncached rate. Round up once; never use floats or
    # assume discounts, cached-input accounting, or free reasoning tokens.
    numerator = (
        input_tokens * profile["input_microusd_per_million_tokens"]
        + output_tokens * profile["output_microusd_per_million_tokens"]
    )
    return (numerator + 999_999) // 1_000_000


class ResponseBudget:
    """One serial review, terminal on any ambiguous or failed upstream outcome.

    A validated request reserves the full model context plus its output cap,
    rather than estimating token counts from text length. Separate authenticated
    input-token admission must succeed before the model request. An authenticated
    successful upstream response may settle that reservation to actual usage.
    Loss, failure, incomplete output, unknown usage or cancellation retains the
    entire reservation and permanently prevents another request in this review.
    """

    def __init__(
        self,
        profile: dict[str, Any],
        *,
        max_cost_microusd: int,
        start_ms: int,
        timeout_ms: int,
        max_requests: int = 16,
        request_byte_limit: int = 2_000_000,
    ):
        validate_profile(profile)
        integer(max_cost_microusd, 1, 1_000_000, "provider-cost-budget")
        integer(start_ms, 0, 2**63 - 1, "provider-clock")
        integer(timeout_ms, 1, 100_000, "provider-time-budget")
        integer(max_requests, 1, 16, "provider-request-budget")
        self.profile = json.loads(canonical(profile))
        self.limit = max_cost_microusd
        self.deadline = start_ms + timeout_ms
        self.last_ms = start_ms
        integer(request_byte_limit, 1, 2**63 - 1, "provider-resource-bound")
        self.request_byte_limit = request_byte_limit
        self.max_requests = max_requests
        self.requests: set[str] = set()
        self.responses: set[str] = set()
        self.charged = 0
        self.active: tuple[str, int, int] | None = None
        self.failed = False
        self.admitted: str | None = None

    def _clock(self, now_ms: int) -> None:
        integer(now_ms, self.last_ms, 2**63 - 1, "provider-clock")
        require(now_ms < self.deadline, "provider-timeout")
        self.last_ms = now_ms

    @staticmethod
    def _tools(tools: Any, depth: int = 0) -> None:
        require(type(tools) is list and len(tools) <= 64 and depth <= 2, "provider-tools")
        for tool in tools:
            require(type(tool) is dict, "provider-tools")
            kind = tool.get("type")
            # Local function/custom tools generate ordinary model tokens. Hosted
            # tools may incur extra fees or access unbound state and are rejected.
            if kind == "namespace":
                ResponseBudget._tools(tool.get("tools"), depth + 1)
            else:
                require(kind in ("function", "custom"), "provider-hosted-tool")

    @staticmethod
    def _text_input(value: Any) -> None:
        if type(value) is str:
            return
        require(type(value) is list and len(value) <= 1024, "provider-input")
        for item in value:
            require(type(item) is dict, "provider-input")
            kind = item.get("type", "message")
            if kind == "message":
                content = item.get("content")
                if type(content) is str:
                    continue
                require(type(content) is list and len(content) <= 1024, "provider-input")
                for part in content:
                    require(
                        type(part) is dict
                        and part.get("type") in ("input_text", "output_text")
                        and type(part.get("text")) is str,
                        "provider-nontext-input",
                    )
            else:
                require(
                    kind
                    in (
                        "reasoning",
                        "function_call",
                        "function_call_output",
                        "custom_tool_call",
                        "custom_tool_call_output",
                    ),
                    "provider-unbound-input",
                )
                if kind.endswith("_output"):
                    require(type(item.get("output")) is str, "provider-nontext-input")

    def reserve(self, request: dict[str, Any], *, now_ms: int) -> tuple[str, dict[str, Any]]:
        """Validate and return the exact bounded request to forward once upstream."""
        try:
            require(not self.failed and self.active is None, "provider-active-or-terminal")
            self._clock(now_ms)
            require(
                type(request) is dict and len(canonical(request)) <= self.request_byte_limit, "provider-request-size"
            )
            require(set(request) <= REQUEST_KEYS, "provider-request-feature")
            require(request.get("model") == self.profile["model"], "provider-model-drift")
            require(request.get("service_tier", "default") in (None, "default"), "provider-service-tier")
            require(request.get("background", False) is False, "provider-background")
            require(request.get("store", False) is False, "provider-storage")
            require(request.get("truncation", "disabled") == "disabled", "provider-truncation")
            require(
                request.get("previous_response_id") is None and request.get("conversation") is None,
                "provider-unbound-state",
            )
            require(type(request.get("stream", False)) is bool, "provider-stream")
            require(
                request.get("instructions") is None or type(request["instructions"]) is str, "provider-instructions"
            )
            self._tools(request.get("tools", []))
            self._text_input(request.get("input"))
            output_cap = request.get("max_output_tokens", self.profile["max_output_tokens"])
            integer(output_cap, 1, self.profile["max_output_tokens"], "provider-output-bound")
            bounded = json.loads(canonical(request))
            # Codex 0.160.0 emits a string map even for the ordinary HTTP
            # Responses provider. Strip this client telemetry before forwarding;
            # it grants no routing, guardian, access-program or billing authority.
            if "client_metadata" in bounded:
                metadata = bounded.pop("client_metadata")
                require(
                    type(metadata) is dict
                    and len(metadata) <= 64
                    and all(type(key) is str and type(value) is str for key, value in metadata.items())
                    and len(canonical(metadata)) <= 16_384,
                    "provider-client-metadata",
                )
            bounded.update(
                max_output_tokens=output_cap,
                store=False,
                background=False,
                truncation="disabled",
                service_tier="default",
            )
            digest = sha(canonical(bounded))
            require(digest not in self.requests, "provider-request-replay")
            require(len(self.requests) < self.max_requests, "provider-request-budget")
            reserved = cost(self.profile, self.profile["context_tokens"], output_cap)
            require(self.charged + reserved <= self.limit, "provider-cost-admission")
            self.charged += reserved
            self.requests.add(digest)
            self.active = (digest, reserved, output_cap)
            return digest, bounded
        except (ReviewError, TypeError, ValueError, OverflowError, RecursionError):
            self.failed = True
            raise

    def admit_tokens(self, digest: str, request: dict[str, Any], count: dict[str, Any], *, now_ms: int) -> None:
        """Bind authenticated input count to the exact reserved request before send.

        Only the protected transport may supply the provider count. This is not
        reviewer-provided authority or a byte-based token estimate.
        """
        try:
            require(
                not self.failed and self.active is not None and self.admitted is None, "provider-active-or-terminal"
            )
            self._clock(now_ms)
            expected, _unused_value_1, output_cap = self.active
            require(digest == expected == sha(canonical(request)), "provider-substituted-count")
            keys(count, {"object", "input_tokens"}, "provider-token-count-shape")
            require(count["object"] == "response.input_tokens", "provider-token-count-object")
            integer(count["input_tokens"], 0, self.profile["max_input_tokens"], "provider-input-admission")
            require(count["input_tokens"] + output_cap <= self.profile["context_tokens"], "provider-context-admission")
            self.admitted = digest
        except (ReviewError, TypeError, ValueError, OverflowError, RecursionError):
            self.failed = True
            raise

    def complete(self, digest: str, response: dict[str, Any], *, now_ms: int) -> int:
        """Settle only a complete, authenticated upstream response with usage.

        The transport must call this before exposing terminal success to Codex.
        It must use the upstream response body, never a reviewer's cost report.
        """
        try:
            require(not self.failed and self.active is not None, "provider-active-or-terminal")
            self._clock(now_ms)
            expected, reserved, output_cap = self.active
            require(self.admitted == expected, "provider-token-count-required")
            require(digest == expected, "provider-substituted-response")
            require(type(response) is dict and response.get("status") == "completed", "provider-incomplete")
            require(response.get("error") is None and response.get("incomplete_details") is None, "provider-incomplete")
            require(response.get("model") == self.profile["model"], "provider-model-drift")
            require(response.get("service_tier", "default") == "default", "provider-service-tier")
            identity = response.get("id")
            require(
                type(identity) is str and 0 < len(identity) <= 256 and identity not in self.responses,
                "provider-response-replay",
            )
            usage = response.get("usage")
            require(type(usage) is dict, "provider-missing-usage")
            input_tokens, output_tokens = (usage.get("input_tokens"), usage.get("output_tokens"))
            integer(input_tokens, 0, self.profile["max_input_tokens"], "provider-input-overrun")
            require(input_tokens + output_cap <= self.profile["context_tokens"], "provider-context-overrun")
            integer(output_tokens, 0, output_cap, "provider-output-overrun")
            integer(usage.get("total_tokens"), 0, self.profile["context_tokens"] + output_cap, "provider-usage")
            require(usage["total_tokens"] == input_tokens + output_tokens, "provider-usage")
            actual = cost(self.profile, input_tokens, output_tokens)
            require(actual <= reserved, "provider-cost-overrun")
            self.charged -= reserved - actual
            self.responses.add(identity)
            self.active = None
            self.admitted = None
            return actual
        except (ReviewError, TypeError, ValueError, OverflowError, RecursionError):
            self.failed = True
            raise

    def abandon(self) -> None:
        """Unknown outcome: retain the full reservation and forbid all retries."""
        self.failed = True
