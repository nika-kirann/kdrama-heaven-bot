"""Tiny HTML helpers and page chrome for the admin UI."""
from __future__ import annotations

import json
import html as _h

ASSET_V = "10"

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
    "pencil": '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
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


def sparkline_svg(values, w: int = 120, h: int = 36, cls: str = "spark") -> str:
    """Tiny inline SVG area+line chart. values are non-negative ints."""
    vals = [max(0, int(v or 0)) for v in (values or [0])] or [0]
    mx = max(vals + [1])
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = 0 if n == 1 else i * w / (n - 1)
        y = h - 2 - (v / mx) * (h - 4)
        pts.append((x, y))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,{h} " + line + f" {w},{h}"
    return (f'<svg class="{e(cls)}" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'preserveAspectRatio="none" aria-hidden="true">'
            f'<polygon class="spark-fill" points="{area}"/>'
            f'<polyline class="spark-line" fill="none" points="{line}"/></svg>')


def bar_chart_svg(days: list, values: list, w: int = 640, h: int = 148) -> str:
    """30-day bar chart with first/mid/last date labels and hover titles."""
    vals = [max(0, int(v or 0)) for v in (values or [])]
    labels = list(days or [])
    n = max(len(vals), 1)
    if len(vals) < n:
        vals += [0] * (n - len(vals))
    if len(labels) < n:
        labels += [""] * (n - len(labels))
    mx = max(vals + [1])
    pad_t, pad_b, pad_x = 8, 22, 2
    inner_h = h - pad_t - pad_b
    gap = 2.0
    bw = max(1.4, (w - 2 * pad_x - gap * (n - 1)) / n)
    bars = []
    for i, (day, v) in enumerate(zip(labels, vals)):
        x = pad_x + i * (bw + gap)
        bh = (v / mx) * inner_h if mx else 0
        y = pad_t + inner_h - bh
        cls = "on" if v else "empty"
        if v:
            ht = max(bh, 1.5)
        else:
            y, ht, cls = pad_t + inner_h - 1.2, 1.2, "empty"
        bars.append(
            f'<rect class="{cls}" x="{x:.2f}" y="{y:.2f}" width="{bw:.2f}" height="{ht:.2f}" rx="1.4">'
            f'<title>{e(day)}: {v}</title></rect>'
        )

    def lab(i):
        if not labels[i]:
            return ""
        x = pad_x + i * (bw + gap) + bw / 2
        anchor = "start" if i == 0 else ("end" if i == n - 1 else "middle")
        return f'<text class="bar-lab" x="{x:.1f}" y="{h - 6}" text-anchor="{anchor}">{e(labels[i][5:])}</text>'

    mid = n // 2
    labels_svg = lab(0) + lab(mid) + lab(n - 1)
    return (f'<svg class="bars" viewBox="0 0 {w} {h}" width="100%" height="{h}" '
            f'preserveAspectRatio="none" role="img" aria-label="Activity last 30 days">'
            f'{"".join(bars)}{labels_svg}</svg>')


def _delta_html(n, period: str = "7d") -> str:
    n = int(n or 0)
    cls = "up" if n > 0 else ("down" if n < 0 else "zero")
    sign = f"+{n}" if n > 0 else str(n)
    return f'<div class="stat-delta {cls}">{sign} · {e(period)}</div>'


def live_stat_card(key: str, label: str, value, ic: str, tone: str, *,
                   delta=None, spark=None, sub: str | None = None) -> str:
    spark_html = (f'<div class="stat-spark" data-spark="{e(key)}">{sparkline_svg(spark)}</div>'
                  if spark is not None else "")
    sub_html = f'<div class="stat-sub" data-sub="{e(key)}">{e(sub)}</div>' if sub else ""
    delta_html = _delta_html(delta) if delta is not None else ""
    return (
        f'<div class="stat tone-{e(tone)}" data-stat="{e(key)}">'
        f'<div class="stat-top"><div class="stat-ic">{icon(ic)}</div>'
        f'<div class="stat-body"><div class="n" data-n="{e(key)}">{e(value)}</div>'
        f'<div class="l">{e(label)}</div>{sub_html}{delta_html}</div></div>'
        f'{spark_html}</div>'
    )


def _rank_list(rows: list, count_key: str, empty: str) -> str:
    if not rows:
        return f'<p class="muted sm empty-mini">{e(empty)}</p>'
    mx = max(int(r.get(count_key) or 0) for r in rows) or 1
    items = []
    for i, r in enumerate(rows, 1):
        n = int(r.get(count_key) or 0)
        pct = max(4, int(n * 100 / mx))
        title = e(r.get("title") or r.get("quality") or "—")
        hid = r.get("id")
        label = f'<a href="/admin/drama/{int(hid)}">{title}</a>' if hid else f'<span>{title}</span>'
        items.append(
            f'<li><span class="rank-i">{i}</span><div class="rank-body">{label}'
            f'<i class="rank-bar" style="width:{pct}%"></i></div>'
            f'<span class="rank-n">{n}</span></li>'
        )
    return f'<ol class="rank-list">{"".join(items)}</ol>'


def _upcoming_list(rows: list) -> str:
    if not rows:
        return '<p class="muted sm empty-mini">No upcoming episode dates set.</p>'
    items = []
    for r in rows:
        ep = f"S{r['season']} Ep {r['episode']}" if r.get("season") else f"Ep {r['episode']}"
        extra = f" · {e(r['time'])}" if r.get("time") else ""
        items.append(
            f'<li><a href="/admin/drama/{int(r["id"])}"><b>{e(r["title"])}</b></a>'
            f'<div class="muted sm">{e(ep)} · {e(r["date"])}{extra}</div></li>'
        )
    return f'<ul class="air-list">{"".join(items)}</ul>'


def _period_pills(deltas: dict, metric: str) -> str:
    bits = []
    for key, label in (("24h", "24h"), ("7d", "7d"), ("30d", "30d")):
        n = int((deltas.get(key) or {}).get(metric) or 0)
        sign = f"+{n}" if n > 0 else str(n)
        bits.append(f'<span class="period-pill" data-period="{key}"><b>{sign}</b> {label}</span>')
    return "".join(bits)


_ACTIVITY_METRICS = (
    ("clicks", "Clicks"),
    ("users", "New users"),
    ("episodes", "Episodes added"),
    ("requests", "Requests"),
    ("reports", "Reports"),
)


def live_stats_section(data: dict) -> str:
    """Full Live stats dashboard block. Server-rendered; JS refreshes from /admin/api/stats."""
    t, dlt, series = data["totals"], data["deltas"], data["series"]
    d7 = dlt.get("7d") or {}
    req_sub = f"{t['requests_open']} pending · {t['requests_replied']} replied"
    user_sub = f"{t['users_started']} started"
    if t["users_blocked"]:
        user_sub += f" · {t['users_blocked']} blocked"
    cards = "".join([
        live_stat_card("dramas", "Dramas", t["dramas"], "film", "purple",
                       delta=d7.get("dramas"), spark=series.get("dramas")),
        live_stat_card("ongoing", "Ongoing", t["ongoing"], "play", "violet"),
        live_stat_card("completed", "Completed", t["completed"], "check-circle", "green"),
        live_stat_card("episodes", "Episodes", t["episodes"], "tv", "pink",
                       delta=d7.get("episodes"), spark=series.get("episodes")),
        live_stat_card("users", "Users", t["users"], "user", "blue",
                       delta=d7.get("users"), spark=series.get("users"), sub=user_sub),
        live_stat_card("requests", "Requests", t["requests"], "inbox", "gold",
                       delta=d7.get("requests"), spark=series.get("requests"), sub=req_sub),
        live_stat_card("reports_open", "Open reports", t["reports_open"], "flag",
                       "red" if t["reports_open"] else "slate",
                       delta=d7.get("reports"), spark=series.get("reports")),
        live_stat_card("clicks", "Clicks", t["clicks"], "bolt", "cyan",
                       delta=d7.get("clicks"), spark=series.get("clicks")),
    ])
    default = "clicks"
    best = -1
    for key, _ in _ACTIVITY_METRICS:
        s = sum(series.get(key) or [])
        if s > best:
            best, default = s, key
    tabs = "".join(
        f'<button type="button" class="act-tab{" on" if key == default else ""}" data-metric="{key}">{label}</button>'
        for key, label in _ACTIVITY_METRICS
    )
    chart = bar_chart_svg(series["days"], series.get(default) or [])
    periods = _period_pills(dlt, default)
    payload = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    posts = t.get("posts_today", 0)
    sched = t.get("pending_schedules", 0)
    follows = t.get("follows", 0)
    extra = (f'<div class="live-extra muted sm">'
             f'<span>Posts today <b>{posts}</b></span>'
             f'<span>Follows <b>{follows}</b></span>'
             f'<span>Pending schedules <b>{sched}</b></span></div>')
    tz = e(data.get("tz") or "")
    return (
        f'<section class="live-stats" id="live-stats" data-default-metric="{e(default)}">'
        f'<div class="live-head"><div class="live-title">'
        f'<span class="live-pulse" title="Live" aria-hidden="true"><i></i></span>'
        f'<h2>Live stats</h2>'
        f'<span class="live-ago" data-live-updated>Updated just now</span></div>'
        f'<p class="muted sm">Totals, {tz} activity and what’s airing next. Refreshes every 30 seconds.</p></div>'
        f'<div class="stats">{cards}</div>'
        f'<div class="live-grid">'
        f'<div class="card" data-activity>'
        f'<div class="card-head between"><div class="card-head-l"><div class="card-ic">{icon("calendar")}</div>'
        f'<div><h2>Activity</h2><p class="muted">Last 30 days</p></div></div>'
        f'<div class="period-row" data-periods>{periods}</div></div>'
        f'<div class="act-tabs" role="tablist">{tabs}</div>'
        f'<div class="bar-wrap" data-chart>{chart}</div>{extra}</div>'
        f'<div class="card"><div class="card-head"><div class="card-ic gold">{icon("clock")}</div>'
        f'<div><h2>Upcoming episodes</h2><p class="muted">Next air date · full date, not a countdown</p></div></div>'
        f'<div data-upcoming>{_upcoming_list(data.get("upcoming") or [])}</div></div></div>'
        f'<div class="live-grid three">'
        f'<div class="card"><div class="card-head"><div class="card-ic pink">{icon("bolt")}</div>'
        f'<div><h2>Top clicked</h2><p class="muted">Last 7 days</p></div></div>'
        f'<div data-top-clicked>{_rank_list(data.get("top_clicked_7d") or [], "clicks", "No clicks in the last 7 days.")}</div></div>'
        f'<div class="card"><div class="card-head"><div class="card-ic">{icon("star")}</div>'
        f'<div><h2>Most followed</h2><p class="muted">All time</p></div></div>'
        f'<div data-top-followed>{_rank_list(data.get("top_followed") or [], "followers", "No followers yet.")}</div></div>'
        f'<div class="card"><div class="card-head"><div class="card-ic blue">{icon("tv")}</div>'
        f'<div><h2>Quality clicks</h2><p class="muted">Last 7 days</p></div></div>'
        f'<div data-top-qualities>{_rank_list(data.get("top_qualities_7d") or [], "clicks", "No quality clicks in the last 7 days.")}</div></div>'
        f'</div>'
        f'<script type="application/json" id="live-stats-data">{payload}</script>'
        f'</section>'
    )



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
<link rel="icon" href="/static/favicon-32.png?v={ASSET_V}" type="image/png" sizes="32x32">
<link rel="icon" href="/favicon.ico?v={ASSET_V}" sizes="any">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png?v={ASSET_V}" sizes="180x180">
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
    <picture>
      <source type="image/webp" srcset="/static/logo.webp?v={ASSET_V}">
      <img class="brand-logo" src="/static/logo.png?v={ASSET_V}" alt="Kdrama Heaven" width="349" height="140" decoding="async">
    </picture>
    <span class="brand-text"><small>Admin console</small></span>
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
    <div class="brand big">
      <picture>
        <source type="image/webp" srcset="/static/logo.webp?v={ASSET_V}">
        <img class="brand-logo" src="/static/logo.png?v={ASSET_V}" alt="Kdrama Heaven" width="349" height="140" decoding="async">
      </picture>
      <span class="brand-text"><small>Admin console</small></span></div>
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
