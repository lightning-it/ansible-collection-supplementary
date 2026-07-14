#!/usr/bin/env python3
"""Small state-file-backed Vault lifecycle API used by light Molecule tests."""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class VaultHandler(BaseHTTPRequestHandler):
    server_version = "MoleculeVault/1.0"

    @property
    def state_path(self) -> Path:
        return self.server.state_path  # type: ignore[attr-defined]

    @property
    def request_log_path(self) -> Path:
        return self.server.request_log_path  # type: ignore[attr-defined]

    def read_state(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_state(self, state: dict[str, Any]) -> None:
        temporary_path = self.state_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(state), encoding="utf-8")
        temporary_path.chmod(0o600)
        temporary_path.replace(self.state_path)

    def log_request_line(self) -> None:
        with self.request_log_path.open("a", encoding="utf-8") as request_log:
            request_log.write(f"{self.command} {self.path}\n")

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        response = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def send_bytes(self, status: int, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(content_length) or b"{}")

    def read_raw_body(self) -> bytes:
        content_length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(content_length)

    def token_policies(self, state: dict[str, Any]) -> list[str]:
        token = self.headers.get("X-Vault-Token", "")
        root_token = state.get("root_token", "molecule-root-token-fixture")
        scoped_token = state.get("scoped_token", "molecule-scoped-token-fixture")
        if token == root_token and state.get("root_token_active", True):
            return ["root"]
        if token == scoped_token:
            return [state.get("policy_name", "molecule-automation")]
        return []

    def is_root(self, state: dict[str, Any]) -> bool:
        return "root" in self.token_policies(state)

    def require_root(self, state: dict[str, Any]) -> bool:
        if self.is_root(state):
            return True
        self.send_json(403, {"errors": ["permission denied"]})
        return False

    def do_GET(self) -> None:  # noqa: N802
        self.log_request_line()
        state = self.read_state()

        if self.path == "/v1/sys/health":
            status = 503 if state["sealed"] else 200
            self.send_json(
                status,
                {
                    "initialized": state["initialized"],
                    "sealed": state["sealed"],
                    "cluster_id": state.get("cluster_id", "molecule-cluster-id"),
                },
            )
            return

        if self.path == "/v1/sys/init":
            self.send_json(200, {"initialized": state["initialized"]})
            return

        if self.path == "/v1/sys/seal-status":
            self.send_json(
                200,
                {
                    "initialized": state["initialized"],
                    "sealed": state["sealed"],
                    "t": state["threshold"],
                    "progress": state["progress"],
                },
            )
            return

        if self.path == "/v1/auth/token/lookup-self":
            policies = self.token_policies(state)
            if not policies:
                self.send_json(403, {"errors": ["permission denied"]})
                return
            self.send_json(200, {"data": {"policies": policies}})
            return

        if self.path == "/v1/sys/mounts":
            if not self.require_root(state):
                return
            self.send_json(200, {"data": state.get("mounts", {})})
            return

        if self.path == "/v1/sys/auth":
            if not self.require_root(state):
                return
            self.send_json(200, {"data": state.get("auth_methods", {})})
            return

        if self.path.startswith("/v1/sys/policies/acl/"):
            if not self.require_root(state):
                return
            policy_name = self.path.rsplit("/", 1)[-1]
            policy = state.get("policies", {}).get(policy_name)
            if policy is None:
                self.send_json(404, {"errors": ["not found"]})
                return
            self.send_json(200, {"data": {"policy": policy}})
            return

        if "/role/" in self.path and self.path.endswith("/role-id"):
            if not self.require_root(state):
                return
            self.send_json(
                200,
                {"data": {"role_id": state.get("role_id", "molecule-role-id-fixture")}},
            )
            return

        if "/role/" in self.path:
            if not self.require_root(state):
                return
            role_name = self.path.rsplit("/", 1)[-1]
            role = state.get("roles", {}).get(role_name)
            if role is None:
                self.send_json(404, {"errors": ["not found"]})
                return
            self.send_json(200, {"data": role})
            return

        if self.path == "/v1/sys/storage/raft/snapshot":
            if not self.token_policies(state):
                self.send_json(403, {"errors": ["permission denied"]})
                return
            snapshot = base64.b64decode(
                state.get("snapshot_b64", base64.b64encode(b"molecule-raft-snapshot\n").decode())
            )
            self.send_bytes(200, snapshot)
            return

        if self.path.startswith("/v1/") and "/data/" in self.path:
            if not self.token_policies(state):
                self.send_json(403, {"errors": ["permission denied"]})
                return
            document = state.get("kv_documents", {}).get(self.path.removeprefix("/v1/"))
            if document is None:
                self.send_json(404, {"errors": ["not found"]})
                return
            self.send_json(200, {"data": {"data": document}})
            return

        self.send_json(404, {"errors": ["not found"]})

    def do_POST(self) -> None:  # noqa: N802
        self.log_request_line()
        state = self.read_state()

        if self.path == "/v1/sys/storage/raft/snapshot-force":
            snapshot = self.read_raw_body()
            if not self.require_root(state):
                return
            try:
                restored_state = json.loads(snapshot)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self.send_json(400, {"errors": ["invalid test snapshot"]})
                return
            restored_state.update(
                {
                    "initialized": True,
                    "sealed": True,
                    "progress": 0,
                    "root_token_active": True,
                    "snapshot_b64": base64.b64encode(snapshot).decode(),
                }
            )
            self.write_state(restored_state)
            self.send_json(204, {})
            return

        payload = self.read_json_body()

        if self.path == "/v1/sys/init":
            if state["initialized"]:
                self.send_json(400, {"errors": ["already initialized"]})
                return
            threshold = int(payload.get("secret_threshold", 1))
            state.update(
                {
                    "initialized": True,
                    "sealed": True,
                    "threshold": threshold,
                    "progress": 0,
                    "cluster_id": "molecule-ephemeral-cluster-id",
                    "root_token": "molecule-ephemeral-root-token",
                    "root_token_active": True,
                }
            )
            self.write_state(state)
            self.send_json(
                200,
                {
                    "keys_base64": ["molecule-ephemeral-unseal-key"],
                    "root_token": state["root_token"],
                },
            )
            return

        if self.path == "/v1/sys/unseal" and state["sealed"] and payload.get("key"):
            state["progress"] += 1
            if state["progress"] >= state["threshold"]:
                state["sealed"] = False
                state["progress"] = 0
            self.write_state(state)
            self.send_json(
                200,
                {
                    "sealed": state["sealed"],
                    "t": state["threshold"],
                    "progress": state["progress"],
                },
            )
            return

        if self.path.startswith("/v1/sys/mounts/"):
            if not self.require_root(state):
                return
            mount_point = self.path.rsplit("/", 1)[-1]
            state.setdefault("mounts", {})[f"{mount_point}/"] = {
                "type": payload.get("type", "kv"),
                "options": payload.get("options", {}),
            }
            self.write_state(state)
            self.send_json(204, {})
            return

        if self.path.startswith("/v1/sys/auth/"):
            if not self.require_root(state):
                return
            mount_point = self.path.rsplit("/", 1)[-1]
            state.setdefault("auth_methods", {})[f"{mount_point}/"] = {
                "type": payload.get("type", "approle")
            }
            self.write_state(state)
            self.send_json(204, {})
            return

        if self.path.endswith("/secret-id"):
            if not self.require_root(state):
                return
            self.send_json(
                200,
                {"data": {"secret_id": state.get("secret_id", "molecule-secret-id-fixture")}},
            )
            return

        if self.path.endswith("/login"):
            if (
                payload.get("role_id") != state.get("role_id", "molecule-role-id-fixture")
                or payload.get("secret_id")
                != state.get("secret_id", "molecule-secret-id-fixture")
            ):
                self.send_json(403, {"errors": ["invalid credentials"]})
                return
            policy_name = state.get("policy_name", "molecule-automation")
            self.send_json(
                200,
                {
                    "auth": {
                        "client_token": state.get(
                            "scoped_token", "molecule-scoped-token-fixture"
                        ),
                        "token_policies": [policy_name],
                        "lease_duration": state.get("token_ttl", 1200),
                    }
                },
            )
            return

        if self.path == "/v1/sys/capabilities-self":
            if not self.token_policies(state):
                self.send_json(403, {"errors": ["permission denied"]})
                return
            capabilities = state.get("capabilities", {})
            self.send_json(
                200,
                {path: capabilities.get(path, ["deny"]) for path in payload.get("paths", [])},
            )
            return

        if self.path == "/v1/auth/token/revoke-self":
            if "root" not in self.token_policies(state):
                self.send_json(403, {"errors": ["permission denied"]})
                return
            state["root_token_active"] = False
            self.write_state(state)
            self.send_json(204, {})
            return

        if "/role/" in self.path:
            if not self.require_root(state):
                return
            role_name = self.path.rsplit("/", 1)[-1]
            role = dict(payload)
            role["token_ttl"] = state.get("token_ttl", 1200)
            role["token_max_ttl"] = state.get("token_max_ttl", 3600)
            state.setdefault("roles", {})[role_name] = role
            state["policy_name"] = payload.get("token_policies", ["molecule-automation"])[0]
            self.write_state(state)
            self.send_json(204, {})
            return

        self.send_json(404, {"errors": ["not found"]})

    def do_PUT(self) -> None:  # noqa: N802
        self.log_request_line()
        payload = self.read_json_body()
        state = self.read_state()
        if self.path.startswith("/v1/sys/policies/acl/"):
            if not self.require_root(state):
                return
            policy_name = self.path.rsplit("/", 1)[-1]
            state.setdefault("policies", {})[policy_name] = payload.get("policy", "")
            state["policy_name"] = policy_name
            self.write_state(state)
            self.send_json(204, {})
            return
        self.send_json(404, {"errors": ["not found"]})

    def log_message(self, message_format: str, *args: object) -> None:
        del message_format, args


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--request-log", type=Path, required=True)
    parser.add_argument("--pid-file", type=Path, required=True)
    parser.add_argument("--cert", type=Path)
    parser.add_argument("--key", type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    server = ThreadingHTTPServer(("127.0.0.1", arguments.port), VaultHandler)
    server.state_path = arguments.state  # type: ignore[attr-defined]
    server.request_log_path = arguments.request_log  # type: ignore[attr-defined]
    if arguments.cert and arguments.key:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(arguments.cert, arguments.key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    arguments.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    server.serve_forever()


if __name__ == "__main__":
    main()
