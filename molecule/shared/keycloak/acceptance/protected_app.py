#!/usr/bin/env python3
"""Minimal test-only OIDC relying party used by Keycloak acceptance tests."""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from authlib.integrations.flask_client import OAuth
from flask import Flask, Response, jsonify, redirect, session, url_for

View = TypeVar("View", bound=Callable[..., Response | str])


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"Required environment variable {name} is missing")
    return value


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = required_env("OIDC_SESSION_SECRET")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("OIDC_COOKIE_SECURE", "true").lower() == "true",
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    issuer = required_env("OIDC_ISSUER").rstrip("/")
    oauth = OAuth(app)
    oauth.register(
        name="keycloak",
        client_id=required_env("OIDC_CLIENT_ID"),
        client_secret=required_env("OIDC_CLIENT_SECRET"),
        server_metadata_url=f"{issuer}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid profile email groups"},
    )

    def authenticated(view: View) -> View:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Response | str:
            if "user" not in session:
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return cast(View, wrapper)

    def has_role(role: str) -> bool:
        user = session.get("user", {})
        realm_roles = user.get("realm_access", {}).get("roles", [])
        client_roles = user.get("resource_access", {}).get(required_env("OIDC_CLIENT_ID"), {}).get("roles", [])
        return role in realm_roles or role in client_roles

    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify(status="ok")

    @app.get("/")
    def index() -> Response | str:
        if "user" not in session:
            return '<a id="login" href="/login">Sign in</a>'
        username = session["user"].get("preferred_username", "unknown")
        return f'<p id="username">{username}</p><a id="logout" href="/logout">Sign out</a>'

    @app.get("/login")
    def login() -> Response:
        return oauth.keycloak.authorize_redirect(url_for("callback", _external=True))

    @app.get("/callback")
    def callback() -> Response:
        token = oauth.keycloak.authorize_access_token()
        claims = token.get("userinfo") or oauth.keycloak.parse_id_token(token)
        session.clear()
        session["user"] = dict(claims)
        return redirect(url_for("viewer"))

    @app.get("/viewer")
    @authenticated
    def viewer() -> Response:
        if not (has_role("viewer") or has_role("admin")):
            return jsonify(error="forbidden"), 403
        return jsonify(access="viewer", username=session["user"].get("preferred_username"))

    @app.route("/admin", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    @authenticated
    def admin() -> Response:
        if not has_role("admin"):
            return jsonify(error="forbidden"), 403
        return jsonify(access="admin", operation="allowed")

    @app.get("/logout")
    def logout() -> Response:
        session.clear()
        return redirect(url_for("index"))

    return app


app = create_app()
