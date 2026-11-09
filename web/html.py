"""Tiny HTML helpers and page chrome for the admin UI."""
from __future__ import annotations

import html as _h
from urllib.parse import quote


def e(s) -> str:
    return _h.escape("" if s is None else str(s))


def flash(msg: str | None, kind: str = "ok") -> str:
    if not msg:
        return ""
    return f'<div class="flash {e(kind)}">{e(msg)}</div>'


def layout(title: str, body: str, *, nav: str = "dashboard", admin_id: int | None = None,
           flash_msg: str | None = None, flash_kind: str = "ok") -> str:
    links = [
        ("dashboard", "/admin", "Dashboard"),
        ("dramas", "/admin/dramas", "Dramas"),
        ("add", "/admin/add", "Add"),
        ("reports", "/admin/reports", "Reports"),
        ("requests", "/admin/requests", "Requests"),
    ]
    nav_html = "".join(
        f'<a class="{"active" if nav == k else ""}" href="{href}">{label}</a>'
        for k, href, label in links
    )
    who = f'<span class="muted">admin {admin_id}</span>' if admin_id else ""
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · kdrama_heaven</title>
<link rel="stylesheet" href="/admin/static/admin.css?v=2">
</head><body>
<header class="top">
  <div class="brand">✦ <span>kdrama_heaven</span> admin</div>
  <nav class="nav">{nav_html}
    <a href="/admin/logout">Logout</a>
  </nav>
</header>
<main class="wrap">
{flash(flash_msg, flash_kind)}
{body}
<p class="muted" style="margin-top:28px;font-size:12px">{who} · Telegram commands still work</p>
</main>
<script src="/admin/static/admin.js?v=2"></script>
</body></html>"""


def login_page(*, has_password: bool, flash_msg: str | None = None, flash_kind: str = "err",
               telegram_id: str = "") -> str:
    pwd_tab = ""
    if has_password:
        pwd_tab = f"""
        <div id="tab-password" hidden>
          <form method="post" action="/admin/login">
            <input type="hidden" name="mode" value="password">
            <label>Telegram user id</label>
            <input name="telegram_id" inputmode="numeric" required value="{e(telegram_id)}" placeholder="123456789">
            <label>Admin password</label>
            <input name="password" type="password" required autocomplete="current-password">
            <div class="actions"><button class="btn gold" type="submit">Sign in</button></div>
          </form>
        </div>"""
    tabs = ""
    if has_password:
        tabs = """<div class="tabs">
          <button type="button" class="active" data-tab="code">Telegram code</button>
          <button type="button" data-tab="password">Password</button>
        </div>"""
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Login · kdrama_heaven</title>
<link rel="stylesheet" href="/admin/static/admin.css?v=2">
</head><body>
<div class="login-wrap">
  <div class="card login-card">
    <h1>✦ Admin</h1>
    <p class="muted">Sign in with a one-time code DMed by the bot{', or your admin password' if has_password else ''}.</p>
    {flash(flash_msg, flash_kind)}
    {tabs}
    <div id="tab-code">
      <form method="post" action="/admin/request-code" style="margin-bottom:14px">
        <label>Telegram user id</label>
        <input name="telegram_id" inputmode="numeric" required value="{e(telegram_id)}" placeholder="123456789">
        <div class="actions"><button class="btn secondary" type="submit">Send code</button></div>
      </form>
      <form method="post" action="/admin/login">
        <input type="hidden" name="mode" value="code">
        <label>Telegram user id</label>
        <input name="telegram_id" inputmode="numeric" required value="{e(telegram_id)}" placeholder="123456789">
        <label>6-digit code</label>
        <input name="code" inputmode="numeric" pattern="\\d{{6}}" maxlength="6" required placeholder="••••••">
        <div class="actions"><button class="btn" type="submit">Sign in</button></div>
      </form>
    </div>
    {pwd_tab}
  </div>
</div>
<script src="/admin/static/admin.js?v=2"></script>
</body></html>"""


def status_badge(status: str) -> str:
    cls = "ok" if status == "Completed" else "on"
    icon = "✅" if status == "Completed" else "🔄"
    return f'<span class="badge {cls}">{icon} {e(status)}</span>'
