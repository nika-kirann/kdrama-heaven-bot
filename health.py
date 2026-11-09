"""HTTP health + admin panel server.

Kept as health.py so older imports / docs keep working. The real implementation
lives in web/ and serves /healthz (public) plus /admin* (auth-protected) on PORT.
"""
from web import set_context, start_web_server

# Legacy names
start_health_server = start_web_server
STARTED = None  # web.app.STARTED is the real uptime clock

__all__ = ["start_health_server", "start_web_server", "set_context"]
