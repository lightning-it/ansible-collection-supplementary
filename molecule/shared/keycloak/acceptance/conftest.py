"""Fail-closed pytest fixtures and secret-safe Playwright diagnostics."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Browser, BrowserContext, Page


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
def secure_page(browser: Browser, request: pytest.FixtureRequest) -> Iterator[Page]:
    """Trace only non-secret browser activity and sanitize screenshots on failure."""
    context: BrowserContext = browser.new_context(
        viewport={"width": 1440, "height": 900},
        ignore_https_errors=False,
    )
    page = context.new_page()
    browser_events: list[dict[str, object]] = []
    page.on(
        "console",
        lambda message: browser_events.append(
            {"event": "console", "type": message.type, "location": message.location}
        ),
    )
    page.on(
        "response",
        lambda response: browser_events.append(
            {
                "event": "response",
                "method": response.request.method,
                "status": response.status,
                "origin_path": (
                    f"{urlsplit(response.url).scheme}://{urlsplit(response.url).netloc}"
                    f"{urlsplit(response.url).path}"
                ),
            }
        ),
    )
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
        (diagnostics / f"{request.node.name}.json").write_text(
            json.dumps(browser_events, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # Password values must never enter screenshots or traces. Clear inputs,
        # then capture a fresh diagnostic trace containing no authentication data.
        page.locator("input").evaluate_all("els => els.forEach(e => e.value = '')")
        page.screenshot(path=str(screenshots / f"{request.node.name}.png"), full_page=True)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page.reload(wait_until="domcontentloaded")
        context.tracing.stop(path=str(traces / f"{request.node.name}.zip"))
    context.close()


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)
