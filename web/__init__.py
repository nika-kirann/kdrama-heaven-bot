"""Web admin panel + health server on the same PORT (Koyeb web process)."""
from .app import set_context, start_web_server

# Back-compat for health.py / tests that import start_health_server
start_health_server = start_web_server

__all__ = ["set_context", "start_web_server", "start_health_server"]
