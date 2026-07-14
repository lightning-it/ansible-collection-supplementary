#!/usr/bin/env python3
"""Small state-file-backed Vault lifecycle API used by light Molecule tests."""

from __future__ import annotations

import argparse
import json
import os
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

        self.send_json(404, {"errors": ["not found"]})

    def do_POST(self) -> None:  # noqa: N802
        self.log_request_line()
        if self.path != "/v1/sys/unseal":
            self.send_json(404, {"errors": ["not found"]})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(content_length) or b"{}")
        state = self.read_state()

        if state["sealed"] and payload.get("key"):
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

    def log_message(self, message_format: str, *args: object) -> None:
        del message_format, args


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--request-log", type=Path, required=True)
    parser.add_argument("--pid-file", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    server = ThreadingHTTPServer(("127.0.0.1", arguments.port), VaultHandler)
    server.state_path = arguments.state  # type: ignore[attr-defined]
    server.request_log_path = arguments.request_log  # type: ignore[attr-defined]
    arguments.pid_file.write_text(str(os.getpid()), encoding="utf-8")
    server.serve_forever()


if __name__ == "__main__":
    main()
