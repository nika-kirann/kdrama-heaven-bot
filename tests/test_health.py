import json
import urllib.request

from health import start_health_server


def test_healthz_root_and_404():
    srv = start_health_server(port=0, host="127.0.0.1")
    port = srv.server_address[1]
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
            assert r.status == 200 and r.headers["Content-Type"] == "application/json"
            assert json.loads(r.read())["ok"] is True
        # "/" is the public website once the bot context is set, plain health JSON before that
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
        req = urllib.request.Request(f"http://127.0.0.1:{port}/healthz", method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()


def test_no_port_no_server(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert start_health_server() is None
