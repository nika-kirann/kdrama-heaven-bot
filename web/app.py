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
from .forms import add_drama_links_section, add_episode_form, expand_quality_range

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
        if path in {"/", "/healthz", "/health"}:
            return self._health()
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
            "/admin/dramas": self._dramas,
            "/admin/add": self._add_get,
            "/admin/reports": self._reports,
            "/admin/requests": self._requests,
        }
        if path in routes:
            return routes[path](admin)
        m = re.fullmatch(r"/admin/drama/(\d+)", path)
        if m:
            return self._drama_detail(admin, int(m.group(1)))
        self._html(404, H.layout("Not found", "<div class='card'><h1>404</h1></div>", admin_id=admin))

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
            return self._html(403, H.layout("CSRF", "<div class='card'><h1>Invalid CSRF token</h1>"
                                            "<p><a href='/admin'>Back</a></p></div>",
                                            admin_id=admin, flash_msg="CSRF failed — try again.", flash_kind="err"))
        handlers = {
            "/admin/add": lambda: self._add_post(admin, fields, files),
            "/admin/drama/edit": lambda: self._edit_post(admin, fields, files),
            "/admin/drama/addep": lambda: self._addep_post(admin, fields),
            "/admin/drama/newseason": lambda: self._newseason_post(admin, fields),
            "/admin/drama/complete": lambda: self._complete_post(admin, fields),
            "/admin/drama/delete": lambda: self._delete_post(admin, fields),
            "/admin/report/resolve": lambda: self._report_resolve(admin, fields),
        }
        if path in handlers:
            return handlers[path]()
        self._html(404, H.layout("Not found", "<div class='card'><h1>404</h1></div>", admin_id=admin))

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
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

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

    def _dashboard(self, admin_id: int):
        db, svc = _CTX["db"], _CTX["svc"]
        from utils import local_midnight_utc
        s = db.stats(local_midnight_utc(_CTX["cfg"].tz))
        open_r = db.open_reports(0)[0]
        body = f"""
        <div class="card">
          <h1>Dashboard</h1>
          <p class="muted">Quick look at kdrama_heaven.</p>
          <div class="grid">
            <div class="stat"><div class="n">{s['dramas']}</div><div class="l">Dramas</div></div>
            <div class="stat"><div class="n">{s['ongoing']}</div><div class="l">Ongoing</div></div>
            <div class="stat"><div class="n">{s['completed']}</div><div class="l">Completed</div></div>
            <div class="stat"><div class="n">{s.get('seasons', 0)}</div><div class="l">Seasons</div></div>
            <div class="stat"><div class="n">{s['episodes']}</div><div class="l">Episodes</div></div>
            <div class="stat"><div class="n">{open_r}</div><div class="l">Open reports</div></div>
            <div class="stat"><div class="n">{s['requests']}</div><div class="l">Requests</div></div>
            <div class="stat"><div class="n">{s['posts_today']}</div><div class="l">Posts today</div></div>
          </div>
          <div class="actions">
            <a class="btn" href="/admin/add">＋ Add drama</a>
            <a class="btn secondary" href="/admin/reports">⚠️ Reports</a>
            <a class="btn secondary" href="/admin/dramas">📚 Dramas</a>
          </div>
        </div>
        <div class="card"><h2>Live stats text</h2>
          <pre class="mono muted">{H.e(svc.stats_text())}</pre></div>
        """
        q = parse_qs(urlparse(self.path).query)
        flash = q.get("ok", [None])[0] or q.get("err", [None])[0]
        kind = "ok" if "ok" in q else "err"
        self._html(200, H.layout("Dashboard", body, nav="dashboard", admin_id=admin_id,
                                 flash_msg=flash, flash_kind=kind))

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
            if d.is_multi and d.current:
                eps = f"{len(d.seasons)} seasons · S{d.current.number} {len(d.current.episodes)}"
                if d.current.total_episodes:
                    eps += f"/{d.current.total_episodes}"
            else:
                eps = f"{len(d.episodes)}" + (f"/{d.total_episodes}" if d.total_episodes else "")
                eps += " eps"
            rows.append(
                f"<tr><td><a href='/admin/drama/{d.id}'><b>{H.e(d.title)}</b></a>"
                f"<div class='muted'>#{d.id}{' · ' + str(d.year) if d.year else ''}</div></td>"
                f"<td>{H.status_badge(d.status)}</td><td>{H.e(eps)}</td></tr>"
            )
        body = f"""
        <div class="card">
          <h1>Dramas <span class="muted">({total})</span></h1>
          <form method="get" action="/admin/dramas" class="row">
            <div><label>Search</label><input name="q" value="{H.e(search)}" placeholder="title, genre, year"></div>
            <div><label>Status</label>
              <select name="status">
                <option value="">All</option>
                <option value="Ongoing" {"selected" if status=="Ongoing" else ""}>Ongoing</option>
                <option value="Completed" {"selected" if status=="Completed" else ""}>Completed</option>
              </select>
            </div>
            <div><button class="btn" type="submit">Filter</button></div>
          </form>
          <table class="table"><thead><tr><th>Title</th><th>Status</th><th>Episodes</th></tr></thead>
          <tbody>{''.join(rows) or "<tr><td colspan=3 class='muted'>No dramas yet.</td></tr>"}</tbody></table>
        </div>"""
        self._html(200, H.layout("Dramas", body, nav="dramas", admin_id=admin_id))

    def _drama_detail(self, admin_id: int, drama_id: int):
        db = _CTX["db"]
        d = db.get_drama(drama_id)
        if not d or d.deleted:
            return self._html(404, H.layout("Missing", "<div class='card'><h1>Drama not found</h1></div>",
                                            admin_id=admin_id))
        csrf = self._csrf(admin_id)
        q = parse_qs(urlparse(self.path).query)
        form_err = q.get("addep_err", [None])[0] or ""
        seasons_html = ""
        for sea in d.seasons:
            heading = (f"{'✅' if sea.status=='Completed' else '🔄'} Season {sea.number}"
                       if d.is_multi else f"{'✅' if sea.status=='Completed' else '🔄'} Episodes")
            eps_rows = "".join(
                f"<tr><td>EP {e.number}</td><td class='mono'>{H.e(', '.join(qq for qq,_ in e.quality_groups()))}</td>"
                f"<td>{e.link_count} links</td></tr>" for e in sea.episodes
            ) or "<tr><td colspan=3 class='muted'>No episodes yet</td></tr>"
            seasons_html += f"""
            <div class="card" id="season-{sea.number}">
              <h3>{heading}
                <span class="muted">· {len(sea.episodes)}{('/'+str(sea.total_episodes)) if sea.total_episodes else ''} eps</span>
              </h3>
              <table class="table"><thead><tr><th>Ep</th><th>Quality</th><th>Links</th></tr></thead>
              <tbody>{eps_rows}</tbody></table>
              <div class="actions">
                <form method="post" action="/admin/drama/complete">{csrf}
                  <input type="hidden" name="drama_id" value="{d.id}">
                  <input type="hidden" name="season" value="{sea.number}">
                  <button class="btn secondary" type="submit" {"disabled" if sea.status=="Completed" else ""}>Complete{" season" if d.is_multi else ""}</button>
                </form>
                {"<form method='post' action='/admin/drama/delete'>"+csrf+f"<input type='hidden' name='drama_id' value='{d.id}'><input type='hidden' name='season' value='{sea.number}'><button class='btn danger' data-confirm='Delete Season {sea.number}? This cannot be undone.' type='submit'>Delete season</button></form>" if d.is_multi else ""}
              </div>
            </div>"""
        add_form = add_episode_form(d, csrf, err=form_err)

        poster = f'<img class="poster" src="{H.e(d.poster)}" alt="poster">' if d.poster and str(d.poster).startswith("http") else '<div class="poster"></div>'
        body = f"""
        <div class="card">
          <div class="drama-head">
            {poster}
            <div class="meta">
              <h1>{H.e(d.title)}</h1>
              <div>{H.status_badge(d.status)} <span class="muted">#{d.id}
                {" · " + str(len(d.seasons)) + " seasons" if d.is_multi else ""}</span></div>
              <p class="muted">{H.e(d.genres)}{" · " + str(d.year) if d.year else ""}{" · ⭐ " + H.e(d.imdb) if d.imdb else ""}</p>
            </div>
          </div>
          <form method="post" action="/admin/drama/edit" enctype="multipart/form-data">
            {csrf}
            <input type="hidden" name="drama_id" value="{d.id}">
            <div class="row">
              <div><label>Title</label><input name="title" value="{H.e(d.title)}" required></div>
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
              <div><label>Genres / tags</label><input name="genres" value="{H.e(d.genres)}"></div>
            </div>
            <label>Synopsis</label>
            <textarea name="synopsis" rows="4">{H.e(d.synopsis)}</textarea>
            <div class="row">
              <div><label>Total eps (current season)</label>
                <input name="total" value="{(d.current.total_episodes if d.current else d.total_episodes) or ''}" inputmode="numeric"></div>
              <div><label>Next episode date</label>
                <input name="nextep" value="{H.e(d.next_ep_date or '')}" placeholder="2026-11-11"></div>
              <div><label>Air time (IST)</label>
                <input name="air_time" value="{H.e(d.air_time or '')}" placeholder="20:00"></div>
            </div>
            <div class="row">
              <div><label>Poster URL</label><input name="poster_url" value="" placeholder="https://… or leave blank"></div>
              <div><label>Poster file</label><input type="file" name="poster_file" accept="image/*"></div>
            </div>
            <div class="actions"><button class="btn" type="submit">Save changes</button></div>
          </form>
          <div class="actions" style="margin-top:8px">
            <form method="post" action="/admin/drama/newseason">{csrf}
              <input type="hidden" name="drama_id" value="{d.id}">
              <input name="total" placeholder="S{len(d.seasons)+1} total eps" inputmode="numeric" style="width:140px">
              <button class="btn gold" type="submit">＋ New season</button>
            </form>
            <form method="post" action="/admin/drama/complete">{csrf}
              <input type="hidden" name="drama_id" value="{d.id}">
              <button class="btn secondary" type="submit">Complete current season</button>
            </form>
            <form method="post" action="/admin/drama/delete">{csrf}
              <input type="hidden" name="drama_id" value="{d.id}">
              <button class="btn danger" data-confirm="Delete the WHOLE drama '{H.e(d.title)}'?" type="submit">Delete drama</button>
            </form>
          </div>
        </div>
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
        <div class="card">
          <h1>Add drama</h1>
          <p class="muted">Creates Season 1 and posts the channel card (same as /add).</p>
          <form method="post" action="/admin/add" enctype="multipart/form-data" id="add-drama-form">
            {csrf}
            <label>Title</label><input name="title" required>
            <div class="row">
              <div><label>Year</label><input name="year" inputmode="numeric" placeholder="2026"></div>
              <div><label>Status</label>
                <select name="status"><option>Ongoing</option><option>Completed</option></select></div>
              <div><label>Total episodes</label>
                <input name="total" id="add-total" inputmode="numeric" placeholder="16"></div>
            </div>
            <div class="row">
              <div><label>Audio</label><input name="audio" placeholder="Korean, Eng Sub"></div>
              <div><label>IMDb</label><input name="imdb" placeholder="8.6"></div>
              <div><label>Genres</label><input name="genres" placeholder="Romance, Fantasy"></div>
            </div>
            <label>Synopsis</label><textarea name="synopsis" rows="3"></textarea>
            <div class="row">
              <div><label>Poster URL</label><input name="poster_url" placeholder="https://…"></div>
              <div><label>Poster file</label><input type="file" name="poster_file" accept="image/*"></div>
            </div>
            {add_drama_links_section(err=links_err)}
            <div class="actions"><button class="btn" type="submit">Create &amp; post</button></div>
          </form>
        </div>"""
        self._html(200, H.layout("Add drama", body, nav="add", admin_id=admin_id,
                                 flash_msg=flash, flash_kind="err"))

    def _reports(self, admin_id: int):
        db = _CTX["db"]
        n, rows = db.open_reports()
        csrf = self._csrf(admin_id)
        items = []
        for r in rows:
            d = db.get_drama(r.drama_id)
            title = d.title if d else f"#{r.drama_id}"
            sea = f"S{r.season} " if r.season and d and d.is_multi else ""
            ep = f"{sea}EP {r.episode}" if r.episode else (sea.strip() or "—")
            from keyboards import REPORT_REASONS
            reason = REPORT_REASONS.get(r.reason, r.reason)
            who = f"@{r.username}" if r.username else str(r.user_id)
            items.append(f"""
            <div class="card">
              <h3>#{r.id} · {H.e(title)}</h3>
              <p><b>{H.e(ep)}</b> · {H.e(reason)} · from {H.e(who)}</p>
              {"<p class='muted'>"+H.e(r.note)+"</p>" if r.note else ""}
              <div class="actions">
                <form method="post" action="/admin/report/resolve">{csrf}
                  <input type="hidden" name="report_id" value="{r.id}">
                  <input type="hidden" name="action" value="fixed">
                  <button class="btn" type="submit">✅ Mark fixed</button></form>
                <form method="post" action="/admin/report/resolve">{csrf}
                  <input type="hidden" name="report_id" value="{r.id}">
                  <input type="hidden" name="action" value="dismissed">
                  <button class="btn secondary" type="submit">🗑 Dismiss</button></form>
              </div>
            </div>""")
        body = f"<div class='card'><h1>Open reports ({n})</h1></div>" + ("".join(items) or
               "<div class='card muted'>No open reports. ✦</div>")
        q = parse_qs(urlparse(self.path).query)
        flash = q.get("ok", [None])[0]
        self._html(200, H.layout("Reports", body, nav="reports", admin_id=admin_id, flash_msg=flash))

    def _requests(self, admin_id: int):
        db = _CTX["db"]
        rows = db.list_requests()
        items = "".join(
            f"<tr><td>#{r.id}</td><td>{H.e('@'+r.username if r.username else r.user_id)}</td>"
            f"<td>{H.e(r.text)}</td><td class='muted'>{H.e(r.created_at)}</td></tr>"
            for r in rows
        ) or "<tr><td colspan=4 class='muted'>No requests yet.</td></tr>"
        body = f"""<div class="card"><h1>Drama requests</h1>
          <table class="table"><thead><tr><th>#</th><th>From</th><th>Text</th><th>When</th></tr></thead>
          <tbody>{items}</tbody></table></div>"""
        self._html(200, H.layout("Requests", body, nav="requests", admin_id=admin_id))

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
        try:
            run_async(svc.post_card(d))
        except Exception as e:
            log.warning("post_card failed: %s", e)
            return self._redirect(f"/admin/drama/{d.id}?err=Saved+but+channel+post+failed")
        self._redirect(f"/admin/drama/{d.id}?ok=Created+#{d.id}")

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
        run_async(svc.add_episodes(did, {ep_n: links}, season=season))
        self._redirect(f"/admin/drama/{did}?ok=" + quote(f"Episode {ep_n} added") + f"#season-{season}")

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
