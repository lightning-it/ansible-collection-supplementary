#!/usr/bin/env python3
"""Minimal test-only OIDC relying party used by Keycloak acceptance tests."""

from __future__ import annotations

import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from functools import wraps
from typing import Any, TypeVar, cast
from urllib.parse import urlencode

from authlib.integrations.flask_client import OAuth
from flask import Flask, Response, jsonify, redirect, session, url_for
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict

View = TypeVar("View", bound=Callable[..., Response | str])
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{43}$")


class ServerSideSession(CallbackDict[str, Any], SessionMixin):
    """Mutable server-side state identified by an opaque browser cookie."""

    def __init__(self, initial: dict[str, Any] | None, sid: str, *, new: bool) -> None:
        def on_update(_: CallbackDict[str, Any]) -> None:
            self.modified = True

        super().__init__(initial, on_update)
        self.sid = sid
        self.new = new
        self.modified = False


class BoundedMemorySessionInterface(SessionInterface):
    """Test-only, bounded session store that never serializes OIDC data to a cookie."""

    def __init__(self, *, ttl_seconds: int = 900, maximum_sessions: int = 1024) -> None:
        self._ttl_seconds = ttl_seconds
        self._maximum_sessions = maximum_sessions
        self._lock = threading.RLock()
        self._sessions: dict[str, tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def _new_sid() -> str:
        return secrets.token_urlsafe(32)

    def _purge(self, now: float) -> None:
        expired = [sid for sid, (deadline, _) in self._sessions.items() if deadline <= now]
        for sid in expired:
            self._sessions.pop(sid, None)
        while len(self._sessions) >= self._maximum_sessions:
            oldest = min(self._sessions, key=lambda sid: self._sessions[sid][0])
            self._sessions.pop(oldest, None)

    def open_session(self, app: Flask, request: Any) -> ServerSideSession:  # type: ignore[override]
        sid = request.cookies.get(self.get_cookie_name(app), "")
        now = time.monotonic()
        with self._lock:
            self._purge(now)
            stored = self._sessions.get(sid) if SESSION_ID.fullmatch(sid) else None
            if stored is None:
                return ServerSideSession({}, self._new_sid(), new=True)
            _, data = stored
            return ServerSideSession(dict(data), sid, new=False)

    def rotate(self, current: ServerSideSession) -> None:
        """Invalidate the pre-authentication identifier before storing OIDC state."""

        with self._lock:
            self._sessions.pop(current.sid, None)
        current.sid = self._new_sid()
        current.new = True
        current.modified = True

    def save_session(self, app: Flask, current: ServerSideSession, response: Response) -> None:  # type: ignore[override]
        cookie_name = self.get_cookie_name(app)
        cookie_options = {
            "domain": self.get_cookie_domain(app),
            "path": self.get_cookie_path(app),
            "secure": self.get_cookie_secure(app),
            "httponly": self.get_cookie_httponly(app),
            "samesite": self.get_cookie_samesite(app),
        }
        if not current:
            with self._lock:
                self._sessions.pop(current.sid, None)
            if current.modified:
                response.delete_cookie(cookie_name, **cookie_options)
            return

        now = time.monotonic()
        with self._lock:
            self._purge(now)
            self._sessions[current.sid] = (now + self._ttl_seconds, dict(current))
        response.set_cookie(
            cookie_name,
            current.sid,
            max_age=self._ttl_seconds,
            **cookie_options,
        )


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"Required environment variable {name} is missing")
    return value


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = required_env("OIDC_SESSION_SECRET")
    server_sessions = BoundedMemorySessionInterface()
    app.session_interface = server_sessions
    app.config.update(
        SESSION_COOKIE_NAME="oidc_acceptance_sid",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("OIDC_COOKIE_SECURE", "true").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=15),
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    issuer = required_env("OIDC_ISSUER").rstrip("/")
    client_id = required_env("OIDC_CLIENT_ID")
    client_secret = required_env("OIDC_CLIENT_SECRET")
    oauth = OAuth(app)
    oauth.register(
        name="keycloak",
        client_id=client_id,
        client_secret=client_secret,
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
        client_roles = user.get("resource_access", {}).get(client_id, {}).get("roles", [])
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
        server_sessions.rotate(cast(ServerSideSession, session._get_current_object()))
        session.permanent = True
        session["user"] = dict(claims)
        session["id_token"] = token.get("id_token", "")
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
        id_token = str(session.get("id_token", ""))
        session.clear()
        if not id_token:
            return redirect(url_for("index"))
        parameters = urlencode(
            {
                "client_id": client_id,
                "id_token_hint": id_token,
                "post_logout_redirect_uri": url_for("index", _external=True),
            }
        )
        return redirect(f"{issuer}/protocol/openid-connect/logout?{parameters}")

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return app


app = create_app()
