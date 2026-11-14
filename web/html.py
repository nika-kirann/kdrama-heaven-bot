"""Tiny HTML helpers and page chrome for the admin UI."""
from __future__ import annotations

import html as _h

ASSET_V = "3"

_FONT = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap">')

# Inline SVG icon paths (24x24, stroke-based). No external icon CDN.
_ICONS = {
    "dashboard": '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    "film": '<rect x="2.5" y="3" width="19" height="18" rx="2.5"/><path d="M7 3v18M17 3v18M2.5 8h4.5M2.5 16h4.5M17 8h4.5M17 16h4.5M2.5 12h19"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "plus-circle": '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
    "flag": '<path d="M4 21V4M4 4h12l-2 4 2 4H4"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
    "inbox": '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1Z"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "play": '<circle cx="12" cy="12" r="9"/><path d="m10 8.5 5.5 3.5-5.5 3.5Z"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7l10-5Z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
    "tv": '<rect x="2" y="7" width="20" height="14" rx="2.5"/><path d="m17 2-5 5-5-5"/>',
    "send": '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "trash": '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8M7 3v5h8"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "sparkle": '<path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4Z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8Z"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2.5"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2.5"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    "star": '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1Z"/>',
    "chevron": '<path d="m9 18 6-6-6-6"/>',
    "arrow-left": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.7 12.3 9.8-9.8M17 6l3 3M14.5 8.5l2 2"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
    "bolt": '<path d="M13 2 3 14h9l-1 8 10-12h-9Z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
}


def e(s) -> str:
    return _h.escape("" if s is None else str(s))


def icon(name: str, cls: str = "") -> str:
    return (f'<svg class="ic {cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            f'{_ICONS.get(name, "")}</svg>')


def flash(msg: str | None, kind: str = "ok") -> str:
    if not msg:
        return ""
    ic = "check-circle" if kind == "ok" else "alert"
    return (f'<div class="flash toast {e(kind)}" role="status">{icon(ic)}'
            f'<span class="toast-msg">{e(msg)}</span>'
            f'<button type="button" class="toast-x" aria-label="Dismiss">{icon("x")}</button></div>')


def page_head(title: str, subtitle: str = "", actions: str = "", *, back: str = "") -> str:
    back_html = (f'<a class="back-link" href="{e(back)}">{icon("arrow-left")}<span>Back</span></a>'
                 if back else "")
    sub = f'<p class="page-sub">{subtitle}</p>' if subtitle else ""
    act = f'<div class="page-actions">{actions}</div>' if actions else ""
    return (f'<div class="page-head"><div class="page-head-text">{back_html}'
            f'<h1>{title}</h1>{sub}</div>{act}</div>')


def stat_card(label: str, value, ic: str, tone: str = "purple") -> str:
    return (f'<div class="stat tone-{tone}"><div class="stat-ic">{icon(ic)}</div>'
            f'<div class="stat-body"><div class="n">{e(value)}</div><div class="l">{e(label)}</div></div></div>')


def empty_state(ic: str, title: str, text: str = "", action: str = "") -> str:
    return (f'<div class="empty"><div class="empty-ic">{icon(ic)}</div><h3>{e(title)}</h3>'
            f'{"<p>" + text + "</p>" if text else ""}{action}</div>')


def pill(text: str, tone: str = "neutral", dot: bool = False) -> str:
    d = '<i class="dot"></i>' if dot else ""
    return f'<span class="pill {tone}">{d}{e(text)}</span>'


def _shell_head(title: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0c0a1a">
<title>{e(title)} · kdrama_heaven</title>
{_FONT}
<link rel="stylesheet" href="/admin/static/admin.css?v={ASSET_V}">
</head>"""


def layout(title: str, body: str, *, nav: str = "dashboard", admin_id: int | None = None,
           flash_msg: str | None = None, flash_kind: str = "ok") -> str:
    links = [
        ("dashboard", "/admin", "Dashboard", "dashboard"),
        ("dramas", "/admin/dramas", "Dramas", "film"),
        ("add", "/admin/add", "Add drama", "plus-circle"),
        ("reports", "/admin/reports", "Reports", "flag"),
        ("requests", "/admin/requests", "Requests", "inbox"),
    ]
    cur = ' aria-current="page"'
    nav_html = "".join(
        f'<a class="nav-link{" active" if nav == k else ""}" href="{href}"'
        f'{cur if nav == k else ""}>{icon(ic)}<span>{label}</span></a>'
        for k, href, label, ic in links
    )
    section = next((label for k, _, label, _ in links if k == nav), "")
    crumb = (f'<span>{e(section)}</span>' if section and section != title
             else "")
    initials = str(admin_id or "A")[-2:]
    who = (f'<div class="tb-user"><div class="avatar">{e(initials)}</div>'
           f'<div class="tb-user-text"><b>Admin</b><span>{e(admin_id)}</span></div></div>'
           if admin_id else "")
    return f"""{_shell_head(title)}<body class="app">
<aside class="sidebar" id="sidebar">
  <a class="brand" href="/admin">
    <span class="brand-mark">{icon("sparkle")}</span>
    <span class="brand-text"><b>kdrama_heaven</b><small>Admin console</small></span>
  </a>
  <div class="nav-label">Menu</div>
  <nav class="side-nav">{nav_html}</nav>
  <div class="side-foot">
    <div class="side-note">{icon("bolt")}<span>Telegram commands still work</span></div>
    <a class="nav-link logout" href="/admin/logout">{icon("logout")}<span>Logout</span></a>
  </div>
</aside>
<div class="scrim" id="scrim"></div>
<div class="main">
  <header class="topbar">
    <button type="button" class="icon-btn menu-btn" id="menu-btn" aria-label="Open menu">{icon("menu")}</button>
    <div class="tb-title"><span class="crumb">kdrama_heaven</span>{crumb}<span class="tb-page">{e(title)}</span></div>
    {who}
  </header>
  <div class="toasts">{flash(flash_msg, flash_kind)}</div>
  <main class="content">
{body}
  </main>
  <footer class="foot">kdrama_heaven admin · signed in as {e(admin_id) if admin_id else '—'}</footer>
</div>
<script src="/admin/static/admin.js?v={ASSET_V}"></script>
</body></html>"""


def login_page(*, has_password: bool, flash_msg: str | None = None, flash_kind: str = "err",
               telegram_id: str = "") -> str:
    pwd_tab = ""
    if has_password:
        pwd_tab = f"""
        <div id="tab-password" hidden>
          <form method="post" action="/admin/login" class="stack">
            <input type="hidden" name="mode" value="password">
            <div class="field"><label>Telegram user id</label>
            <div class="input-ic">{icon("user")}<input name="telegram_id" inputmode="numeric" required value="{e(telegram_id)}" placeholder="123456789"></div></div>
            <div class="field"><label>Admin password</label>
            <div class="input-ic">{icon("key")}<input name="password" type="password" required autocomplete="current-password" placeholder="••••••••"></div></div>
            <button class="btn block" type="submit">{icon("shield")}Sign in</button>
          </form>
        </div>"""
    tabs = ""
    if has_password:
        tabs = """<div class="tabs" role="tablist">
          <button type="button" class="active" data-tab="code">Telegram code</button>
          <button type="button" data-tab="password">Password</button>
        </div>"""
    inline_flash = ""
    if flash_msg:
        ic = "check-circle" if flash_kind == "ok" else "alert"
        inline_flash = f'<div class="flash {e(flash_kind)}">{icon(ic)}<span>{e(flash_msg)}</span></div>'
    return f"""{_shell_head("Login")}<body class="login-body">
<div class="login-wrap">
  <section class="login-hero">
    <div class="brand big"><span class="brand-mark">{icon("sparkle")}</span>
      <span class="brand-text"><b>kdrama_heaven</b><small>Admin console</small></span></div>
    <h2>Run your K-drama channel<br><span class="grad">from one place.</span></h2>
    <ul class="hero-points">
      <li>{icon("film")}<span>Add dramas, seasons &amp; episodes</span></li>
      <li>{icon("link")}<span>Bulk links with <code>{{ep}}</code> ranges</span></li>
      <li>{icon("flag")}<span>Resolve viewer reports fast</span></li>
    </ul>
  </section>
  <div class="login-card">
    <div class="login-head">
      <div class="login-ic">{icon("shield")}</div>
      <h1>Admin sign in</h1>
      <p class="muted">Sign in with a one-time code DMed by the bot{', or your admin password' if has_password else ''}.</p>
    </div>
    {inline_flash}
    {tabs}
    <div id="tab-code">
      <form method="post" action="/admin/request-code" class="stack step">
        <div class="step-label"><span class="step-n">1</span>Get a code on Telegram</div>
        <div class="field"><label>Telegram user id</label>
        <div class="input-ic">{icon("user")}<input name="telegram_id" inputmode="numeric" required value="{e(telegram_id)}" placeholder="123456789"></div></div>
        <button class="btn secondary block" type="submit">{icon("send")}Send code</button>
      </form>
      <form method="post" action="/admin/login" class="stack step">
        <div class="step-label"><span class="step-n">2</span>Enter the code</div>
        <input type="hidden" name="mode" value="code">
        <div class="field"><label>Telegram user id</label>
        <div class="input-ic">{icon("user")}<input name="telegram_id" inputmode="numeric" required value="{e(telegram_id)}" placeholder="123456789"></div></div>
        <div class="field"><label>6-digit code</label>
        <input class="code-input" name="code" inputmode="numeric" pattern="\\d{{6}}" maxlength="6" required placeholder="••••••" autocomplete="one-time-code"></div>
        <button class="btn block" type="submit">{icon("shield")}Sign in</button>
      </form>
    </div>
    {pwd_tab}
    <p class="login-foot muted">Only Telegram ids listed as bot admins can sign in.</p>
  </div>
</div>
<script src="/admin/static/admin.js?v={ASSET_V}"></script>
</body></html>"""


def status_badge(status: str) -> str:
    cls = "ok" if status == "Completed" else "on"
    return f'<span class="pill {cls}"><i class="dot"></i>{e(status)}</span>'


QUALITY_TONES = {"480p": "q480", "720p": "q720", "1080p": "q1080"}


def quality_pill(q: str) -> str:
    return f'<span class="pill q {QUALITY_TONES.get(q, "neutral")}">{e(q)}</span>'
