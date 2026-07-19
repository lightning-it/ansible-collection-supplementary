"""Keycloak browser journeys and protocol/API authorization assertions."""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import allure
import httpx
import pytest
from authlib.jose import JsonWebKey, jwt
from authlib.jose.errors import JoseError
from conftest import Settings
from playwright.sync_api import Page, expect


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _login(page: Page, settings: Settings, username: str, password: str) -> None:
    page.goto(f"{settings.app_url}/login", wait_until="domcontentloaded")
    expect(page.locator("#username")).to_be_visible()
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("#kc-login").click()
    page.wait_for_url(f"{settings.app_url}/viewer", wait_until="domcontentloaded")


def _token(settings: Settings, username: str, password: str) -> dict[str, Any]:
    response = httpx.post(
        f"{settings.issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "username": username,
            "password": password,
            "scope": "openid profile email",
        },
        timeout=20,
        verify=settings.ca_bundle or True,
    )
    assert response.status_code == 200, f"token request failed with HTTP {response.status_code}"
    return response.json()


def _claims(settings: Settings, encoded: str) -> dict[str, Any]:
    discovery = httpx.get(
        f"{settings.issuer}/.well-known/openid-configuration",
        verify=settings.ca_bundle or True,
    ).json()
    jwks = httpx.get(discovery["jwks_uri"], verify=settings.ca_bundle or True).json()
    header = json.loads(_b64url_decode(encoded.split(".")[0]))
    key = next(key for key in jwks["keys"] if key["kid"] == header["kid"])
    claims = jwt.decode(
        encoded,
        JsonWebKey.import_key(key),
        claims_options={"iss": {"essential": True, "value": settings.issuer}},
    )
    claims.validate()
    return dict(claims)


@allure.epic("Keycloak application acceptance")
@pytest.mark.evidence_role("keycloak_cac")
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_viewer_is_read_only(secure_page: Page, settings: Settings, method: str) -> None:
    _login(secure_page, settings, settings.viewer_username, settings.viewer_password)
    assert secure_page.request.get(f"{settings.app_url}/viewer").status == 200
    assert getattr(secure_page.request, method)(f"{settings.app_url}/admin").status == 403
    secure_page.goto(f"{settings.app_url}/logout")
    assert secure_page.request.get(f"{settings.app_url}/viewer", max_redirects=0).status in (302, 303)


@pytest.mark.evidence_role("keycloak_cac")
def test_admin_browser_session_and_logout(secure_page: Page, settings: Settings) -> None:
    _login(secure_page, settings, settings.admin_username, settings.admin_password)
    assert secure_page.request.get(f"{settings.app_url}/viewer").status == 200
    assert secure_page.request.post(f"{settings.app_url}/admin").status == 200
    secure_page.goto(f"{settings.app_url}/logout")
    expect(secure_page.locator("#login")).to_be_visible()
    response = secure_page.request.get(f"{settings.app_url}/admin", max_redirects=0)
    assert response.status in (302, 303)
    secure_page.goto(f"{settings.app_url}/login", wait_until="domcontentloaded")
    expect(secure_page.locator("#username")).to_be_visible()


@pytest.mark.evidence_role("keycloak_cac")
def test_unauthorized_user_denied(secure_page: Page, settings: Settings) -> None:
    _login(secure_page, settings, settings.unauthorized_username, settings.unauthorized_password)
    assert secure_page.request.get(f"{settings.app_url}/viewer").status == 403
    assert secure_page.request.post(f"{settings.app_url}/admin").status == 403


@pytest.mark.evidence_role("keycloak_cac")
def test_invalid_credentials_create_no_session(secure_page: Page, settings: Settings) -> None:
    secure_page.goto(f"{settings.app_url}/login")
    secure_page.locator("#username").fill(settings.invalid_username)
    secure_page.locator("#password").fill(settings.invalid_password)
    secure_page.locator("#kc-login").click()
    expect(secure_page.locator("#input-error")).to_be_visible()
    response = secure_page.request.get(f"{settings.app_url}/admin", max_redirects=0)
    assert response.status in (302, 303)


@pytest.mark.evidence_role("keycloak_deploy")
def test_oidc_metadata_signature_and_claims(settings: Settings) -> None:
    discovery = httpx.get(
        f"{settings.issuer}/.well-known/openid-configuration",
        verify=settings.ca_bundle or True,
    ).json()
    assert discovery["issuer"] == settings.issuer
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        assert discovery[field].startswith(settings.issuer)
    token = _token(settings, settings.viewer_username, settings.viewer_password)
    claims = _claims(settings, token["access_token"])
    assert claims["iss"] == settings.issuer
    assert claims["sub"]
    assert claims["preferred_username"] == settings.viewer_username
    audience = claims.get("aud", [])
    assert settings.client_id in ([audience] if isinstance(audience, str) else audience)
    assert claims.get("email")
    assert claims["exp"] > int(time.time())
    assert claims.get("azp") == settings.client_id
    audience = claims.get("aud", [])
    assert settings.client_id in ([audience] if isinstance(audience, str) else audience)
    assert claims.get("groups")
    roles = claims.get("realm_access", {}).get("roles", [])
    client_roles = claims.get("resource_access", {}).get(settings.client_id, {}).get("roles", [])
    assert "viewer" in roles or "viewer" in client_roles


@pytest.mark.parametrize(
    ("username_attr", "password_attr", "expected_role", "must_have_role"),
    [
        ("admin_username", "admin_password", "admin", True),
        ("viewer_username", "viewer_password", "viewer", True),
        ("unauthorized_username", "unauthorized_password", "admin", False),
    ],
)
@pytest.mark.evidence_role("keycloak_cac")
def test_identity_role_mappings(
    settings: Settings,
    username_attr: str,
    password_attr: str,
    expected_role: str,
    must_have_role: bool,
) -> None:
    token = _token(settings, getattr(settings, username_attr), getattr(settings, password_attr))
    claims = _claims(settings, token["access_token"])
    roles = set(claims.get("realm_access", {}).get("roles", []))
    roles.update(claims.get("resource_access", {}).get(settings.client_id, {}).get("roles", []))
    assert (expected_role in roles) is must_have_role


@pytest.mark.evidence_role("keycloak_cac")
def test_invalid_password_issues_no_token(settings: Settings) -> None:
    response = httpx.post(
        f"{settings.issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "username": settings.invalid_username,
            "password": settings.invalid_password,
        },
        verify=settings.ca_bundle or True,
    )
    assert response.status_code in (400, 401)
    body = response.json()
    assert "access_token" not in body and "refresh_token" not in body and "id_token" not in body


@pytest.mark.evidence_role("keycloak_deploy")
def test_backchannel_logout_revokes_refresh_session(settings: Settings) -> None:
    token = _token(settings, settings.viewer_username, settings.viewer_password)
    logout = httpx.post(
        f"{settings.issuer}/protocol/openid-connect/logout",
        data={
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "refresh_token": token["refresh_token"],
        },
        timeout=20,
        verify=settings.ca_bundle or True,
    )
    assert logout.status_code in (200, 204)

    refresh = httpx.post(
        f"{settings.issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "refresh_token",
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "refresh_token": token["refresh_token"],
        },
        timeout=20,
        verify=settings.ca_bundle or True,
    )
    assert refresh.status_code in (400, 401)
    assert "access_token" not in refresh.json()


@pytest.mark.evidence_role("keycloak_deploy")
def test_tampered_and_expired_tokens_are_rejected(settings: Settings) -> None:
    token = _token(settings, settings.viewer_username, settings.viewer_password)["access_token"]
    header, payload, signature = token.split(".")
    assert signature
    replacement = "A" if signature[0] != "A" else "B"
    tampered_signature = replacement + signature[1:]
    assert _b64url_decode(tampered_signature) != _b64url_decode(signature)
    tampered = ".".join((header, payload, tampered_signature))
    with pytest.raises((JoseError, KeyError, ValueError)):
        _claims(settings, tampered)
    # A syntactically valid but unsigned expired token must also fail signature validation.
    expired = jwt.encode({"alg": "none"}, {"iss": settings.issuer, "exp": 1}, None).decode()
    with pytest.raises((JoseError, KeyError, ValueError)):
        _claims(settings, expired)
