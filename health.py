"""Tiny HTTP health server (stdlib) so the bot can run as a Koyeb *web* service and be pinged by UptimeRobot.
Runs in a daemon thread next to the long-polling bot. Started only when PORT is set (Koyeb sets it)."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)
STARTED = time.time()


class HealthHandler(BaseHTTPRequestHandler):
    server_version = "kdrama-health/1"

    def _send(self, head_only=False):
        if self.path.split("?")[0] not in {"/", "/healthz", "/health"}:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()
            return
        body = json.dumps({"ok": True, "uptime_s": int(time.time() - STARTED)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def do_GET(self):
        self._send()

    def do_HEAD(self):  # UptimeRobot can use HEAD
        self._send(head_only=True)

    def log_message(self, *args):  # keep bot logs clean
        pass


def start_health_server(port: int | None = None, host: str = "0.0.0.0") -> ThreadingHTTPServer | None:
    if port is None:
        raw = os.getenv("PORT", "").strip()
        if not raw.isdigit():
            return None
        port = int(raw)
    srv = ThreadingHTTPServer((host, port), HealthHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="health", daemon=True).start()
    log.info("Health server listening on %s:%s (/healthz)", host, srv.server_address[1])
    return srv
