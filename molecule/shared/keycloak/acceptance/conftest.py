"""Fail-closed pytest fixtures and secret-safe Playwright diagnostics."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

import allure
import pytest
from playwright.sync_api import Browser, BrowserContext, Page
from trace_sanitizer import sanitize_trace

EVIDENCE_ROLES = frozenset({"keycloak_cac", "keycloak_deploy"})
SAFE_ARTIFACT_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass(frozen=True)
class Settings:
    issuer: str
    client_id: str
    client_secret: str
    app_url: str
    admin_username: str
    admin_password: str
    viewer_username: str
    viewer_password: str
    unauthorized_username: str
    unauthorized_password: str
    invalid_username: str
    invalid_password: str
    ca_bundle: str | None


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        pytest.fail(f"Required acceptance setting {name} is missing", pytrace=False)
    return value


def _safe_location(url: str) -> str:
    """Retain only a bounded origin and path; never retain query credentials."""

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return "browser-internal"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:512]


def _artifact_name(node_name: str) -> str:
    return SAFE_ARTIFACT_NAME.sub("-", node_name).strip(".-")[:120] or "acceptance-failure"


def _diagnostic_html(test_name: str, location: str, events: list[dict[str, object]]) -> str:
    summary = json.dumps(events[-100:], indent=2, sort_keys=True)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Acceptance failure diagnostic</title></head>"
        "<body><h1>Acceptance failure diagnostic</h1>"
        f"<p id='test-name'>{escape(test_name)}</p>"
        f"<p id='failure-location'>{escape(location)}</p>"
        f"<pre id='browser-events'>{escape(summary)}</pre>"
        "</body></html>"
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "evidence_role(role): assign one test to one registry role for JUnit and Allure evidence",
    )


@pytest.fixture(autouse=True)
def record_evidence_role(
    request: pytest.FixtureRequest,
    record_property: Callable[[str, object], None],
) -> None:
    """Require and record exactly one supported role identity per test case."""

    markers = list(request.node.iter_markers("evidence_role"))
    if len(markers) != 1 or len(markers[0].args) != 1:
        pytest.fail(
            "Every acceptance test requires exactly one @pytest.mark.evidence_role(role)",
            pytrace=False,
        )
    role = str(markers[0].args[0])
    if role not in EVIDENCE_ROLES:
        pytest.fail(f"Unsupported evidence role: {role}", pytrace=False)
    record_property("role", role)
    allure.dynamic.label("role", role)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        issuer=_required("KEYCLOAK_TEST_ISSUER").rstrip("/"),
        client_id=_required("KEYCLOAK_TEST_CLIENT_ID"),
        client_secret=_required("KEYCLOAK_TEST_CLIENT_SECRET"),
        app_url=_required("KEYCLOAK_TEST_APP_URL").rstrip("/"),
        admin_username=_required("KEYCLOAK_TEST_ADMIN_USERNAME"),
        admin_password=_required("KEYCLOAK_TEST_ADMIN_PASSWORD"),
        viewer_username=_required("KEYCLOAK_TEST_VIEWER_USERNAME"),
        viewer_password=_required("KEYCLOAK_TEST_VIEWER_PASSWORD"),
        unauthorized_username=_required("KEYCLOAK_TEST_UNAUTHORIZED_USERNAME"),
        unauthorized_password=_required("KEYCLOAK_TEST_UNAUTHORIZED_PASSWORD"),
        invalid_username=_required("KEYCLOAK_TEST_INVALID_USERNAME"),
        invalid_password=_required("KEYCLOAK_TEST_INVALID_PASSWORD"),
        ca_bundle=os.environ.get("KEYCLOAK_TEST_CA_BUNDLE") or None,
    )


@pytest.fixture()
def secure_page(browser: Browser, request: pytest.FixtureRequest, settings: Settings) -> Iterator[Page]:
    """Capture a scrubbed action trace plus anonymous rendered diagnostics."""
    context: BrowserContext = browser.new_context(
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=False,
    )
    page = context.new_page()
    browser_events: list[dict[str, object]] = []

    def append_event(event: dict[str, object]) -> None:
        if len(browser_events) < 200:
            browser_events.append(event)

    page.on(
        "console",
        lambda message: append_event(
            {
                "event": "console",
                "type": message.type,
                "origin_path": _safe_location(str(message.location.get("url", ""))),
            }
        ),
    )
    page.on(
        "response",
        lambda response: append_event(
            {
                "event": "response",
                "method": response.request.method,
                "status": response.status,
                "origin_path": _safe_location(response.url),
            }
        ),
    )
    # Capture the actual journey's action sequence. Snapshots, screenshots,
    # sources, network records, input values, headers, and storage are never
    # retained in the published trace; the sanitizer below fails closed.
    context.tracing.start(screenshots=False, snapshots=False, sources=False)
    yield page
    failed = bool(getattr(request.node, "rep_call", None) and request.node.rep_call.failed)
    if failed:
        root = Path(os.environ.get("KEYCLOAK_TEST_ARTIFACTS", "artifacts"))
        screenshots = root / "screenshots"
        traces = root / "playwright-traces"
        diagnostics = root / "browser-diagnostics"
        screenshots.mkdir(parents=True, exist_ok=True)
        traces.mkdir(parents=True, exist_ok=True)
        diagnostics.mkdir(parents=True, exist_ok=True)
        artifact_name = _artifact_name(request.node.name)
        failure_location = _safe_location(page.url)
        with tempfile.TemporaryDirectory(prefix="keycloak-acceptance-trace-") as temporary:
            raw_trace = Path(temporary) / "raw-trace.zip"
            context.tracing.stop(path=str(raw_trace))
            sanitize_trace(
                raw_trace,
                traces / f"{artifact_name}.zip",
                secrets=(
                    settings.client_secret,
                    settings.admin_username,
                    settings.admin_password,
                    settings.viewer_username,
                    settings.viewer_password,
                    settings.unauthorized_username,
                    settings.unauthorized_password,
                    settings.invalid_username,
                    settings.invalid_password,
                ),
            )
        (diagnostics / f"{artifact_name}.json").write_text(
            json.dumps(browser_events, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # Render a screenshot in a fresh context so pixels and DOM snapshots from
        # the authenticated page never become evidence.
        diagnostic_context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            ignore_https_errors=False,
            service_workers="block",
        )
        try:
            if diagnostic_context.cookies():
                pytest.fail("fresh diagnostic browser context unexpectedly contains cookies", pytrace=False)
            diagnostic_page = diagnostic_context.new_page()
            diagnostic_page.set_content(
                _diagnostic_html(request.node.name, failure_location, browser_events),
                wait_until="domcontentloaded",
            )
            diagnostic_page.screenshot(path=str(screenshots / f"{artifact_name}.png"), full_page=True)
            if diagnostic_context.cookies():
                pytest.fail("diagnostic browser context created a cookie", pytrace=False)
        finally:
            diagnostic_context.close()
    else:
        context.tracing.stop()
    context.close()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)
