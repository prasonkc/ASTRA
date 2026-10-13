"""Local HTTP bridge that lets the ASTRA Firefox extension feed the core.

The terminal app is the source of truth and normally runs no web server, so it
needs a tiny localhost listener to receive the page snapshots the extension
pushes. This module provides one with zero dependencies (stdlib only).

The astra-web wrapper exposes the *identical* routes through FastAPI instead
(its own server already owns the same port), so the extension's endpoint URL is
the same whether the user runs the terminal app or the web app:

    POST   /api/browser/context   merge a page snapshot
    GET    /api/browser/context   return the latest snapshot
    DELETE /api/browser/context   forget the snapshot
    GET    /api/browser/commands  claim the next queued browser command
    POST   /api/browser/commands/<id>/result   report a command's result
    POST   /api/browser/message   run one chat turn for the extension popup

Configuration (environment variables):

- ``ASTRA_BROWSER_BRIDGE`` — set to ``0``/``false`` to disable the listener.
- ``ASTRA_BROWSER_HOST`` — bind host (default ``127.0.0.1``).
- ``ASTRA_BROWSER_PORT`` — bind port (default ``8765``, the web app's port; if
  that port is already taken — e.g. astra-web is running — the bridge silently
  stays off and the web server handles the requests instead).
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from browser_bridge import (
    clear_context,
    get_context,
    next_command,
    run_message,
    set_context,
    submit_command_result,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_ENDPOINT = "/api/browser/context"

_server: Optional[ThreadingHTTPServer] = None
_started = False
_lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    server_version = "ASTRA-BrowserBridge/0.1"

    # ---- small helpers --------------------------------------------------
    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        """Read and parse a JSON object body (``{}`` when empty)."""
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") if raw else "{}")
        if not isinstance(data, dict):
            raise ValueError("payload must be a JSON object")
        return data

    def log_message(self, *args):  # keep the terminal output clean
        pass

    # ---- routes ---------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self._path() == _ENDPOINT:
            self._send_json(200, {"context": get_context()})
            return
        if self._path() == "/api/browser/commands":
            self._send_json(200, {"command": next_command()})
            return
        self._send_json(404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        path = self._path()
        if path == _ENDPOINT:
            self._handle_post_context()
            return
        if path == "/api/browser/message":
            self._handle_post_message()
            return
        if path.startswith("/api/browser/commands/"):
            self._handle_post_command_result(path)
            return
        self._send_json(404, {"ok": False, "error": "Not found"})

    def _handle_post_context(self) -> None:
        try:
            data = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": f"Invalid JSON: {exc}"})
            return

        stored = set_context(data)
        self._send_json(200, {"ok": True, "received_at": stored.get("received_at")})

    def _handle_post_message(self) -> None:
        """Forward an extension chat message to the running agent.

        Blocks until the turn finishes (the extension popup owns the request and
        polls its own state), then returns ``{ok, reply, error, session_id}``.
        """
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": f"Invalid JSON: {exc}"})
            return

        result = run_message(str(payload.get("message", "")))
        self._send_json(200, result)

    def _handle_post_command_result(self, path: str) -> None:
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": f"Invalid JSON: {exc}"})
            return

        # Path: /api/browser/commands/<id>/result
        segments = [s for s in path.split("/") if s]
        if len(segments) != 5 or not segments[3].isdigit():
            self._send_json(400, {"ok": False, "error": "Malformed command id"})
            return

        command_id = int(segments[3])
        accepted = submit_command_result(
            command_id,
            ok=bool(payload.get("ok", True)),
            result=payload.get("result"),
            error=payload.get("error"),
        )
        if not accepted:
            self._send_json(404, {"ok": False, "error": "Command not found or already finished"})
            return
        self._send_json(200, {"accepted": True})

    def do_DELETE(self):
        if self._path() != _ENDPOINT:
            self._send_json(404, {"ok": False, "error": "Not found"})
            return
        clear_context()
        self._send_json(200, {"ok": True})


def start_browser_context_server(
    host: Optional[str] = None, port: Optional[int] = None
) -> Optional[ThreadingHTTPServer]:
    """Start the localhost bridge (idempotent).

    Returns the server when it is listening, ``None`` when it is disabled via
    ``ASTRA_BROWSER_BRIDGE=0`` or when the port is already in use (astra-web may
    already be running and serving the same routes).
    """
    global _server, _started
    if _started:
        return _server

    if str(os.environ.get("ASTRA_BROWSER_BRIDGE", "1")).lower() in (
        "0", "false", "no", "off", "disabled",
    ):
        _started = True
        return None

    host = host or os.environ.get("ASTRA_BROWSER_HOST") or DEFAULT_HOST
    try:
        port = port if port is not None else int(
            os.environ.get("ASTRA_BROWSER_PORT") or DEFAULT_PORT
        )
    except ValueError:
        port = DEFAULT_PORT

    with _lock:
        try:
            server = ThreadingHTTPServer((host, port), _Handler)
        except OSError:
            # Port busy (astra-web is probably running) — leave the HTTP side
            # to that server. Not an error.
            _started = True
            return None

        server.daemon_threads = True
        thread = threading.Thread(
            target=server.serve_forever,
            name="astra-browser-bridge",
            daemon=True,
        )
        thread.start()
        _server = server
        _started = True
        return server


def browser_bridge_endpoint() -> Optional[str]:
    """Return the endpoint the bridge would listen on, or ``None`` if disabled."""
    if str(os.environ.get("ASTRA_BROWSER_BRIDGE", "1")).lower() in (
        "0", "false", "no", "off", "disabled",
    ):
        return None
    host = os.environ.get("ASTRA_BROWSER_HOST") or DEFAULT_HOST
    try:
        port = int(os.environ.get("ASTRA_BROWSER_PORT") or DEFAULT_PORT)
    except ValueError:
        port = DEFAULT_PORT
    return f"http://{host}:{port}{_ENDPOINT}"