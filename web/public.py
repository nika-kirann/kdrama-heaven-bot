"""Public, read-only catalog website: /, /search, /drama/<id>, /api/search, /go/<link>, /poster/<id>.

Server-rendered HTML + vanilla JS. Nothing here exposes admin data (no users, reports or requests);
it shows exactly what the bot shows viewers: dramas, seasons, episodes and their quality links.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
from collections import OrderedDict, deque
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import quote, urlsplit, urlunsplit

from . import html as H

log = logging.getLogger(__name__)
ASSET_V = "1"
CACHE_TTL = 60.0
CATALOG_MAX = 3000       # dramas kept in the single cached snapshot (bounded memory)
SYNOPSIS_MAX = 1500      # chars kept per synopsis
DEFAULT_BOT = "kdrama_help_robot"
QUALITY_ORDER = {"480p": 0, "540p": 1, "720p": 2, "HD": 3, "1080p": 4, "4K": 5, "2160p": 5}

_lock = threading.Lock()
_cache: dict = {"key": None, "at": 0.0, "data": None}
_rate: dict[str, deque] = {}
RATE_N, RATE_WINDOW = 40, 10.0  # /api/search: 40 req / 10 s / IP


def invalidate() -> None:
    with _lock:
        _cache.update(key=None, at=0.0, data=None)


def rate_ok(ip: str, n: int | None = None, window: float | None = None) -> bool:
    n, window = n or RATE_N, window or RATE_WINDOW
    now = time.monotonic()
    with _lock:
        q = _rate.setdefault(ip, deque())
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= n:
            return False
        q.append(now)
        if len(_rate) > 5000:  # keep memory bounded
            for k in list(_rate)[:1000]:
                _rate.pop(k, None)
        return True


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(s: str) -> str:
    return norm(s).replace(" ", "-")[:60] or "drama"


def is_http(u: str | None) -> bool:
    return bool(u) and str(u).lower().startswith(("http://", "https://"))


# ---------------------------------------------------------------- catalog snapshot
def _to_naive(dt):
    return dt.replace(tzinfo=None) if isinstance(dt, datetime) and dt.tzinfo else dt


def _seasons(d) -> list[dict]:
    """Full season/episode/quality-link tree for ONE drama (built per request, never cached)."""
    seasons = []
    for sea in d.seasons or []:
        eps = []
        for e in sorted(sea.episodes, key=lambda x: x.number):
            groups = []
            for q, links in e.quality_groups():
                parts = [l for l in links if (l.kind or "part") != "mirror"]
                mirrors = [l for l in links if l.kind == "mirror"]
                groups.append({
                    "q": q,
                    "parts": [{"id": l.id, "url": l.url} for l in parts],
                    "mirrors": [{"id": l.id, "url": l.url} for l in mirrors],
                })
            groups.sort(key=lambda g: QUALITY_ORDER.get(g["q"], 9))
            eps.append({"n": e.number, "id": e.id, "groups": groups})
        seasons.append({"n": sea.number, "status": sea.status, "total": sea.total_episodes, "eps": eps})
    return seasons


def _build(ctx) -> dict:
    """Card-level index only (no episode links): small enough to keep as the 60s snapshot."""
    db, cfg = ctx["db"], ctx.get("cfg")
    from services import next_air_info
    tz = getattr(cfg, "tz", None) if cfg else None
    posters_on = posters_enabled(ctx)
    dramas, _ = db.list_dramas(limit=CATALOG_MAX, order="latest")
    items = []
    for d in dramas:
        latest_at, latest_label = None, ""
        for sea in d.seasons or []:
            for e in sea.episodes:
                ca = _to_naive(e.created_at)
                if ca and (latest_at is None or ca > latest_at):
                    latest_at = ca
                    latest_label = (f"S{sea.number} · EP {e.number}" if len(d.seasons) > 1 else f"EP {e.number}")
        cur = d.current
        have = len(cur.episodes) if cur else len(d.episodes)
        tot = (cur.total_episodes if cur else None) or d.total_episodes
        nxt = None
        try:
            info = next_air_info(d, tz) if tz else None
        except Exception:
            info = None
        if info:
            ep, when, has_time = info
            nxt = {"ep": ep, "date": f"{when:%B} {when.day}, {when.year}",
                   "time": (f"{when:%I:%M %p}".lstrip("0") + " IST") if has_time else ""}
        poster = None
        if not posters_on:
            pass
        elif is_http(d.poster):
            poster = d.poster
        elif d.poster:
            poster = f"/poster/{d.id}.jpg?v={abs(hash(d.poster)) % 10**8}"
        items.append({
            "id": d.id, "title": d.title, "year": d.year, "status": d.status, "genres": d.genre_list,
            "synopsis": (d.synopsis or "")[:SYNOPSIS_MAX], "imdb": d.imdb, "audio": d.audio or getattr(cfg, "default_audio", ""),
            "poster": poster, "poster_ref": d.poster if posters_on else None,
            "multi": len(d.seasons) > 1, "cur": cur.number if cur else 1,
            "have": have, "total": tot, "next": nxt,
            "latest_at": latest_at, "latest_label": latest_label,
            "updated": _to_naive(d.updated_at), "n": norm(d.title),
            "alt": [norm(a) for a in getattr(d, "alt_titles", None) or []],
        })
    by_id = {x["id"]: x for x in items}
    return {"items": items, "by_id": by_id, "built": time.time()}


def detail(ctx, did: int) -> dict | None:
    """Catalog card + its season/episode/link tree, loaded from the DB for this request only."""
    item = catalog(ctx)["by_id"].get(did)
    if not item:
        return None
    d = ctx["db"].get_drama(did)
    return {**item, "seasons": _seasons(d) if d else []}


def catalog(ctx) -> dict:
    key = id(ctx.get("db"))
    now = time.time()
    with _lock:
        if _cache["data"] is not None and _cache["key"] == key and now - _cache["at"] < CACHE_TTL:
            return _cache["data"]
    data = _build(ctx)
    with _lock:
        _cache.update(key=key, at=now, data=data)
    return data


def search(cat: dict, q: str, limit: int = 60) -> list[dict]:
    nq = norm(q)
    if not nq:
        return []
    toks = nq.split()
    scored = []
    for d in cat["items"]:
        names = [d["n"], *d["alt"]]
        best = 0.0
        for nm in names:
            if not nm:
                continue
            if nm == nq:
                s = 100
            elif nm.startswith(nq):
                s = 90
            elif f" {nq}" in f" {nm}":
                s = 80
            elif nq in nm:
                s = 70
            elif all(t in nm for t in toks):
                s = 60
            else:
                r = SequenceMatcher(None, nq, nm[:max(len(nq) + 4, 1)]).ratio()
                s = 40 * r if r >= 0.72 else 0
            best = max(best, s)
        if not best and d["year"] and nq == str(d["year"]):
            best = 30
        if best:
            scored.append((best, d["updated"] or datetime.min, d))
    scored.sort(key=lambda t: (-t[0], -(t[1].timestamp() if t[1] != datetime.min else 0)))  # newest first on ties
    return [d for _, _, d in scored[:limit]]


def bot_name(ctx) -> str:
    svc = ctx.get("svc")
    try:
        u = getattr(svc, "username", None) if svc else None
    except Exception:
        u = None
    return (u or DEFAULT_BOT).lstrip("@")


def channel_handle(ctx) -> str:
    cfg = ctx.get("cfg")
    try:
        hnd = cfg.brand_handle if cfg else "@kdrama_heaven"
    except Exception:
        hnd = "@kdrama_heaven"
    return (hnd or "@kdrama_heaven").lstrip("@")


def tme(bot: str, payload: str = "") -> str:
    return f"https://t.me/{bot}" + (f"?start={quote(payload)}" if payload else "")


# ---------------------------------------------------------------- rendering helpers
e = H.e


def progress(d) -> str:
    if d["total"]:
        return f"{d['have']}/{d['total']} EP"
    return f"{d['have']} EP" if d["have"] else "Coming soon"


def status_pill(status: str) -> str:
    cls = "done" if status == "Completed" else "live"
    return f'<span class="spill {cls}"><i></i>{e(status)}</span>'


def poster_img(d, cls: str = "", eager: bool = False) -> str:
    letter = e((d["title"] or "?").strip()[:1].upper())
    img = ""
    if d["poster"]:
        img = (f'<img src="{e(d["poster"])}" alt="{e(d["title"])} poster" '
               f'{"" if eager else "loading=" + chr(34) + "lazy" + chr(34) + " "}decoding="async" '
               f'onerror="this.remove()">')
    return f'<div class="pst {cls}"><span class="pst-ph">{letter}</span>{img}</div>'


def drama_url(d) -> str:
    return f"/drama/{d['id']}-{slug(d['title'])}"


def card(d, extra: str = "") -> str:
    meta = " · ".join(x for x in [str(d["year"]) if d["year"] else "", progress(d)] if x)
    return (f'<a class="card" href="{drama_url(d)}">{poster_img(d)}'
            f'<div class="card-badges">{status_pill(d["status"])}{extra}</div>'
            f'<div class="card-body"><h3>{e(d["title"])}</h3><p>{e(meta)}</p></div></a>')


ICONS = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "tg": '<path d="M21.5 4.5 2.9 11.7c-1 .4-1 1.8.1 2.1l4.6 1.4 1.8 5.5c.3.8 1.3 1 1.9.4l2.6-2.5 4.7 3.5c.7.5 1.7.1 1.9-.7l3-15.4c.2-1-.8-1.8-1.9-1.5Z"/><path d="m8 15 9.5-7.5"/>',
    "play": '<path d="M7 4.5v15l13-7.5Z"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "cal": '<rect x="3" y="4" width="18" height="18" rx="2.5"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "flag": '<path d="M4 21V4M4 4h12l-2 4 2 4H4"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.9 1.9 0 0 0 3.4 0"/>',
    "star": '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1Z"/>',
    "chev": '<path d="m9 18 6-6-6-6"/>',
    "dl": '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
    "mirror": '<path d="M17 1l4 4-4 4"/><path d="M3 11V9a4 4 0 0 1 4-4h14M7 23l-4-4 4-4"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
    "sparkle": '<path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4Z"/>',
}


def ic(name: str, cls: str = "") -> str:
    fill = name in {"play", "star"}
    return (f'<svg class="i {cls}" viewBox="0 0 24 24" fill="{"currentColor" if fill else "none"}" stroke="currentColor" '
            f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def search_box(q: str = "", big: bool = False, autofocus: bool = False) -> str:
    return (f'<form class="sbox{" big" if big else ""}" action="/search" method="get" role="search" autocomplete="off">'
            f'{ic("search")}<input type="search" name="q" value="{e(q)}" placeholder="Search dramas by title…" '
            f'aria-label="Search dramas" data-suggest{" autofocus" if autofocus else ""} maxlength="80">'
            f'<button type="submit" class="sbtn">Search</button>'
            f'<div class="suggest" role="listbox" hidden></div></form>')


def page(ctx, *, title: str, body: str, desc: str = "", image: str | None = None, path: str = "/",
         host: str = "", nav: str = "") -> str:
    bot, chan = bot_name(ctx), channel_handle(ctx)
    base = f"https://{host}" if host else ""
    full_title = f"{title} · kdrama_heaven" if title != "kdrama_heaven" else "kdrama_heaven — Watch K-dramas in 480p, 720p & 1080p"
    desc = desc or "Browse ongoing and completed Korean dramas, pick an episode and choose 480p, 720p or 1080p. New episodes every week on kdrama_heaven."
    img = image if (image and is_http(image)) else (base + image if image else "")
    og_img = (f'<meta property="og:image" content="{e(img)}"><meta name="twitter:image" content="{e(img)}">'
              if img else "")
    navl = lambda k, href, label: f'<a href="{href}" class="{"on" if nav == k else ""}">{label}</a>'
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(full_title)}</title>
<meta name="description" content="{e(desc[:300])}">
<meta name="theme-color" content="#0b0918">
<link rel="canonical" href="{e(base + path)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="kdrama_heaven">
<meta property="og:title" content="{e(full_title)}"><meta property="og:description" content="{e(desc[:300])}">
<meta property="og:url" content="{e(base + path)}">{og_img}
<meta name="twitter:card" content="{'summary_large_image' if img else 'summary'}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap">
<link rel="stylesheet" href="/static/public.css?v={ASSET_V}">
</head><body>
<header class="hdr" id="hdr">
  <div class="hdr-in">
    <a class="logo" href="/" aria-label="kdrama_heaven home"><span class="logo-mark">{ic("sparkle")}</span><span>kdrama<b>_heaven</b></span></a>
    <nav class="hnav">{navl("home", "/", "Home")}{navl("Ongoing", "/?status=ongoing#browse", "Ongoing")}{navl("Completed", "/?status=completed#browse", "Completed")}</nav>
    <div class="hdr-r">
      <button type="button" class="icon-b" id="search-open" aria-label="Search">{ic("search")}</button>
      <a class="tg-b" href="https://t.me/{e(chan)}" target="_blank" rel="noopener">{ic("tg")}<span>@{e(chan)}</span></a>
    </div>
  </div>
  <div class="hdr-search" id="hdr-search" hidden>{search_box()}<button type="button" class="icon-b" id="search-close" aria-label="Close search">{ic("x")}</button></div>
</header>
<main id="main">
{body}
</main>
<footer class="ftr">
  <div class="ftr-in">
    <div class="ftr-brand"><a class="logo" href="/"><span class="logo-mark">{ic("sparkle")}</span><span>kdrama<b>_heaven</b></span></a>
      <p>Ongoing &amp; completed K-dramas in 480p, 720p and 1080p. New episodes land on the channel first.</p></div>
    <div class="ftr-links">
      <a href="https://t.me/{e(chan)}" target="_blank" rel="noopener">{ic("tg")}Channel @{e(chan)}</a>
      <a href="{tme(bot)}" target="_blank" rel="noopener">{ic("sparkle")}Bot @{e(bot)}</a>
      <a href="{tme(bot, 'request')}" target="_blank" rel="noopener">{ic("plus")}Request a drama</a>
    </div>
  </div>
  <p class="ftr-note">kdrama_heaven lists links shared on our Telegram channel. © {datetime.now().year} kdrama_heaven</p>
</footer>
<script src="/static/public.js?v={ASSET_V}" defer></script>
</body></html>"""


def rail(title: str, cards: str, more: str = "", sub: str = "") -> str:
    if not cards:
        return ""
    more_html = f'<a class="more" href="{more}">See all {ic("chev")}</a>' if more else ""
    return (f'<section class="rail"><div class="sec-h"><div><h2>{e(title)}</h2>'
            f'{"<p>" + e(sub) + "</p>" if sub else ""}</div>{more_html}</div>'
            f'<div class="rail-track">{cards}</div></section>')


def empty(title: str, text: str, action: str = "") -> str:
    return (f'<div class="empty"><div class="empty-i">{ic("search")}</div><h3>{e(title)}</h3>'
            f'<p>{e(text)}</p>{action}</div>')


# ---------------------------------------------------------------- pages
def home(ctx, status: str = "", host: str = "") -> str:
    cat = catalog(ctx)
    items = cat["items"]
    bot = bot_name(ctx)
    ongoing = [d for d in items if d["status"] != "Completed"]
    completed = [d for d in items if d["status"] == "Completed"]
    latest = sorted([d for d in items if d["latest_at"]], key=lambda d: d["latest_at"], reverse=True)
    featured = (sorted(ongoing, key=lambda d: d["latest_at"] or datetime.min, reverse=True)[:5]
                or latest[:5] or items[:5])
    slides, dots = [], []
    for i, d in enumerate(featured):
        nxt = (f'<span class="hmeta-i">{ic("cal")}Next: EP {d["next"]["ep"]} · {e(d["next"]["date"])}</span>'
               if d["next"] else "")
        meta = "".join(f'<span class="hmeta-i">{x}</span>' for x in [
            e(str(d["year"])) if d["year"] else "", f'{ic("star")}{e(d["imdb"])}' if d["imdb"] else "",
            e(progress(d))] if x) + nxt
        bg = f'<div class="hero-bg" style="background-image:url({css_url(d["poster"])})"></div>' if d["poster"] else '<div class="hero-bg ph"></div>'
        slides.append(f"""
        <article class="slide{' on' if i == 0 else ''}" data-slide="{i}">
          {bg}<div class="hero-shade"></div>
          <div class="hero-in">
            <div class="hero-txt">
              <div class="hero-kick">{status_pill(d['status'])}<span class="kick">Featured</span></div>
              <h1>{e(d['title'])}</h1>
              <div class="hmeta">{meta}</div>
              <p class="hero-syn">{e(d['synopsis'][:240] + ('…' if len(d['synopsis']) > 240 else ''))}</p>
              <div class="hero-cta"><a class="btn pri" href="{drama_url(d)}#episodes">{ic('play')}Watch now</a>
                <a class="btn ghost" href="{drama_url(d)}">Details</a></div>
            </div>
            {poster_img(d, 'hero-pst', eager=(i == 0))}
          </div>
        </article>""")
        dots.append(f'<button type="button" class="dot{" on" if i == 0 else ""}" data-go="{i}" aria-label="Show {e(d["title"])}"></button>')
    hero = (f'<section class="hero" id="hero">{"".join(slides)}'
            f'<div class="hero-dots">{"".join(dots) if len(dots) > 1 else ""}</div></section>') if slides else ""
    latest_cards = "".join(card(d, f'<span class="new">{e(d["latest_label"])}</span>') for d in latest[:16])
    st = status.lower()
    grid_items = ongoing if st == "ongoing" else completed if st == "completed" else items
    tabs = "".join(
        f'<a class="tab{" on" if st == k else ""}" href="/{("?status=" + k) if k else ""}#browse">{lbl}'
        f'<span>{n}</span></a>'
        for k, lbl, n in (("", "All", len(items)), ("ongoing", "Ongoing", len(ongoing)),
                          ("completed", "Completed", len(completed))))
    grid = ("".join(card(d) for d in grid_items) if grid_items else "")
    body = f"""
    {hero}
    <section class="search-band"><div class="wrap">
      <h2>Find your next K-drama</h2>
      {search_box(big=True)}
    </div></section>
    <div class="wrap">
      {rail("Latest updates", latest_cards, sub="Freshly added episodes")}
      {rail("Ongoing", "".join(card(d) for d in ongoing[:16]), "/?status=ongoing#browse", "Airing now — new episodes every week")}
      {rail("Completed", "".join(card(d) for d in completed[:16]), "/?status=completed#browse", "Binge the whole series")}
      <section class="browse" id="browse">
        <div class="sec-h"><div><h2>Browse all</h2></div><div class="tabs">{tabs}</div></div>
        {f'<div class="grid">{grid}</div>' if grid else empty("Nothing here yet", "New dramas are added every week.")}
      </section>
      <section class="cta-band">
        <div><h2>Can't find a drama?</h2><p>Ask our bot and we'll try to add it. You'll get a DM when we reply.</p></div>
        <a class="btn pri" href="{tme(bot, 'request')}" target="_blank" rel="noopener">{ic("plus")}Request a drama</a>
      </section>
    </div>"""
    img = featured[0]["poster"] if featured else None
    return page(ctx, title="kdrama_heaven", body=body, image=img, path="/", host=host,
                nav={"ongoing": "Ongoing", "completed": "Completed"}.get(st, "home"))


def search_page(ctx, q: str, host: str = "") -> str:
    cat = catalog(ctx)
    bot = bot_name(ctx)
    q = (q or "").strip()[:80]
    if q:
        res = search(cat, q)
        head = f'<h1>Results for “{e(q)}”</h1><p class="muted">{len(res)} drama{"s" if len(res) != 1 else ""} found</p>'
        grid = (f'<div class="grid">{"".join(card(d) for d in res)}</div>' if res else
                empty("No dramas found", f"We couldn't find “{q}”. Check the spelling or request it on Telegram.",
                      f'<a class="btn pri" href="{tme(bot, "request")}" target="_blank" rel="noopener">{ic("plus")}Request it</a>'))
    else:
        head = '<h1>Search</h1><p class="muted">Type a title — suggestions appear as you type.</p>'
        res = sorted(cat["items"], key=lambda d: d["latest_at"] or datetime.min, reverse=True)[:18]
        grid = (f'<h2 class="sub-h">Recently updated</h2><div class="grid">{"".join(card(d) for d in res)}</div>'
                if res else "")
    body = f"""<div class="wrap page-top">
      <div class="search-head">{search_box(q, big=True, autofocus=not q)}</div>
      <div class="res-head">{head}</div>
      {grid}
    </div>"""
    return page(ctx, title=f"Search: {q}" if q else "Search", body=body, path="/search", host=host, nav="search")


def api_search(ctx, q: str) -> dict:
    cat = catalog(ctx)
    res = search(cat, q, limit=8) if q else []
    return {"q": q, "results": [{
        "id": d["id"], "title": d["title"], "year": d["year"], "status": d["status"],
        "poster": d["poster"], "url": drama_url(d), "eps": progress(d)} for d in res]}


def link_href(l: dict, d: dict, bot: str) -> str:
    """Tracked redirect for stored links; legacy rows without an id go straight to the target."""
    if l.get("id"):
        return f"/go/{l['id']}"
    return e(l["url"]) if is_http(l["url"]) else tme(bot, f"drama_{d['id']}")


def css_url(u: str) -> str:
    return e(re.sub(r'["\\()\s\']', lambda m: "%{:02X}".format(ord(m.group(0))), u or ""))


def ep_panel(d, sea, ep, bot: str, open_: bool) -> str:
    rows = []
    for g in ep["groups"]:
        btns = []
        parts, mirrors = g["parts"], g["mirrors"]
        for i, l in enumerate(parts):
            if i == 0:
                btns.append(f'<a class="qbtn main" href="{link_href(l, d, bot)}" '
                            f'target="_blank" rel="nofollow noopener">{ic("play")}<b>{e(g["q"])}</b>'
                            f'{"<small>Part 1</small>" if len(parts) > 1 else ""}</a>')
            else:
                btns.append(f'<a class="qbtn" href="{link_href(l, d, bot)}" '
                            f'target="_blank" rel="nofollow noopener">{ic("dl")}Part {i + 1}</a>')
        for i, l in enumerate(mirrors):
            btns.append(f'<a class="qbtn mir" href="{link_href(l, d, bot)}" '
                        f'target="_blank" rel="nofollow noopener">{ic("mirror")}Mirror{" " + str(i + 1) if len(mirrors) > 1 else ""}</a>')
        if not parts and mirrors:
            btns[0] = btns[0].replace('class="qbtn mir"', 'class="qbtn main"')
        tone = {"480p": "q480", "720p": "q720", "1080p": "q1080"}.get(g["q"], "qhd")
        rows.append(f'<div class="qrow {tone}"><span class="qtag">{e(g["q"])}</span><div class="qbtns">{"".join(btns)}</div></div>')
    label = f"Season {sea['n']} · Episode {ep['n']}" if d["multi"] else f"Episode {ep['n']}"
    body = "".join(rows) or '<p class="muted">Links for this episode are coming soon.</p>'
    return (f'<div class="ep-panel" id="ep-{sea["n"]}-{ep["n"]}" data-ep="{ep["n"]}"{"" if open_ else " hidden"}>'
            f'<div class="ep-panel-h"><h3>{e(label)}</h3><span class="muted">Choose a quality</span></div>'
            f'{body}'
            f'<p class="ep-help">Links open in a new tab. Broken? <a href="{tme(bot, "report_" + str(d["id"]))}" '
            f'target="_blank" rel="noopener">Report it</a>.</p></div>')


def drama_page(ctx, did: int, season: int | None = None, epn: int | None = None, host: str = "") -> str | None:
    d = detail(ctx, did)
    if not d:
        return None
    bot = bot_name(ctx)
    seas = d["seasons"]
    sea = next((s for s in seas if s["n"] == season), None) or next((s for s in seas if s["n"] == d["cur"]), None) \
        or (seas[-1] if seas else {"n": 1, "status": d["status"], "total": d["total"], "eps": []})
    eps = sea["eps"]
    sel = next((x for x in eps if x["n"] == epn), None) or (eps[-1] if eps else None)
    switch = ""
    if d["multi"]:
        switch = '<div class="seasons" role="tablist">' + "".join(
            f'<a class="tab{" on" if s["n"] == sea["n"] else ""}" href="{drama_url(d)}?s={s["n"]}#episodes">'
            f'Season {s["n"]}<span>{len(s["eps"])}{"/" + str(s["total"]) if s["total"] else ""}</span></a>'
            for s in seas) + "</div>"
    chips = "".join(
        f'<a class="epc{" on" if sel and x["n"] == sel["n"] else ""}" href="{drama_url(d)}?s={sea["n"]}&amp;ep={x["n"]}#episodes" '
        f'data-ep="{x["n"]}" data-target="ep-{sea["n"]}-{x["n"]}">{x["n"]}</a>' for x in eps)
    if sea["total"] and len(eps) < sea["total"] and sea["status"] != "Completed":
        chips += "".join(f'<span class="epc soon" title="Coming soon">{n}</span>'
                         for n in range(max((x["n"] for x in eps), default=0) + 1, sea["total"] + 1))
    panels = "".join(ep_panel(d, sea, x, bot, bool(sel and x["n"] == sel["n"])) for x in eps)
    eps_html = (f'<div class="ep-grid" id="ep-grid">{chips}</div>{panels}' if eps else
                empty("No episodes yet", "Follow the drama on Telegram and we'll DM you when episode 1 drops.",
                      f'<a class="btn pri" href="{tme(bot, "follow_" + str(d["id"]))}" target="_blank" rel="noopener">{ic("bell")}Notify me</a>'))
    facts = [("Status", status_pill(d["status"]))]
    if d["year"]:
        facts.append(("Year", e(d["year"])))
    facts.append(("Episodes", e(progress(d) + (f" · S{d['cur']}" if d["multi"] else ""))))
    if d["multi"]:
        facts.append(("Seasons", e(len(seas))))
    if d["imdb"]:
        facts.append(("IMDb", f'{ic("star", "gold")}{e(d["imdb"])}'))
    if d["audio"]:
        facts.append(("Audio", e(d["audio"])))
    quals = sorted({g["q"] for s in seas for x in s["eps"] for g in x["groups"]}, key=lambda q: QUALITY_ORDER.get(q, 9))
    if quals:
        facts.append(("Quality", " ".join(f'<span class="qchip">{e(q)}</span>' for q in quals)))
    facts_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in facts)
    genres = "".join(f'<span class="gchip">{e(g)}</span>' for g in d["genres"])
    nxt = ""
    if d["next"]:
        nxt = (f'<div class="next">{ic("cal")}<div><span>Next episode · EP {d["next"]["ep"]}</span>'
               f'<b>{e(d["next"]["date"])}</b>{"<small>" + e(d["next"]["time"]) + "</small>" if d["next"]["time"] else ""}</div></div>')
    bg = (f'<div class="dbg" style="background-image:url({css_url(d["poster"])})"></div>' if d["poster"]
          else '<div class="dbg ph"></div>')
    first = eps[0] if eps else None
    body = f"""
    <section class="dhero">{bg}<div class="dshade"></div>
      <div class="wrap dhero-in">
        {poster_img(d, 'dpst', eager=True)}
        <div class="dinfo">
          <a class="crumb" href="/">Home</a>
          <h1>{e(d['title'])}</h1>
          <div class="gchips">{genres}</div>
          <p class="syn">{e(d['synopsis'])}</p>
          {nxt}
          <div class="dcta">
            {f'<a class="btn pri" href="#episodes" data-jump="ep-{sea["n"]}-{first["n"]}">{ic("play")}Start EP 1</a>' if first and first["n"] == 1 else f'<a class="btn pri" href="#episodes">{ic("play")}Episodes</a>'}
            <a class="btn ghost" href="{tme(bot, 'drama_' + str(d['id']))}" target="_blank" rel="noopener">{ic("tg")}Open in Telegram</a>
            <a class="btn ghost" href="{tme(bot, 'follow_' + str(d['id']))}" target="_blank" rel="noopener">{ic("bell")}Notify me</a>
          </div>
        </div>
      </div>
    </section>
    <div class="wrap dbody">
      <section class="eps" id="episodes">
        <div class="sec-h"><div><h2>Episodes</h2><p>Pick an episode, then choose 480p, 720p or 1080p.</p></div></div>
        {switch}
        {eps_html}
      </section>
      <aside class="side">
        <div class="box"><h3>Details</h3><dl class="facts">{facts_html}</dl></div>
        <div class="box help">
          <h3>Need help?</h3>
          <a class="btn line" href="{tme(bot, 'report_' + str(d['id']))}" target="_blank" rel="noopener">{ic("flag")}Report a problem</a>
          <a class="btn line" href="{tme(bot, 'request')}" target="_blank" rel="noopener">{ic("plus")}Request a drama</a>
        </div>
      </aside>
    </div>"""
    desc = (d["synopsis"] or f"Watch {d['title']} episodes in 480p, 720p and 1080p on kdrama_heaven.")[:200]
    return page(ctx, title=d["title"], body=body, desc=desc, image=d["poster"], path=drama_url(d), host=host)


def not_found(ctx, host: str = "") -> str:
    body = f"""<div class="wrap nf">
      <div class="nf-code">404</div>
      <h1>This page went off-air</h1>
      <p class="muted">The drama or page you're looking for doesn't exist or was removed.</p>
      {search_box(big=True)}
      <a class="btn ghost" href="/">Back to home</a>
    </div>"""
    return page(ctx, title="Page not found", body=body, path="/404", host=host)


# ---------------------------------------------------------------- link + poster delivery
def resolve_link(ctx, link_ref: str) -> tuple[str | None, dict | None]:
    """'/go/<link_id>' -> (target_url, click_info). Non-http targets go to the bot deep link."""
    bot = bot_name(ctx)
    if not link_ref.isdigit():
        return None, None
    lid = int(link_ref)
    from db import EpisodeLink, Episode
    with ctx["db"].session() as ses:
        row = ses.get(EpisodeLink, lid)
        did = ses.get(Episode, row.episode_id).drama_id if row else None
    d = detail(ctx, did) if did else None
    for d in [d] if d else []:
        for s in d["seasons"]:
            for x in s["eps"]:
                for g in x["groups"]:
                    for kind, lst in (("part", g["parts"]), ("mirror", g["mirrors"])):
                        for i, l in enumerate(lst):
                            if l["id"] == lid:
                                url = l["url"] if is_http(l["url"]) else tme(bot, f"drama_{d['id']}")
                                first = kind == "part" and i == 0
                                return url, {"drama_id": d["id"], "episode": x["n"], "quality": g["q"],
                                             "season": s["n"], "log": first}
    return None, None


def favicon_svg() -> bytes:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0" stop-color="#8b5cf6"/><stop offset="1" stop-color="#db2777"/></linearGradient></defs>'
            '<rect width="64" height="64" rx="16" fill="url(#g)"/>'
            '<path d="M32 12l4.4 13.1L49 29l-12.6 4.4L32 47l-4.4-13.6L15 29l12.6-3.9Z" fill="#fff"/></svg>').encode()


# Posters are STREAMED, never held in memory: only file_id -> Telegram download URL is remembered
# (bounded, short TTL), and the image bytes flow upstream -> client in small chunks.
POSTER_CHUNK = 32 * 1024            # bytes per read/write
POSTER_MAX_BYTES = 8 * 1024 * 1024  # refuse anything bigger than a sane poster
_PATH_TTL = 30 * 60.0               # Telegram download links live >= 1 h
_PATH_MAX = 200
_paths: "OrderedDict[str, tuple[str, float]]" = OrderedDict()


def posters_enabled(ctx) -> bool:
    cfg = ctx.get("cfg")
    return bool(getattr(cfg, "public_posters", True)) if cfg is not None else True


def poster_etag(ref: str) -> str:
    return '"p-' + hashlib.sha1(str(ref).encode()).hexdigest()[:20] + '"'


def _bot(ctx):
    return ctx.get("bot") or getattr(ctx.get("svc"), "bot", None)


def cached_file_url(file_id: str) -> str | None:
    now = time.monotonic()
    with _lock:
        v = _paths.get(file_id)
        if v and v[1] > now:
            _paths.move_to_end(file_id)
            return v[0]
        _paths.pop(file_id, None)
    return None


def remember_file_url(file_id: str, url: str) -> None:
    with _lock:
        _paths[file_id] = (url, time.monotonic() + _PATH_TTL)
        _paths.move_to_end(file_id)
        while len(_paths) > _PATH_MAX:
            _paths.popitem(last=False)


def forget_file_url(file_id: str) -> None:
    with _lock:
        _paths.pop(file_id, None)


async def resolve_file_url(ctx, file_id: str) -> str | None:
    """Telegram file_id -> server-side download URL (contains the bot token: never send it to a client
    and never log it)."""
    url = cached_file_url(file_id)
    if url:
        return url
    bot = _bot(ctx)
    if bot is None:
        return None
    f = await bot.get_file(file_id)
    fp = getattr(f, "file_path", None)
    if not fp:
        return None
    if not is_http(fp):
        fp = f"{getattr(bot, 'base_file_url', '').rstrip('/')}/{fp.lstrip('/')}"
    sp = urlsplit(fp)
    url = urlunsplit((sp.scheme, sp.netloc, quote(sp.path), sp.query, ""))
    remember_file_url(file_id, url)
    return url


def json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").encode()
