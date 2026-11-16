"""HTTP server: public /healthz + protected /admin* panel on the same PORT."""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import re
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import auth as authlib
from . import html as H
from . import public as P
from .forms import (add_drama_links_section, add_episode_form, bulk_add_form,
                    expand_quality_range, parse_paste_lines, plan_bulk, silent_checkbox)

WEB_POSTER_ERR = "Website poster must be a plain http(s) image URL"


def web_poster_field(value: str | None = None) -> str:
    """'Website poster URL' input with a live thumbnail preview (admin.js). Website only; Telegram poster unchanged."""
    v = H.e(value or "")
    img = (f'<img src="{v}" alt="" referrerpolicy="no-referrer">' if value else "")
    return f"""<div class="wp-field" data-wp>
              <div class="wp-in"><label for="wp-url">Website poster URL <span class="muted">(website only)</span></label>
                <input id="wp-url" name="web_poster_url" value="{v}" inputmode="url" autocomplete="off" spellcheck="false"
                  placeholder="https://… image link for the public site">
                <p class="hint muted sm" data-wp-msg>Shown on the public website only. The Telegram poster stays as it is.
                  Leave blank for the gradient title tile.</p></div>
              <div class="wp-prev{' on' if value else ''}" data-wp-prev aria-label="Preview">{img}<span>Preview</span></div>
            </div>"""

log = logging.getLogger(__name__)
STARTED = time.time()
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

_CTX: dict = {}
_AUTH: authlib.AuthState | None = None


def set_context(*, cfg, db, svc, bot=None, loop=None):
    """Attach bot dependencies once the Telegram app is ready."""
    global _AUTH
    _CTX.update(cfg=cfg, db=db, svc=svc, bot=bot, loop=loop)
    _AUTH = authlib.make_auth(
        getattr(cfg, "admin_web_secret", "") or "",
        getattr(cfg, "admin_web_password", "") or "",
        set(cfg.admin_ids or set()),
        getattr(cfg, "bot_token", "") or "",
    )
    log.info("Web admin context ready (admins=%s, password=%s)",
             len(cfg.admin_ids or []), "yes" if _AUTH.password else "no")


def _field(fields: dict, key: str, default: str = "") -> str:
    v = fields.get(key, default)
    if isinstance(v, list):
        return (v[-1] if v else default) or default
    return v if v is not None else default


def _field_list(fields: dict, key: str) -> list[str]:
    v = fields.get(key)
    if v is None:
        return []
    if isinstance(v, list):
        return [x.strip() for x in v if isinstance(x, str) and x.strip()]
    return [v.strip()] if isinstance(v, str) and v.strip() else []


def _flag(fields: dict, key: str) -> bool:
    return _field(fields, key).strip().lower() in {"1", "on", "true", "yes"}


def get_auth() -> authlib.AuthState:
    if _AUTH is None:
        # tests / early boot: empty auth until set_context
        return authlib.make_auth("test-secret", "", set())
    return _AUTH


def run_async(coro, timeout: float = 60):
    """Run a service coroutine from the HTTP thread."""
    loop = _CTX.get("loop")
    if loop and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)
    return asyncio.run(coro)


def start_web_server(port: int | None = None, host: str = "0.0.0.0") -> ThreadingHTTPServer | None:
    if port is None:
        raw = os.getenv("PORT", "").strip()
        if not raw.isdigit():
            return None
        port = int(raw)
    srv = ThreadingHTTPServer((host, port), AdminHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, name="web", daemon=True).start()
    log.info("Web server listening on %s:%s (/healthz, /admin)", host, srv.server_address[1])
    return srv


# back-compat name
start_health_server = start_web_server


def _secure_cookie(handler) -> bool:
    # Prefer Secure when the proxy / request looks like HTTPS
    xf = (handler.headers.get("X-Forwarded-Proto") or "").lower()
    return xf == "https" or handler.headers.get("Host", "").endswith(".koyeb.app")


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "kdrama-admin/1"

    # ---------- low-level helpers ----------
    def log_message(self, fmt, *args):
        if self.path.startswith("/admin"):
            log.info("%s %s", self.address_string(), fmt % args)

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, code: int, body: str, headers: dict | None = None):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, loc: str, headers: dict | None = None):
        self.send_response(303)
        self.send_header("Location", loc)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cookie(self, name: str) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        c = SimpleCookie()
        c.load(raw)
        morsel = c.get(name)
        return morsel.value if morsel else None

    def _set_cookie_header(self, name: str, value: str, max_age: int) -> str:
        parts = [f"{name}={value}", "Path=/", f"Max-Age={max_age}", "HttpOnly", "SameSite=Lax"]
        if _secure_cookie(self):
            parts.append("Secure")
        return "; ".join(parts)

    def _clear_cookie_header(self, name: str) -> str:
        return f"{name}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"

    def _ip(self) -> str:
        return self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()

    def _read_body(self) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
        """Return (fields, files) where files[name] = (filename, bytes)."""
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")
        fields: dict[str, str] = {}
        files: dict[str, tuple[str, bytes]] = {}
        if "multipart/form-data" in ctype:
            m = re.search(r"boundary=(?P<b>[^;]+)", ctype)
            if not m:
                return fields, files
            boundary = m.group("b").strip().strip('"').encode()
            for part in raw.split(b"--" + boundary):
                if not part or part in (b"--\r\n", b"--"):
                    continue
                if part.startswith(b"\r\n"):
                    part = part[2:]
                if part.endswith(b"--\r\n"):
                    part = part[:-4]
                elif part.endswith(b"\r\n"):
                    part = part[:-2]
                if b"\r\n\r\n" not in part:
                    continue
                head, body = part.split(b"\r\n\r\n", 1)
                headers = head.decode("utf-8", "replace")
                name_m = re.search(r'name="([^"]+)"', headers)
                if not name_m:
                    continue
                name = name_m.group(1)
                fn_m = re.search(r'filename="([^"]*)"', headers)
                if fn_m is not None:
                    files[name] = (fn_m.group(1), body)
                else:
                    val = body.decode("utf-8", "replace")
                    if name in fields:
                        prev = fields[name]
                        fields[name] = (prev if isinstance(prev, list) else [prev]) + [val]
                    else:
                        fields[name] = val
            return fields, files
        qs = parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True)
        fields = {k: (v if len(v) > 1 else v[-1]) for k, v in qs.items()}
        return fields, files

    def _admin(self) -> int | None:
        return authlib.read_session(get_auth(), self._cookie("kdrama_session"))

    def _need_login(self):
        return self._redirect("/admin/login")

    def _csrf_ok(self, admin_id: int, fields: dict) -> bool:
        return authlib.check_csrf(get_auth(), admin_id, _field(fields, "csrf"))

    # ---------- routing ----------
    def do_HEAD(self):
        if self.path.split("?")[0] in {"/", "/healthz", "/health"}:
            self._health(head_only=True)
        else:
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/healthz", "/health"} or (path == "/" and "db" not in _CTX):
            return self._health()
        if not path.startswith("/admin"):
            return self._public(path)
        if path.startswith("/admin/static/"):
            return self._static(path[len("/admin/static/"):])
        if path == "/admin/login":
            return self._login_get()
        if path == "/admin/logout":
            return self._logout()
        admin = self._admin()
        if not admin:
            if path.startswith("/admin"):
                return self._need_login()
            return self._json(404, {"ok": False})
        routes = {
            "/admin": self._dashboard,
            "/admin/": self._dashboard,
            "/admin/api/stats": self._live_stats_api,
            "/admin/dramas": self._dramas,
            "/admin/add": self._add_get,
            "/admin/reports": self._reports,
            "/admin/requests": self._requests,
        }
        if path in routes:
            return routes[path](admin)
        m = re.fullmatch(r"/admin/drama/(\d+)/bulk", path)
        if m:
            return self._bulk_get(admin, int(m.group(1)))
        m = re.fullmatch(r"/admin/drama/(\d+)", path)
        if m:
            return self._drama_detail(admin, int(m.group(1)))
        self._html(404, H.layout("Not found", H.empty_state("info", "404 — Page not found", "That page doesn't exist.", "<a class='btn secondary' href='/admin'>Go to dashboard</a>"), admin_id=admin))

    def do_POST(self):
        path = urlparse(self.path).path
        fields, files = self._read_body()
        if path == "/admin/request-code":
            return self._request_code(fields)
        if path == "/admin/login":
            return self._login_post(fields)
        admin = self._admin()
        if not admin:
            return self._need_login()
        if not self._csrf_ok(admin, fields):
            return self._html(403, H.layout("CSRF", H.empty_state("shield", "Invalid CSRF token", "Your session form expired. Go back and try again.",
                                                           "<a class='btn secondary' href='/admin'>Back</a>"),
                                            admin_id=admin, flash_msg="CSRF failed — try again.", flash_kind="err"))
        handlers = {
            "/admin/add": lambda: self._add_post(admin, fields, files),
            "/admin/drama/edit": lambda: self._edit_post(admin, fields, files),
            "/admin/drama/addep": lambda: self._addep_post(admin, fields),
            "/admin/drama/bulk": lambda: self._bulk_post(admin, fields),
            "/admin/drama/newseason": lambda: self._newseason_post(admin, fields),
            "/admin/drama/complete": lambda: self._complete_post(admin, fields),
            "/admin/drama/delete": lambda: self._delete_post(admin, fields),
            "/admin/report/resolve": lambda: self._report_resolve(admin, fields),
            "/admin/request/reply": lambda: self._request_reply_post(admin, fields),
        }
        if path in handlers:
            try:
                return handlers[path]()
            finally:
                P.invalidate()  # public catalog reflects admin edits right away
        self._html(404, H.layout("Not found", H.empty_state("info", "404 — Page not found", "That page doesn't exist.", "<a class='btn secondary' href='/admin'>Go to dashboard</a>"), admin_id=admin))

    # ---------- public ----------
    def _health(self, head_only=False):
        body = json.dumps({"ok": True, "uptime_s": int(time.time() - STARTED)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _static(self, name: str):
        # only allow bare filenames in static/
        name = Path(name).name
        path = STATIC / name
        if not path.is_file():
            self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if path.suffix.lower() in {".png", ".webp", ".ico", ".jpg", ".jpeg", ".gif", ".svg"}:
            cache = "public, max-age=604800, immutable"
        else:
            cache = "public, max-age=86400"  # assets are cache-busted with ?v=
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    # ---------- public website ----------
    def _host(self) -> str:
        host = (self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or "").split(",")[0].strip()
        return host if re.fullmatch(r"[A-Za-z0-9.\-]+(:\d+)?", host or "") else ""

    def _send(self, code: int, data: bytes, ctype: str, cache: str, headers: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _page(self, code: int, html: str):
        self._send(code, html.encode(), "text/html; charset=utf-8",
                   "public, max-age=60" if code == 200 else "no-store",
                   {"Referrer-Policy": "strict-origin-when-cross-origin", "X-Frame-Options": "SAMEORIGIN"})

    def _public(self, path: str):
        q = parse_qs(urlparse(self.path).query)
        arg = lambda k: (q.get(k, [""])[0] or "").strip()
        host = self._host()
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        if path == "/favicon.ico":
            ico = STATIC / "favicon.ico"
            if ico.is_file():
                return self._send(200, ico.read_bytes(), "image/x-icon", "public, max-age=604800, immutable")
        if path in {"/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"}:
            icon = STATIC / "apple-touch-icon.png"
            if icon.is_file():
                return self._send(200, icon.read_bytes(), "image/png", "public, max-age=604800, immutable")
        if path == "/robots.txt":
            return self._send(200, b"User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /go/\nDisallow: /api/\n",
                              "text/plain; charset=utf-8", "public, max-age=86400")
        if "db" not in _CTX:
            return self._json(503, {"ok": False, "error": "starting"})
        try:
            if path == "/":
                return self._page(200, P.home(_CTX, arg("status"), host))
            if path == "/search":
                return self._page(200, P.search_page(_CTX, arg("q"), host))
            if path == "/api/search":
                if not P.rate_ok(self._ip()):
                    return self._send(429, P.json_bytes({"error": "Too many requests, slow down."}),
                                      "application/json", "no-store", {"Retry-After": "10"})
                return self._send(200, P.json_bytes(P.api_search(_CTX, arg("q")[:80])),
                                  "application/json; charset=utf-8", "public, max-age=30")
            m = re.fullmatch(r"/drama/(\d+)(?:-[a-z0-9-]*)?/?", path)
            if m:
                s_, ep_ = arg("s"), arg("ep")
                html = P.drama_page(_CTX, int(m.group(1)), int(s_) if s_.isdigit() else None,
                                    int(ep_) if ep_.isdigit() else None, host)
                if html:
                    return self._page(200, html)
            m = re.fullmatch(r"/go/(\d+)", path)
            if m:
                return self._go(m.group(1))
            m = re.fullmatch(r"/poster/(\d+)\.jpg", path)
            if m:
                return self._poster(int(m.group(1)))
        except Exception:
            log.exception("public page %s failed", path)
            return self._send(500, b"Something went wrong.", "text/plain; charset=utf-8", "no-store")
        self._page(404, P.not_found(_CTX, host))

    def _go(self, ref: str):
        if not P.rate_ok("go:" + self._ip(), n=60, window=60):
            return self._send(429, b"Too many requests", "text/plain", "no-store")
        url, info = P.resolve_link(_CTX, ref)
        if not url:
            return self._page(404, P.not_found(_CTX, self._host()))
        if info and info.get("log"):
            try:
                _CTX["db"].add_click(info["drama_id"], info["episode"], info["quality"], None, season=info["season"])
            except Exception:
                log.warning("click log failed", exc_info=True)
        self.send_response(302)
        self.send_header("Location", url)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _poster(self, did: int):
        """Stream a poster: Telegram -> client in small chunks. No image bytes are kept in memory."""
        if not P.posters_enabled(_CTX):
            return self._send(404, b"", "text/plain", "public, max-age=3600")
        d = P.catalog(_CTX)["by_id"].get(did)
        ref = d and d.get("poster_ref")
        if not ref:
            return self._send(404, b"", "text/plain", "public, max-age=300")
        cache = "public, max-age=604800, immutable"
        if P.is_http(ref):
            self.send_response(302); self.send_header("Location", ref)
            self.send_header("Cache-Control", cache); self.send_header("Content-Length", "0")
            return self.end_headers()
        etag = P.poster_etag(ref)
        inm = self.headers.get("If-None-Match") or ""
        if etag in [t.strip() for t in inm.split(",")] or inm.strip() == "*":
            self.send_response(304)
            self.send_header("ETag", etag); self.send_header("Cache-Control", cache)
            return self.end_headers()
        import urllib.error
        import urllib.request
        upstream = None
        for attempt in (1, 2):
            try:
                url = run_async(P.resolve_file_url(_CTX, ref), timeout=20)
            except Exception as e:
                log.info("poster %s: get_file failed (%s)", did, type(e).__name__)
                url = None
            if not url:
                return self._send(404, b"", "text/plain", "public, max-age=300")
            try:
                upstream = urllib.request.urlopen(url, timeout=15)
                break
            except urllib.error.HTTPError as e:
                P.forget_file_url(ref)  # stale download link: ask Telegram again once
                log.info("poster %s: upstream HTTP %s", did, e.code)
            except Exception as e:  # never log the URL (it contains the token)
                log.info("poster %s: upstream failed (%s)", did, type(e).__name__)
                P.forget_file_url(ref)
                break
        if upstream is None:
            return self._send(502, b"", "text/plain", "no-store")
        with upstream:
            length = upstream.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > P.POSTER_MAX_BYTES:
                return self._send(404, b"", "text/plain", "public, max-age=300")
            ctype = (upstream.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not ctype.startswith("image/"):
                ctype = "image/jpeg"  # Telegram serves photos as octet-stream
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            if length and length.isdigit():
                self.send_header("Content-Length", length)
            else:
                self.close_connection = True  # HTTP/1.0: end of body = connection close
            self.send_header("Cache-Control", cache)
            self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            sent = 0
            try:
                while True:
                    chunk = upstream.read(P.POSTER_CHUNK)
                    if not chunk:
                        break
                    sent += len(chunk)
                    if sent > P.POSTER_MAX_BYTES:
                        self.close_connection = True
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True
            except Exception as e:
                log.info("poster %s: stream aborted (%s)", did, type(e).__name__)
                self.close_connection = True

    # ---------- auth ----------
    def _login_get(self):
        if self._admin():
            return self._redirect("/admin")
        a = get_auth()
        self._html(200, H.login_page(has_password=bool(a.password)))

    def _logout(self):
        self._redirect("/admin/login", {"Set-Cookie": self._clear_cookie_header("kdrama_session")})

    def _request_code(self, fields: dict):
        a = get_auth()
        ip = self._ip()
        if authlib.rate_limited(a, ip):
            return self._html(429, H.login_page(has_password=bool(a.password),
                                                flash_msg="Too many attempts. Try again later.",
                                                telegram_id=fields.get("telegram_id", "")))
        authlib.record_attempt(a, ip)
        tid = (fields.get("telegram_id") or "").strip()
        if not tid.isdigit() or int(tid) not in a.admin_ids:
            return self._html(400, H.login_page(has_password=bool(a.password),
                                                flash_msg="That Telegram id is not an admin.",
                                                telegram_id=tid))
        admin_id = int(tid)
        code = authlib.issue_code(a, admin_id)
        bot = _CTX.get("bot")
        sent = False
        if bot is not None:
            try:
                run_async(bot.send_message(
                    chat_id=admin_id,
                    text=f"🔐 <b>kdrama_heaven admin login code</b>\n\n<code>{code}</code>\n\n"
                         f"Expires in 10 minutes. If you didn't request this, ignore it.",
                    parse_mode="HTML"))
                sent = True
            except Exception as e:
                log.warning("Could not DM login code to %s: %s", admin_id, e)
        # In tests without a bot, code is still issued (readable via auth state)
        msg = ("Code sent to your Telegram." if sent
               else "Code issued, but the bot couldn't DM you — open the bot and /start first.")
        # Never echo the code in the HTML response
        self._html(200, H.login_page(has_password=bool(a.password), flash_msg=msg, flash_kind="ok",
                                     telegram_id=tid))

    def _login_post(self, fields: dict):
        a = get_auth()
        ip = self._ip()
        if authlib.rate_limited(a, ip):
            return self._html(429, H.login_page(has_password=bool(a.password),
                                                flash_msg="Too many attempts. Try again later.",
                                                telegram_id=fields.get("telegram_id", "")))
        authlib.record_attempt(a, ip)
        tid = (fields.get("telegram_id") or "").strip()
        if not tid.isdigit() or int(tid) not in a.admin_ids:
            return self._html(403, H.login_page(has_password=bool(a.password),
                                                flash_msg="Not an admin id.",
                                                telegram_id=tid))
        admin_id = int(tid)
        mode = fields.get("mode") or "code"
        ok = False
        if mode == "password":
            ok = authlib.verify_password(a, fields.get("password", ""))
        else:
            ok = authlib.verify_code(a, admin_id, fields.get("code", ""))
        if not ok:
            return self._html(403, H.login_page(has_password=bool(a.password),
                                                flash_msg="Invalid or expired credentials.",
                                                telegram_id=tid))
        cookie = authlib.issue_session(a, admin_id)
        self._redirect("/admin", {"Set-Cookie": self._set_cookie_header(
            "kdrama_session", cookie, authlib.SESSION_TTL)})

    # ---------- pages ----------
    def _csrf(self, admin_id: int) -> str:
        return f'<input type="hidden" name="csrf" value="{H.e(authlib.csrf_token(get_auth(), admin_id))}">'

    def _live_stats_api(self, admin_id: int):
        self._json(200, _CTX["db"].cached_live_stats(_CTX["cfg"].tz))

    def _dashboard(self, admin_id: int):
        db = _CTX["db"]
        live = db.cached_live_stats(_CTX["cfg"].tz)
        open_n, open_rows = db.open_reports(5)
        recent, _ = db.list_dramas(limit=6, order="latest")
        recent_rows = "".join(
            f"<tr data-href='/admin/drama/{d.id}'><td><div class='cell-title'>{self._thumb(d)}"
            f"<div><a href='/admin/drama/{d.id}'><b>{H.e(d.title)}</b></a>"
            f"<div class='muted sm'>#{d.id}{' · ' + str(d.year) if d.year else ''}</div></div></div></td>"
            f"<td>{H.status_badge(d.status)}</td><td class='num'>{H.e(self._eps_text(d))}</td></tr>"
            for d in recent
        )
        recent_html = (
            f"<div class='table-wrap'><table class='table'><thead><tr><th>Title</th><th>Status</th>"
            f"<th>Episodes</th></tr></thead><tbody>{recent_rows}</tbody></table></div>"
            if recent else H.empty_state("film", "No dramas yet", "Add your first drama to get started.",
                                         f"<a class='btn' href='/admin/add'>{H.icon('plus')}Add drama</a>")
        )
        rep_items = []
        for r in open_rows:
            d = db.get_drama(r.drama_id)
            rep_items.append(
                f"<li><span class='li-ic'>{H.icon('flag')}</span><div><b>{H.e(d.title if d else '#'+str(r.drama_id))}</b>"
                f"<div class='muted sm'>{H.e(self._reason(r.reason))}{' · EP ' + str(r.episode) if r.episode else ''}</div></div>"
                f"<span class='pill warn'><i class='dot'></i>Open</span></li>")
        rep_html = (f"<ul class='mini-list'>{''.join(rep_items)}</ul>" if rep_items else
                    H.empty_state("check-circle", "All clear", "No open reports right now."))
        actions = (f"<a class='btn secondary' href='/admin/reports'>{H.icon('flag')}Reports</a>"
                   f"<a class='btn' href='/admin/add'>{H.icon('plus')}Add drama</a>")
        body = f"""
        {H.page_head("Dashboard", "Quick look at kdrama_heaven — your channel at a glance.", actions)}
        {H.live_stats_section(live)}
        <div class="grid-2">
          <div class="card">
            <div class="card-head between"><div class="card-head-l"><div class="card-ic">{H.icon('film')}</div>
              <div><h2>Recent dramas</h2><p class="muted">Latest additions and updates</p></div></div>
              <a class="btn ghost btn-sm" href="/admin/dramas">View all {H.icon('chevron')}</a></div>
            {recent_html}
          </div>
          <div class="card">
            <div class="card-head between"><div class="card-head-l"><div class="card-ic red">{H.icon('flag')}</div>
              <div><h2>Open reports</h2><p class="muted">{open_n} waiting</p></div></div>
              <a class="btn ghost btn-sm" href="/admin/reports">Open {H.icon('chevron')}</a></div>
            {rep_html}
          </div>
        </div>
        """
        q = parse_qs(urlparse(self.path).query)
        flash = q.get("ok", [None])[0] or q.get("err", [None])[0]
        kind = "ok" if "ok" in q else "err"
        self._html(200, H.layout("Dashboard", body, nav="dashboard", admin_id=admin_id,
                                 flash_msg=flash, flash_kind=kind))

    @staticmethod
    def _reason(code: str) -> str:
        from keyboards import REPORT_REASONS
        return REPORT_REASONS.get(code, code)

    @staticmethod
    def _thumb(d, cls: str = "thumb") -> str:
        letter = H.e((d.title or "?").strip()[:1].upper())
        src = P.clean_web_poster(getattr(d, "web_poster_url", None))
        if not src and d.poster and str(d.poster).startswith("http"):
            src = d.poster
        if src:
            # browser loads it directly; if it fails, swap in the letter tile
            return (f'<span class="{cls} ph thumb-wrap"><span>{letter}</span><img class="thumb-img" src="{H.e(src)}" alt="" '
                    f'loading="lazy" referrerpolicy="no-referrer" onerror="this.remove()"></span>')
        return f'<div class="{cls} ph">{letter}</div>'

    @staticmethod
    def _eps_text(d) -> str:
        if d.is_multi and d.current:
            eps = f"{len(d.seasons)} seasons · S{d.current.number} {len(d.current.episodes)}"
            if d.current.total_episodes:
                eps += f"/{d.current.total_episodes}"
            return eps
        eps = f"{len(d.episodes)}" + (f"/{d.total_episodes}" if d.total_episodes else "")
        return eps + " eps"

    def _dramas(self, admin_id: int):
        db = _CTX["db"]
        q = parse_qs(urlparse(self.path).query)
        status = (q.get("status", [""])[0] or "").title() or None
        if status not in {None, "Ongoing", "Completed"}:
            status = None
        search = (q.get("q", [""])[0] or "").strip()
        if search:
            dramas, total = db.search(search, limit=100)
        else:
            dramas, total = db.list_dramas(status=status, limit=100, order="latest")
        rows = []
        for d in dramas:
            eps = self._eps_text(d)
            cur = d.current
            have = len(cur.episodes) if cur else len(d.episodes)
            tot = (cur.total_episodes if cur else None) or d.total_episodes
            pct = min(100, int(have * 100 / tot)) if tot else 0
            prog = (f"<div class='prog'><i style='width:{pct}%'></i></div>" if tot else "")
            genres = ", ".join(g.strip() for g in (d.genres or "").split(",")[:3] if g.strip())
            rows.append(
                f"<tr data-href='/admin/drama/{d.id}'><td><div class='cell-title'>{self._thumb(d)}"
                f"<div><a href='/admin/drama/{d.id}'><b>{H.e(d.title)}</b></a>"
                f"<div class='muted sm'>#{d.id}{' · ' + str(d.year) if d.year else ''}"
                f"{' · ' + H.e(genres) if genres else ''}</div></div></div></td>"
                f"<td>{H.status_badge(d.status)}</td><td class='num'>{H.e(eps)}{prog}</td>"
                f"<td class='chev'>{H.icon('chevron')}</td></tr>"
            )

        def chip(val, label):
            on = (status or "") == val and not search
            href = "/admin/dramas" + (f"?status={val}" if val else "")
            return f'<a class="chip{" on" if on else ""}" href="{href}">{label}</a>'
        chips = chip("", "All") + chip("Ongoing", "Ongoing") + chip("Completed", "Completed")
        if rows:
            table = (f"<div class='table-wrap'><table class='table'><thead><tr><th>Title</th><th>Status</th>"
                     f"<th>Episodes</th><th></th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>")
        else:
            table = H.empty_state("film", "No dramas yet" if not search else "No matches",
                                  "Try a different search or filter." if search or status else
                                  "Add your first drama to get started.",
                                  f"<a class='btn' href='/admin/add'>{H.icon('plus')}Add drama</a>")
        body = f"""
        {H.page_head(f'Dramas <span class="count">{total}</span>', "Browse, search and manage every drama in the channel.",
                     f"<a class='btn' href='/admin/add'>{H.icon('plus')}Add drama</a>")}
        <div class="card">
          <form method="get" action="/admin/dramas" class="toolbar">
            <div class="input-ic grow">{H.icon('search')}<input name="q" value="{H.e(search)}" placeholder="Search title, genre, year" aria-label="Search"></div>
            <select name="status" aria-label="Status">
              <option value="">All statuses</option>
              <option value="Ongoing" {"selected" if status=="Ongoing" else ""}>Ongoing</option>
              <option value="Completed" {"selected" if status=="Completed" else ""}>Completed</option>
            </select>
            <button class="btn" type="submit">Filter</button>
          </form>
          <div class="chips">{chips}</div>
          {table}
        </div>"""
        qq = parse_qs(urlparse(self.path).query)
        flash = qq.get("ok", [None])[0] or qq.get("err", [None])[0]
        self._html(200, H.layout("Dramas", body, nav="dramas", admin_id=admin_id,
                                 flash_msg=flash, flash_kind="ok" if "ok" in qq else "err"))

    def _drama_detail(self, admin_id: int, drama_id: int):
        db = _CTX["db"]
        d = db.get_drama(drama_id)
        if not d or d.deleted:
            return self._html(404, H.layout("Missing", H.empty_state(
                "film", "Drama not found", "It may have been deleted.",
                f"<a class='btn secondary' href='/admin/dramas'>{H.icon('arrow-left')}Back to dramas</a>"),
                nav="dramas", admin_id=admin_id))
        csrf = self._csrf(admin_id)
        q = parse_qs(urlparse(self.path).query)
        form_err = q.get("addep_err", [None])[0] or ""
        seasons_html = ""
        for sea in d.seasons:
            heading = f"Season {sea.number}" if d.is_multi else "Episodes"
            eps_rows = "".join(
                f"<tr><td><span class='ep-n'>EP {e.number}</span></td>"
                f"<td><div class='pills'>{''.join(H.quality_pill(qq) for qq,_ in e.quality_groups())}</div></td>"
                f"<td class='num muted'>{e.link_count} links</td></tr>" for e in sea.episodes
            )
            table = (f"<div class='table-wrap'><table class='table compact'><thead><tr><th>Ep</th><th>Quality</th>"
                     f"<th>Links</th></tr></thead><tbody>{eps_rows}</tbody></table></div>" if eps_rows else
                     H.empty_state("tv", "No episodes yet", "Use Add episode above, or Bulk add for a range or a pasted list."))
            del_season = ("<form method='post' action='/admin/drama/delete'>" + csrf +
                          f"<input type='hidden' name='drama_id' value='{d.id}'><input type='hidden' name='season' value='{sea.number}'>"
                          f"<button class='btn danger-ghost btn-sm' data-confirm='Delete Season {sea.number}? This cannot be undone.' type='submit'>{H.icon('trash')}Delete season</button></form>"
                          if d.is_multi else "")
            seasons_html += f"""
            <div class="card" id="season-{sea.number}">
              <div class="card-head between"><div class="card-head-l"><div class="card-ic">{H.icon('layers')}</div>
                <div><h2>{heading} {H.status_badge(sea.status)}</h2>
                <p class="muted">{len(sea.episodes)}{('/'+str(sea.total_episodes)) if sea.total_episodes else ''} eps</p></div></div>
                <div class="actions">
                  <a class="btn ghost btn-sm" href="/admin/drama/{d.id}/bulk?season={sea.number}">{H.icon('layers')}Bulk add</a>
                  <form method="post" action="/admin/drama/complete">{csrf}
                    <input type="hidden" name="drama_id" value="{d.id}">
                    <input type="hidden" name="season" value="{sea.number}">
                    <button class="btn secondary btn-sm" type="submit" {"disabled" if sea.status=="Completed" else ""}>{H.icon('check')}Complete{" season" if d.is_multi else ""}</button>
                  </form>
                  {del_season}
                </div>
              </div>
              {table}
            </div>"""
        add_form = add_episode_form(d, csrf, err=form_err)

        poster = self._thumb(d, "poster")
        tags = "".join(H.pill(g.strip(), "neutral") for g in (d.genres or "").split(",") if g.strip())
        facts = []
        if d.year:
            facts.append(f"<span>{H.icon('calendar')}{d.year}</span>")
        if d.imdb:
            facts.append(f"<span>{H.icon('star')}IMDb {H.e(d.imdb)}</span>")
        if d.audio:
            facts.append(f"<span>{H.icon('info')}{H.e(d.audio)}</span>")
        if d.is_multi:
            facts.append(f"<span>{H.icon('layers')}{len(d.seasons)} seasons</span>")
        facts.append(f"<span>{H.icon('tv')}{H.e(self._eps_text(d))}</span>")
        if d.next_ep_date:
            facts.append(f"<span>{H.icon('clock')}Next: {H.e(d.next_ep_date)}{' ' + H.e(d.air_time) if d.air_time else ''}</span>")
        body = f"""
        <a class="back-link" href="/admin/dramas">{H.icon('arrow-left')}<span>All dramas</span></a>
        <div class="card hero">
          <div class="drama-head">
            {poster}
            <div class="meta">
              <div class="pills">{H.status_badge(d.status)} <span class="pill neutral">#{d.id}</span></div>
              <h1>{H.e(d.title)}</h1>
              <div class="facts">{''.join(facts)}</div>
              <div class="pills">{tags}</div>
              {"<p class='synopsis'>" + H.e(d.synopsis) + "</p>" if d.synopsis else ""}
            </div>
          </div>
          <div class="hero-actions">
            <form method="post" action="/admin/drama/newseason" class="inline-form">{csrf}
              <input type="hidden" name="drama_id" value="{d.id}">
              <input name="total" placeholder="S{len(d.seasons)+1} total eps" inputmode="numeric" class="w-sm">
              <button class="btn gold" type="submit">{H.icon('plus')}New season</button>
            </form>
            <form method="post" action="/admin/drama/complete">{csrf}
              <input type="hidden" name="drama_id" value="{d.id}">
              <button class="btn secondary" type="submit">{H.icon('check-circle')}Complete current season</button>
            </form>
            <form method="post" action="/admin/drama/delete" class="push-right">{csrf}
              <input type="hidden" name="drama_id" value="{d.id}">
              <button class="btn danger" data-confirm="Delete the WHOLE drama '{H.e(d.title)}'?" type="submit">{H.icon('trash')}Delete drama</button>
            </form>
          </div>
        </div>
        <details class="card collapsible">
          <summary class="card-head"><div class="card-ic">{H.icon('save')}</div>
            <div><h2>Edit details</h2><p class="muted">Title, status, metadata, schedule &amp; poster</p></div>
            <span class="sum-chev">{H.icon('chevron')}</span></summary>
          <form method="post" action="/admin/drama/edit" enctype="multipart/form-data" class="edit-form">
            {csrf}
            <input type="hidden" name="drama_id" value="{d.id}">
            <div class="fieldset"><div class="fs-title">Basics</div>
            <div class="row">
              <div class="span-2"><label>Title</label><input name="title" value="{H.e(d.title)}" required></div>
              <div><label>Year</label><input name="year" value="{d.year or ''}" inputmode="numeric"></div>
              <div><label>Status</label>
                <select name="status">
                  <option {"selected" if d.status=="Ongoing" else ""}>Ongoing</option>
                  <option {"selected" if d.status=="Completed" else ""}>Completed</option>
                </select>
              </div>
            </div>
            <div class="row">
              <div><label>Audio</label><input name="audio" value="{H.e(d.audio or '')}" placeholder="Korean, Eng Sub"></div>
              <div><label>IMDb</label><input name="imdb" value="{H.e(d.imdb or '')}" placeholder="8.6"></div>
              <div class="span-2"><label>Genres / tags</label><input name="genres" value="{H.e(d.genres)}"></div>
            </div>
            <label>Synopsis</label>
            <textarea name="synopsis" rows="4">{H.e(d.synopsis)}</textarea></div>
            <div class="fieldset"><div class="fs-title">Schedule</div>
            <div class="row">
              <div><label>Total eps (current season)</label>
                <input name="total" value="{(d.current.total_episodes if d.current else d.total_episodes) or ''}" inputmode="numeric"></div>
              <div><label>Next episode date</label>
                <input name="nextep" value="{H.e(d.next_ep_date or '')}" placeholder="2026-11-11"></div>
              <div><label>Air time (IST)</label>
                <input name="air_time" value="{H.e(d.air_time or '')}" placeholder="20:00"></div>
            </div></div>
            <div class="fieldset"><div class="fs-title">Poster</div>
            <div class="row">
              <div><label>Telegram poster URL</label><input name="poster_url" value="" placeholder="https://… or leave blank"></div>
              <div><label>Telegram poster file</label><input type="file" name="poster_file" accept="image/*"></div>
            </div>
            {web_poster_field(d.web_poster_url)}</div>
            <div class="form-foot"><button class="btn" type="submit">{H.icon('save')}Save changes</button></div>
          </form>
        </details>
        {add_form}
        {seasons_html}
        """
        flash = q.get("ok", [None])[0] or q.get("err", [None])[0]
        kind = "ok" if "ok" in q else "err"
        self._html(200, H.layout(d.title, body, nav="dramas", admin_id=admin_id,
                                 flash_msg=flash, flash_kind=kind))

    def _add_get(self, admin_id: int):
        csrf = self._csrf(admin_id)
        q = parse_qs(urlparse(self.path).query)
        err = q.get("err", [None])[0]
        links_err = q.get("links_err", [None])[0] or ""
        flash = err if err and not links_err else None
        body = f"""
        {H.page_head("Add drama", "Creates Season 1 and posts the channel card (same as /add), unless you create silently.", back="/admin/dramas")}
        <form method="post" action="/admin/add" enctype="multipart/form-data" id="add-drama-form" class="form-grid">
          {csrf}
          <div class="card">
            <div class="card-head"><div class="card-ic">{H.icon('film')}</div>
              <div><h2>Basics</h2><p class="muted">Title, year and season status</p></div></div>
            <label>Title</label><input name="title" required placeholder="e.g. Lovely Runner">
            <div class="row">
              <div><label>Year</label><input name="year" inputmode="numeric" placeholder="2026"></div>
              <div><label>Status</label>
                <select name="status"><option>Ongoing</option><option>Completed</option></select></div>
              <div><label>Total episodes</label>
                <input name="total" id="add-total" inputmode="numeric" placeholder="16"></div>
            </div>
          </div>
          <div class="card">
            <div class="card-head"><div class="card-ic blue">{H.icon('info')}</div>
              <div><h2>Details</h2><p class="muted">Shown on the channel card</p></div></div>
            <div class="row">
              <div><label>Audio</label><input name="audio" placeholder="Korean, Eng Sub"></div>
              <div><label>IMDb</label><input name="imdb" placeholder="8.6"></div>
              <div><label>Genres</label><input name="genres" placeholder="Romance, Fantasy"></div>
            </div>
            <label>Synopsis</label><textarea name="synopsis" rows="3" placeholder="Short plot summary…"></textarea>
          </div>
          <div class="card">
            <div class="card-head"><div class="card-ic pink">{H.icon('image')}</div>
              <div><h2>Poster</h2><p class="muted">Telegram poster for the channel card, plus an optional website-only poster</p></div></div>
            <div class="row">
              <div><label>Telegram poster URL</label><input name="poster_url" placeholder="https://…"></div>
              <div><label>Telegram poster file</label><input type="file" name="poster_file" accept="image/*"></div>
            </div>
            {web_poster_field()}
          </div>
          <div class="card">
            <div class="card-head"><div class="card-ic gold">{H.icon('link')}</div>
              <div><h2>Season 1 episodes <span class="muted">(optional)</span></h2>
              <p class="muted">Bulk-create episodes from link templates</p></div></div>
            {add_drama_links_section(err=links_err)}
          </div>
          <div class="sticky-foot add-foot">
            {silent_checkbox(checked=False, title="Create silently",
                             hint="Don't post the channel card, and don't notify anyone. The drama still appears on the website and in the bot.")}
            <span class="muted sm" id="add-post-hint">The channel card is posted as soon as you create.</span>
            <button class="btn lg" type="submit" id="add-submit">{H.icon('send')}Create &amp; post</button>
          </div>
        </form>"""
        self._html(200, H.layout("Add drama", body, nav="add", admin_id=admin_id,
                                 flash_msg=flash, flash_kind="err"))

    def _reports(self, admin_id: int):
        db = _CTX["db"]
        n, rows = db.open_reports()
        csrf = self._csrf(admin_id)
        items = []
        tones = {"m": "warn", "w": "violet", "b": "err", "o": "neutral"}
        for r in rows:
            d = db.get_drama(r.drama_id)
            title = d.title if d else f"#{r.drama_id}"
            sea = f"S{r.season} " if r.season and d and d.is_multi else ""
            ep = f"{sea}EP {r.episode}" if r.episode else (sea.strip() or "—")
            reason = self._reason(r.reason)
            who = f"@{r.username}" if r.username else str(r.user_id)
            when = r.created_at.strftime("%d %b %Y, %H:%M UTC") if r.created_at else ""
            link = f"<a href='/admin/drama/{d.id}'>{H.e(title)}</a>" if d else H.e(title)
            items.append(f"""
            <div class="card report">
              <div class="report-top">
                <div class="report-title">
                  <span class="report-id">#{r.id}</span>
                  <h3>{link}</h3>
                </div>
                <span class="pill warn"><i class="dot"></i>Open</span>
              </div>
              <div class="report-meta">
                {H.pill(reason, tones.get(r.reason, "neutral"))}
                <span class="pill neutral">{H.icon('tv')}{H.e(ep)}</span>
                <span class="muted sm">{H.icon('user')}{H.e(who)}</span>
                {f"<span class='muted sm'>{H.icon('clock')}{H.e(when)}</span>" if when else ""}
              </div>
              {"<blockquote class='note'>"+H.e(r.note)+"</blockquote>" if r.note else ""}
              <div class="actions">
                <form method="post" action="/admin/report/resolve">{csrf}
                  <input type="hidden" name="report_id" value="{r.id}">
                  <input type="hidden" name="action" value="fixed">
                  <button class="btn success btn-sm" type="submit">{H.icon('check')}Mark fixed</button></form>
                <form method="post" action="/admin/report/resolve">{csrf}
                  <input type="hidden" name="report_id" value="{r.id}">
                  <input type="hidden" name="action" value="dismissed">
                  <button class="btn secondary btn-sm" type="submit">{H.icon('x')}Dismiss</button></form>
              </div>
            </div>""")
        body = (H.page_head(f'Open reports <span class="count">{n}</span>',
                            "Viewer reports about missing, wrong or broken episodes. Marking fixed DMs the reporter.")
                + (f"<div class='report-list'>{''.join(items)}</div>" if items else
                   f"<div class='card'>{H.empty_state('check-circle', 'No open reports', 'Everything is working. ✦')}</div>"))
        q = parse_qs(urlparse(self.path).query)
        flash = q.get("ok", [None])[0] or q.get("err", [None])[0]
        self._html(200, H.layout("Reports", body, nav="reports", admin_id=admin_id, flash_msg=flash,
                                 flash_kind="ok" if "ok" in q else "err"))

    def _requests(self, admin_id: int):
        db = _CTX["db"]
        from services import REQUEST_QUICK_REPLIES
        q = parse_qs(urlparse(self.path).query)
        view = (q.get("status", ["open"])[0] or "open").lower()
        if view not in {"open", "closed", "all"}:
            view = "open"
        open_id = (q.get("open", [""])[0] or "").strip()
        rows = db.list_requests(limit=100, status=None if view == "all" else view)
        n_open = len(db.list_requests(limit=1000, status="open"))
        history = db.request_replies(r.id for r in rows)
        csrf = self._csrf(admin_id)

        def when(v):
            return v.strftime("%d %b %Y, %H:%M UTC") if hasattr(v, "strftime") else (v or "")

        chips_q = "".join(
            f'<button type="button" class="chip quick" data-fill="{H.e(t)}">{H.e(t)}</button>'
            for t in REQUEST_QUICK_REPLIES)
        cards = []
        for r in rows:
            who = f"@{r.username}" if r.username else str(r.user_id)
            st = r.status or "open"
            reps = history.get(r.id, [])
            pills = ""
            if reps:
                pills += H.pill(f"Replied{' ×' + str(len(reps)) if len(reps) > 1 else ''}", "ok", dot=True)
            if st == "closed":
                pills += H.pill("Closed", "neutral")
            elif not reps:
                pills += H.pill("Open", "warn", dot=True)
            hist = ""
            if reps:
                items = "".join(
                    f"<li><div class='rh-meta'>{H.icon('send')}<b>Admin {H.e(rr.admin_id or '')}</b>"
                    f"<span class='muted sm'>{H.e(when(rr.created_at))}</span></div>"
                    f"<div class='rh-text'>{H.e(rr.text)}</div></li>" for rr in reps)
                hist = f"<ul class='reply-history'>{items}</ul>"
            is_open = open_id == str(r.id)
            cards.append(f"""
            <div class="card req{' closed' if st == 'closed' else ''}" id="req-{r.id}">
              <div class="req-top">
                <div class="cell-title"><div class="avatar sm">{H.e(who[:2].lstrip('@')[:1].upper() or '?')}</div>
                  <div><b>{H.e(who)}</b> <span class="report-id">#{r.id}</span>
                  <div class="muted sm">{H.icon('clock')} {H.e(when(r.created_at))} · id <span class="mono">{r.user_id}</span></div></div></div>
                <div class="pills">{pills}</div>
              </div>
              <blockquote class="req-text">{H.e(r.text)}</blockquote>
              {hist}
              <details class="reply-box"{' open' if is_open else ''}>
                <summary class="btn secondary btn-sm">{H.icon('send')}{'Reply again' if reps else 'Reply'}</summary>
                <form method="post" action="/admin/request/reply" class="reply-form">{csrf}
                  <input type="hidden" name="request_id" value="{r.id}">
                  <input type="hidden" name="view" value="{H.e(view)}">
                  <label>Reply to {H.e(who)}</label>
                  <div class="chips quick-chips">{chips_q}</div>
                  <textarea name="text" rows="3" required maxlength="3500" placeholder="Write a reply… it's sent as a Telegram DM from the bot"></textarea>
                  <div class="reply-foot">
                    <label class="check"><input type="checkbox" name="close" value="1" checked><span>Mark as done / closed</span></label>
                    <button class="btn btn-sm" type="submit">{H.icon('send')}Send reply</button>
                  </div>
                </form>
              </details>
            </div>""")

        def chip(val, label):
            return f'<a class="chip{" on" if view == val else ""}" href="/admin/requests?status={val}">{label}</a>'
        chips = chip("open", f"Open · {n_open}") + chip("closed", "Closed") + chip("all", "All")
        listing = (f"<div class='req-list'>{''.join(cards)}</div>" if cards else
                   f"<div class='card'>{H.empty_state('inbox', 'No requests here', 'Requests from viewers will show up here.' if view != 'closed' else 'Nothing closed yet.')}</div>")
        body = f"""{H.page_head(f'Drama requests <span class="count">{n_open}</span>',
                                "What viewers asked the bot to add. Reply and they get a Telegram DM from the bot.")}
          <div class="chips">{chips}</div>
          {listing}"""
        flash = q.get("ok", [None])[0] or q.get("err", [None])[0]
        self._html(200, H.layout("Requests", body, nav="requests", admin_id=admin_id,
                                 flash_msg=flash, flash_kind="ok" if "ok" in q else "err"))

    def _request_reply_post(self, admin_id: int, fields: dict):
        from urllib.parse import quote
        from services import reply_to_request
        rid_s = _field(fields, "request_id").strip()
        view = _field(fields, "view", "open")
        view = view if view in {"open", "closed", "all"} else "open"
        if not rid_s.isdigit():
            return self._redirect(f"/admin/requests?status={view}&err=" + quote("Bad request id"))
        rid = int(rid_s)
        close = _field(fields, "close") in {"1", "on", "true", "yes"}
        try:
            ok, msg = run_async(reply_to_request(_CTX.get("bot"), _CTX["db"], rid, _field(fields, "text"),
                                                 admin_id=admin_id, close=close))
        except Exception as e:  # never 500 on a send problem
            log.warning("request reply failed: %s", e)
            ok, msg = False, f"Couldn't send the reply: {e}"
        if ok:
            return self._redirect(f"/admin/requests?status={view}&ok=" + quote(msg) + f"#req-{rid}")
        self._redirect(f"/admin/requests?status={view}&open={rid}&err=" + quote(msg) + f"#req-{rid}")

    # ---------- mutations ----------
    def _add_post(self, admin_id: int, fields: dict, files: dict):
        from urllib.parse import quote
        db, svc = _CTX["db"], _CTX["svc"]
        title = _field(fields, "title").strip()
        if not title:
            return self._redirect("/admin/add?err=" + quote("Title required"))
        kw = {
            "title": title,
            "synopsis": _field(fields, "synopsis").strip(),
            "genres": ", ".join(g.strip().title() for g in _field(fields, "genres").split(",") if g.strip()),
            "status": "Completed" if _field(fields, "status").title() == "Completed" else "Ongoing",
            "audio": _field(fields, "audio").strip() or None,
            "imdb": _field(fields, "imdb").strip() or None,
        }
        year = _field(fields, "year").strip()
        if year.isdigit():
            kw["year"] = int(year)
        total = _field(fields, "total").strip()
        if total.isdigit():
            kw["total_episodes"] = int(total)
        wp_raw = _field(fields, "web_poster_url").strip()
        if wp_raw and not P.clean_web_poster(wp_raw):
            return self._redirect("/admin/add?err=" + quote(WEB_POSTER_ERR))
        kw["web_poster_url"] = P.clean_web_poster(wp_raw)
        poster = _field(fields, "poster_url").strip() or None
        if files.get("poster_file") and files["poster_file"][1]:
            poster = self._upload_poster_bytes(files["poster_file"][0], files["poster_file"][1]) or poster
        if poster:
            try:
                kw.update(run_async(svc.persist_poster(poster)))
            except Exception:
                kw["poster"] = poster
        eps, err = expand_quality_range(fields, _field, _field_list)
        if err:
            return self._redirect("/admin/add?links_err=" + quote(err))
        d = db.add_drama(**kw, episodes=eps)
        if _flag(fields, "silent"):
            return self._redirect(f"/admin/drama/{d.id}?ok=" + quote(f"Created #{d.id} (not posted to the channel)"))
        try:
            run_async(svc.post_card(d))
        except Exception as e:
            log.warning("post_card failed: %s", e)
            return self._redirect(f"/admin/drama/{d.id}?err=Saved+but+channel+post+failed")
        self._redirect(f"/admin/drama/{d.id}?ok=Created+%23{d.id}")

    def _upload_poster_bytes(self, filename: str, data: bytes) -> str | None:
        """Send image bytes to Telegram and return a file_id usable as poster."""
        bot = _CTX.get("bot")
        if not bot or not data:
            return None
        from io import BytesIO
        bio = BytesIO(data)
        bio.name = filename or "poster.jpg"
        try:
            # Prefer storage channel, else first admin
            chat = getattr(_CTX["cfg"], "storage_channel_id", None) or _CTX["cfg"].channel_id
            msg = run_async(bot.send_photo(chat_id=chat, photo=bio))
            return msg.photo[-1].file_id
        except Exception as e:
            log.warning("poster upload failed: %s", e)
            return None

    def _edit_post(self, admin_id: int, fields: dict, files: dict):
        db, svc = _CTX["db"], _CTX["svc"]
        did = int(fields.get("drama_id") or 0)
        d = db.get_drama(did)
        if not d:
            return self._redirect("/admin/dramas?err=Missing")
        changes = {
            "title": (fields.get("title") or d.title).strip(),
            "synopsis": fields.get("synopsis") or "",
            "genres": ", ".join(g.strip().title() for g in (fields.get("genres") or "").split(",") if g.strip()),
            "audio": (fields.get("audio") or "").strip() or None,
        }
        year = (fields.get("year") or "").strip()
        changes["year"] = int(year) if year.isdigit() else None
        imdb = (fields.get("imdb") or "").strip()
        changes["imdb"] = imdb or None
        status = (fields.get("status") or d.status).title()
        if status in {"Ongoing", "Completed"}:
            if status == "Completed" and d.is_multi:
                for sea in d.seasons:
                    if sea.status != "Completed":
                        db.update_season(d.id, sea.number, status="Completed")
            elif status == "Ongoing" and d.current:
                db.update_season(d.id, d.current.number, status="Ongoing")
            else:
                changes["status"] = status
        nextep = (fields.get("nextep") or "").strip()
        air = (fields.get("air_time") or "").strip()
        if nextep in {"", "-"}:
            changes["next_ep_date"] = None
            changes["air_time"] = None
        else:
            changes["next_ep_date"] = nextep
            changes["air_time"] = air or None
        total = (fields.get("total") or "").strip()
        if total.isdigit() and d.current:
            db.update_season(d.id, d.current.number, total_episodes=int(total))
        if "web_poster_url" in fields:          # website-only poster; blank clears it
            wp_raw = (fields.get("web_poster_url") or "").strip()
            if wp_raw and not P.clean_web_poster(wp_raw):
                from urllib.parse import quote
                return self._redirect(f"/admin/drama/{d.id}?err=" + quote(WEB_POSTER_ERR))
            changes["web_poster_url"] = P.clean_web_poster(wp_raw)
        poster = (fields.get("poster_url") or "").strip()
        if files.get("poster_file") and files["poster_file"][1]:
            poster = self._upload_poster_bytes(files["poster_file"][0], files["poster_file"][1]) or poster
        if poster:
            try:
                run_async(svc.set_poster(d.id, poster))
            except Exception as e:
                log.warning("set_poster: %s", e)
                changes["poster"] = poster
        db.update_drama(d.id, **changes)
        try:
            run_async(svc.refresh_card(d.id))
        except Exception as e:
            log.warning("refresh_card: %s", e)
        self._redirect(f"/admin/drama/{d.id}?ok=Saved")

    def _addep_post(self, admin_id: int, fields: dict):
        from urllib.parse import quote
        db, svc = _CTX["db"], _CTX["svc"]
        did = int(_field(fields, "drama_id") or 0)
        d = db.get_drama(did)
        if not d:
            return self._redirect("/admin/dramas?err=Missing")
        season_s = _field(fields, "season")
        season = int(season_s) if season_s.isdigit() else (d.current.number if d.current else 1)
        sea = d.season(season)
        if not sea:
            return self._redirect(f"/admin/drama/{did}?addep_err=" + quote("Invalid season"))
        ep_s = _field(fields, "episode").strip()
        if not ep_s.isdigit() or not (1 <= int(ep_s) <= 9999):
            return self._redirect(f"/admin/drama/{did}?addep_err=" + quote("Episode number required (1–9999)"))
        ep_n = int(ep_s)
        links = []
        for qname in ("480p", "720p", "1080p"):
            for url in _field_list(fields, qname):
                if not url.lower().startswith(("http://", "https://")):
                    return self._redirect(f"/admin/drama/{did}?addep_err=" + quote(f"Invalid {qname} URL (need http/https)"))
                links.append((qname, url, "part"))
            for url in _field_list(fields, f"{qname}_mirror"):
                if not url.lower().startswith(("http://", "https://")):
                    return self._redirect(f"/admin/drama/{did}?addep_err=" + quote(f"Invalid {qname} mirror URL"))
                links.append((qname, url, "mirror"))
        if not links:
            return self._redirect(f"/admin/drama/{did}?addep_err=" + quote("At least one valid http(s) link is required"))
        silent = _flag(fields, "silent")
        run_async(svc.add_episodes(did, {ep_n: links}, season=season, silent=silent))
        note = " (silent)" if silent else ""
        self._redirect(f"/admin/drama/{did}?ok=" + quote(f"Episode {ep_n} added{note}") + f"#season-{season}")


    def _bulk_get(self, admin_id: int, drama_id: int, *, err: str = "", values: dict | None = None,
                  plan: dict | None = None, flash: str | None = None, flash_kind: str = "ok"):
        db = _CTX["db"]
        d = db.get_drama(drama_id)
        if not d or d.deleted:
            return self._html(404, H.layout("Missing", H.empty_state(
                "film", "Drama not found", "It may have been deleted.",
                f"<a class='btn secondary' href='/admin/dramas'>{H.icon('arrow-left')}Back to dramas</a>"),
                nav="dramas", admin_id=admin_id))
        values = dict(values or {})
        q = parse_qs(urlparse(self.path).query)
        if "season" not in values and q.get("season"):
            values["season"] = q.get("season", [""])[0]
        csrf = self._csrf(admin_id)
        form = bulk_add_form(d, csrf, err=err, values=values, plan=plan, field_list=_field_list)
        sub = f"Import a range or a pasted list into <b>{H.e(d.title)}</b> · #{d.id}."
        actions = (f"<a class='btn secondary' href='/admin/drama/{d.id}#add-episode'>"
                   f"{H.icon('plus')}Single episode</a>")
        body = f"""
        {H.page_head("Bulk add episodes", sub, back=f"/admin/drama/{d.id}", actions=actions)}
        <div class="card" id="bulk-add">
          <div class="card-head"><div class="card-ic gold">{H.icon('layers')}</div>
            <div><h2>Import into {H.e(d.title)}</h2>
            <p class="muted">Silent import is on by default, so nothing is posted to the channel or sent to followers.
              Episodes still show on the website and in the bot.</p></div></div>
          {form}
        </div>
        """
        self._html(200, H.layout(f"Bulk add · {d.title}", body, nav="dramas", admin_id=admin_id,
                                 flash_msg=flash, flash_kind=flash_kind))

    def _plan_bulk(self, fields: dict, d):
        """Parse the bulk form into a plan. Returns (plan, error_or_None)."""
        season_s = _field(fields, "season")
        season = int(season_s) if season_s.isdigit() else (d.current.number if d.current else 1)
        sea = d.season(season)
        if not sea:
            return None, "Invalid season"
        existing = {e.number for e in sea.episodes}
        mode = _field(fields, "mode", "range").strip().lower() or "range"
        issues: list[dict] = []
        if mode == "paste":
            eps, issues = parse_paste_lines(_field(fields, "paste"))
            errors = [i for i in issues if i.get("kind") == "error"]
            if not eps:
                msg = errors[0]["message"] if errors else "No valid episodes in the paste box"
                plan = {"add": {}, "skip": [], "overwrite": [], "issues": issues,
                        "season": season, "mode": mode,
                        "on_existing": _field(fields, "on_existing", "skip")}
                return plan, msg
        else:
            eps, err = expand_quality_range(fields, _field, _field_list)
            if err:
                return None, err
            if not eps:
                return None, "Add a from/to range and at least one http(s) link template"
        on_existing = _field(fields, "on_existing", "skip").strip().lower()
        if on_existing not in {"skip", "overwrite"}:
            on_existing = "skip"
        plan = plan_bulk(eps, existing, on_existing)
        plan.update(issues=issues, season=season, mode=mode, silent=_flag(fields, "silent"),
                    on_existing=on_existing)
        return plan, None

    def _bulk_values(self, fields: dict) -> dict:
        return {
            "season": _field(fields, "season"),
            "mode": _field(fields, "mode", "range"),
            "ep_from": _field(fields, "ep_from"),
            "ep_to": _field(fields, "ep_to"),
            "paste": _field(fields, "paste"),
            "on_existing": _field(fields, "on_existing", "skip"),
            "silent": "1" if _flag(fields, "silent") else "0",
            "quality_values": {k: _field_list(fields, k)
                               for q in ("480p", "720p", "1080p")
                               for k in (q, f"{q}_mirror")},
        }

    def _bulk_post(self, admin_id: int, fields: dict):
        from urllib.parse import quote
        db, svc = _CTX["db"], _CTX["svc"]
        did = int(_field(fields, "drama_id") or 0)
        d = db.get_drama(did)
        if not d or d.deleted:
            return self._redirect("/admin/dramas?err=Missing")
        action = _field(fields, "action", "preview").strip().lower() or "preview"
        plan, err = self._plan_bulk(fields, d)
        values = self._bulk_values(fields)
        if err:
            return self._bulk_get(admin_id, did, err=err, values=values, plan=plan)
        if action != "import":
            return self._bulk_get(admin_id, did, values=values, plan=plan)
        add = (plan or {}).get("add") or {}
        if not add:
            skipped = len((plan or {}).get("skip") or [])
            msg = (f"Nothing new to import — {skipped} episode"
                   f"{'s' if skipped != 1 else ''} already exist and were skipped."
                   if skipped else "Nothing to import")
            return self._bulk_get(admin_id, did, err=msg, values=values, plan=plan)
        silent = _flag(fields, "silent")
        season = plan["season"]
        run_async(svc.add_episodes(did, add, season=season, silent=silent))
        n_new = len(add) - len(plan.get("overwrite") or [])
        bits = [f"{n_new} added"] if n_new else []
        if plan.get("overwrite"):
            bits.append(f"{len(plan['overwrite'])} overwritten")
        if plan.get("skip"):
            bits.append(f"{len(plan['skip'])} skipped")
        note = " · silent" if silent else ""
        self._redirect(f"/admin/drama/{did}?ok=" + quote(f"Imported {', '.join(bits)}{note}")
                       + f"#season-{season}")

    def _newseason_post(self, admin_id: int, fields: dict):
        did = int(fields.get("drama_id") or 0)
        total = int(fields["total"]) if (fields.get("total") or "").isdigit() else None
        run_async(_CTX["svc"].new_season(did, total))
        self._redirect(f"/admin/drama/{did}?ok=New+season+started")

    def _complete_post(self, admin_id: int, fields: dict):
        did = int(fields.get("drama_id") or 0)
        season = int(fields["season"]) if (fields.get("season") or "").isdigit() else None
        run_async(_CTX["svc"].complete(did, season))
        self._redirect(f"/admin/drama/{did}?ok=Completed")

    def _delete_post(self, admin_id: int, fields: dict):
        db, svc = _CTX["db"], _CTX["svc"]
        did = int(fields.get("drama_id") or 0)
        season = int(fields["season"]) if (fields.get("season") or "").isdigit() else None
        if season is not None:
            ok = db.delete_season(did, season)
            if ok:
                try:
                    run_async(svc.refresh_card(did))
                except Exception:
                    pass
                return self._redirect(f"/admin/drama/{did}?ok=Season+deleted")
            return self._redirect(f"/admin/drama/{did}?err=Could+not+delete+season")
        run_async(svc.delete(did))
        self._redirect("/admin/dramas?ok=Drama+deleted")

    def _report_resolve(self, admin_id: int, fields: dict):
        db, svc = _CTX["db"], _CTX["svc"]
        rid = int(fields.get("report_id") or 0)
        action = fields.get("action")
        if action not in {"fixed", "dismissed"}:
            return self._redirect("/admin/reports?err=Bad+action")
        r = db.set_report_status(rid, action)
        if r and action == "fixed":
            d = db.get_drama(r.drama_id)
            title = d.title if d else f"#{r.drama_id}"
            try:
                run_async(_CTX["bot"].send_message(
                    r.user_id,
                    f"✅ Fixed! Your report #{r.id} for <b>{title}</b> was resolved. Thanks! 💜",
                    parse_mode="HTML"))
            except Exception as e:
                log.info("notify reporter failed: %s", e)
        self._redirect(f"/admin/reports?ok=Report+{action}")
