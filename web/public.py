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
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import quote, urlsplit, urlunsplit

from . import html as H

log = logging.getLogger(__name__)
ASSET_V = "11"
CACHE_TTL = 60.0
SITEMAP_TTL = 3600.0
CATALOG_MAX = 3000       # dramas kept in the single cached snapshot (bounded memory)
SYNOPSIS_MAX = 1500      # chars kept per synopsis
DEFAULT_BOT = "kdrama_help_robot"
QUALITY_ORDER = {"480p": 0, "540p": 1, "720p": 2, "HD": 3, "1080p": 4, "4K": 5, "2160p": 5}
SHARE_IMAGE = f"/static/og-default.jpg?v={ASSET_V}"
SITE_NAME = "Kdrama Heaven"
# Hosts that are the app origin (or local), not the public domain. OG URLs use PUBLIC_BASE_URL then.
_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_ORIGIN_SUFFIXES = (".koyeb.app", ".mistral.run")

_lock = threading.Lock()
_cache: dict = {"key": None, "at": 0.0, "data": None}
_sitemap: dict = {"key": None, "at": 0.0, "body": None}
_rate: dict[str, deque] = {}
RATE_N, RATE_WINDOW = 40, 10.0  # /api/search: 40 req / 10 s / IP


def invalidate() -> None:
    with _lock:
        _cache.update(key=None, at=0.0, data=None)
        _sitemap.update(key=None, at=0.0, body=None)


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


def public_origin(ctx, host: str = "") -> str:
    """Absolute origin for canonical / Open Graph URLs.

    A public Host or X-Forwarded-Host (kdramaheaven.in, www) is used as-is so the
    Cloudflare Worker proxy keeps the address bar host in share previews. Localhost
    and origin hosts (koyeb.app, mistral.run) fall back to PUBLIC_BASE_URL, which
    defaults to https://kdramaheaven.in.
    """
    cfg = ctx.get("cfg") if ctx else None
    env = (getattr(cfg, "public_base_url", None) or "https://kdramaheaven.in").strip().rstrip("/")
    if not env:
        env = "https://kdramaheaven.in"
    host = (host or "").split(",")[0].strip()
    if not host:
        return env
    raw = host.split("/")[0]
    if raw.startswith("["):
        hostname = raw[1:].split("]")[0].lower()
    else:
        hostname = raw.split(":")[0].lower()
    if hostname in _ORIGIN_HOSTS or any(hostname.endswith(s) for s in _ORIGIN_SUFFIXES):
        return env
    return "https://" + raw


def canonical_origin(ctx) -> str:
    """Always the configured public base (default https://kdramaheaven.in).

    Canonical tags, the sitemap, robots.txt and JSON-LD use this so koyeb,
    mistral and www hosts all point at the apex domain.
    """
    cfg = ctx.get("cfg") if ctx else None
    env = (getattr(cfg, "public_base_url", None) or "https://kdramaheaven.in").strip().rstrip("/")
    return env or "https://kdramaheaven.in"


from utils import clean_web_poster  # noqa: E402  (website-only poster URL validation)


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
    """Card-level index only (no episode links): small enough to keep as the 60s snapshot.
    Built from plain SQL rows + COUNT/MAX aggregates; no ORM episode or link rows are loaded."""
    db, cfg = ctx["db"], ctx.get("cfg")
    from services import next_air_from
    tz = getattr(cfg, "tz", None) if cfg else None
    posters_on = posters_enabled(ctx)
    items = []
    for d in db.catalog_cards(limit=CATALOG_MAX, synopsis_max=SYNOPSIS_MAX):
        seas = d["seasons"]
        multi = len(seas) > 1
        latest_at, latest_label = None, ""
        labeled = multi or any(x["n"] != 1 for x in seas)
        if d["latest"]:
            at, sn, ep = d["latest"]
            latest_at = _to_naive(at)
            latest_label = f"S{sn} · EP {ep}" if labeled else f"EP {ep}"
        cur = (max([x for x in seas if x["status"] == "Ongoing"] or seas, key=lambda x: x["n"]) if seas else None)
        have = cur["eps"] if cur else d["episodes"]
        tot = (cur["total"] if cur else None) or d["total_episodes"]
        nxt = None
        try:
            info = (next_air_from(d["status"], cur["max"] if cur else d["max_ep"],
                                  cur["total"] if cur else d["total_episodes"],
                                  d["air_time"], d["next_ep_date"], tz) if tz else None)
        except Exception:
            info = None
        if info:
            ep, when, has_time = info
            nxt = {"ep": ep, "date": f"{when:%B} {when.day}, {when.year}",
                   "time": (f"{when:%I:%M %p}".lstrip("0") + " IST") if has_time else ""}
        ref = d["poster"]
        poster = None
        web_poster = clean_web_poster(d.get("web_poster_url"))
        if web_poster:
            poster = web_poster            # website-only poster: direct <img>, never fetched by us
        elif not posters_on:
            pass
        elif is_http(ref):
            poster = ref
        elif ref:
            poster = f"/poster/{d['id']}.jpg?v={abs(hash(ref)) % 10**8}"
        items.append({
            "id": d["id"], "title": d["title"], "year": d["year"],
            "status": resolve_status(d["status"], nxt, have, tot),
            "genres": [g.strip() for g in d["genres"].split(",") if g.strip()],
            "synopsis": d["synopsis"][:SYNOPSIS_MAX], "imdb": d["imdb"],
            "audio": d["audio"] or getattr(cfg, "default_audio", ""),
            "poster": poster, "web_poster": web_poster,
            "poster_ref": ref if (posters_on and not web_poster) else None,
            "multi": multi, "labeled": labeled,
            "cur": cur["n"] if cur else (min((x["n"] for x in seas), default=1)),
            "have": have, "total": tot, "next": nxt,
            "latest_at": latest_at, "latest_label": latest_label,
            "updated": _to_naive(d["updated_at"]), "n": norm(d["title"]), "alt": [],
        })
    by_id = {x["id"]: x for x in items}
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    trending, new_week = [], []
    try:
        trending = [by_id[i] for i in db.trending_drama_ids(since, limit=16) if i in by_id]
        new_week = [by_id[i] for i in db.new_this_week_ids(since, limit=16) if i in by_id]
    except Exception:
        log.exception("week rails failed")
    return {"items": items, "by_id": by_id, "trending": trending, "new_week": new_week, "built": time.time()}


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


def resolve_status(status: str | None, nxt, have, total) -> str:
    """Use the stored status; if it's missing, infer Ongoing vs Completed."""
    st = (status or "").strip()
    if st in ("Ongoing", "Completed"):
        return st
    if nxt:
        return "Ongoing"
    if total and have and have >= total:
        return "Completed"
    return st or "Ongoing"


def featured_dramas(cat: dict, n: int = 5) -> list:
    """3–5 hero slides: trending this week first, then newest updates."""
    seen, out = set(), []
    newest = sorted(
        [d for d in cat.get("items") or [] if d.get("latest_at")],
        key=lambda d: d["latest_at"], reverse=True)
    for d in list(cat.get("trending") or []) + newest + list(cat.get("items") or []):
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        out.append(d)
        if len(out) >= n:
            break
    return out


def progress(d) -> str:
    if d["total"]:
        return f"{d['have']}/{d['total']} EP"
    return f"{d['have']} EP" if d["have"] else "Coming soon"


def status_pill(status: str) -> str:
    cls = "done" if status == "Completed" else "live"
    return f'<span class="spill {cls}"><i></i>{e(status)}</span>'


def hue(d) -> int:
    """Stable per-drama hue in the purple -> magenta band (no images needed)."""
    h = int(hashlib.md5(str(d["id"]).encode()).hexdigest()[:4], 16)
    return 252 + h % 70


def initial(d) -> str:
    t = (d["title"] or "?").strip()
    m = re.search(r"\w", t)
    return (m.group(0) if m else t[:1] or "?").upper()


def poster_img(d, cls: str = "", eager: bool = False) -> str:
    letter = e(initial(d))
    img = ""
    if d["poster"]:
        load = "eager" if eager else "lazy"
        prio = ' fetchpriority="high"' if eager else ""
        img = (f'<img src="{e(d["poster"])}" alt="{e(d["title"])} poster" loading="{load}" decoding="async"{prio} '
               f'referrerpolicy="no-referrer" onload="this.classList.add(\'is-on\')" onerror="this.remove()">')
    tile = (f'<span class="pst-ph" aria-hidden="true">{letter}</span>'
            f'<span class="pst-t">{e(d["title"])}</span>')
    return f'<div class="pst {cls}" style="--h:{hue(d)}">{tile}{img}</div>'


def backdrop(d, cls: str, eager: bool = False) -> str:
    """Gradient backdrop; with a poster, a blurred <img> on top that removes itself if it fails to load."""
    img = ""
    if d["poster"]:
        load = "eager" if eager else "lazy"
        prio = ' fetchpriority="high"' if eager else ""
        img = (f'<img class="bgimg" src="{e(d["poster"])}" alt="" loading="{load}" decoding="async"{prio} '
               f'referrerpolicy="no-referrer" onerror="this.parentNode.classList.remove(\'has-img\');this.remove()">')
    return (f'<div class="{cls} ph{" has-img" if img else ""}" style="--h:{hue(d)}">'
            f'<span>{e(initial(d))}</span>{img}</div>')


def drama_url(d) -> str:
    return f"/drama/{d['id']}-{slug(d['title'])}"


def card(d, extra: str = "") -> str:
    year = str(d["year"]) if d["year"] else ""
    return (f'<a class="card" href="{drama_url(d)}">{poster_img(d)}'
            f'<div class="card-badges">{status_pill(d["status"])}{extra}</div>'
            f'<span class="ep-badge">{e(progress(d))}</span>'
            f'<div class="card-body"><h3>{e(d["title"])}</h3>'
            f'{"<p>" + e(year) + "</p>" if year else ""}</div></a>')


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
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M21 14.5A8.5 8.5 0 1 1 9.5 3 7 7 0 0 0 21 14.5z"/>',
}


def ic(name: str, cls: str = "") -> str:
    fill = name in {"play", "star", "moon"}
    return (f'<svg class="i {cls}" viewBox="0 0 24 24" fill="{"currentColor" if fill else "none"}" stroke="currentColor" '
            f'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def search_box(q: str = "", big: bool = False, autofocus: bool = False) -> str:
    return (f'<form class="sbox{" big" if big else ""}" action="/search" method="get" role="search" autocomplete="off">'
            f'{ic("search")}<input type="search" name="q" value="{e(q)}" placeholder="Search dramas by title…" '
            f'aria-label="Search dramas" data-suggest{" autofocus" if autofocus else ""} maxlength="80">'
            f'<button type="submit" class="sbtn">Search</button>'
            f'<div class="suggest" role="listbox" hidden></div></form>')


def quality_phrase(quals: list[str] | None) -> str:
    """'720p', '480p & 1080p', or '480p, 720p & 1080p' — only the qualities the drama has."""
    qs = [q for q in (quals or []) if q]
    if not qs:
        return ""
    if len(qs) == 1:
        return qs[0]
    if len(qs) == 2:
        return f"{qs[0]} & {qs[1]}"
    return ", ".join(qs[:-1]) + " & " + qs[-1]


def drama_title_tag(title: str, quals: list[str] | None = None) -> str:
    q = quality_phrase(quals)
    if q:
        return f"Watch {title} in {q} | {SITE_NAME}"
    return f"Watch {title} | {SITE_NAME}"


def share_desc(d, quals: list[str] | None = None) -> str:
    """Meta description: year (optional), status, episode count, qualities, then a short synopsis."""
    bits = [x for x in [
        str(d["year"]) if d.get("year") else "",
        d.get("status") or "",
        progress(d),
    ] if x]
    phrase = quality_phrase(quals)
    if phrase:
        bits.append(phrase)
    head = " · ".join(bits)
    syn = (d.get("synopsis") or "").strip()
    if syn:
        text = f"{head}. {syn}" if head else syn
    else:
        watch = f"Watch {d['title']}" + (f" in {phrase}" if phrase else "") + f" on {SITE_NAME}."
        text = f"{head}. {watch}" if head else watch
    return text[:300]


def json_ld_tags(objs) -> str:
    if not objs:
        return ""
    items = objs if isinstance(objs, list) else [objs]
    out = []
    for obj in items:
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        out.append(f'<script type="application/ld+json">{raw.replace("<", "\\u003c")}</script>')
    return "".join(out)


def tv_series_ld(d, quals, url: str) -> dict:
    data = {
        "@context": "https://schema.org",
        "@type": "TVSeries",
        "name": d["title"],
        "description": share_desc(d, quals),
        "url": url,
    }
    if d.get("web_poster") and is_http(d["web_poster"]):
        data["image"] = d["web_poster"]
    if d.get("have"):
        data["numberOfEpisodes"] = int(d["have"])
    if d.get("year"):
        year = str(d["year"])
        data["datePublished"] = year
        data["startDate"] = year
    return data


def breadcrumb_ld(title: str, url: str, origin: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": origin + "/"},
            {"@type": "ListItem", "position": 2, "name": title, "item": url},
        ],
    }


def google_verification_meta(ctx) -> str:
    """Home-page Google Search Console HTML tag, if GOOGLE_SITE_VERIFICATION is set."""
    cfg = ctx.get("cfg") if ctx else None
    token = (getattr(cfg, "google_site_verification", None) or "").strip()
    if not token or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", token):
        return ""
    return f'<meta name="google-site-verification" content="{e(token)}">'


def website_ld(origin: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": SITE_NAME,
        "url": origin + "/",
        "potentialAction": {
            "@type": "SearchAction",
            "target": origin + "/search?q={search_term_string}",
            "query-input": "required name=search_term_string",
        },
    }


def robots_txt(ctx) -> bytes:
    base = canonical_origin(ctx)
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /go/\n"
        "Disallow: /api/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    ).encode()


def _xml(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _iso_date(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, datetime) and dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d")


def sitemap_xml(ctx) -> bytes:
    """Home + every live drama page. Cached ~1 hour; cleared on invalidate()."""
    key = id(ctx.get("db"))
    now = time.time()
    with _lock:
        if _sitemap["body"] is not None and _sitemap["key"] == key and now - _sitemap["at"] < SITEMAP_TTL:
            return _sitemap["body"]
    origin = canonical_origin(ctx)
    rows = ctx["db"].sitemap_rows()
    urls = [f"  <url><loc>{_xml(origin + '/')}</loc>"]
    home_mod = max((r["lastmod"] for r in rows if r.get("lastmod")), default=None)
    if home_mod:
        urls[0] += f"<lastmod>{_iso_date(home_mod)}</lastmod>"
    urls[0] += "</url>"
    for r in rows:
        loc = origin + drama_url(r)
        entry = f"  <url><loc>{_xml(loc)}</loc>"
        if r.get("lastmod"):
            entry += f"<lastmod>{_iso_date(r['lastmod'])}</lastmod>"
        urls.append(entry + "</url>")
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n</urlset>\n"
    ).encode()
    with _lock:
        _sitemap.update(key=key, at=now, body=body)
    return body


def page(ctx, *, title: str, body: str, desc: str = "", image: str | None = None, path: str = "/",
         host: str = "", nav: str = "", watch: dict | None = None, full_title: str | None = None,
         robots: str | None = None, json_ld=None) -> str:
    bot, chan = bot_name(ctx), channel_handle(ctx)
    base = public_origin(ctx, host)
    canon = canonical_origin(ctx)
    if not full_title:
        if title in {"kdrama_heaven", SITE_NAME}:
            full_title = "Kdrama Heaven — Watch K-dramas in 480p, 720p & 1080p"
        else:
            full_title = f"{title} · {SITE_NAME}"
    desc = desc or "Browse ongoing and completed Korean dramas, pick an episode and choose 480p, 720p or 1080p. New episodes every week on Kdrama Heaven."
    if image and is_http(image):
        img = image
    elif image:
        img = base + image
    else:
        img = base + SHARE_IMAGE
    og_img = (f'<meta property="og:image" content="{e(img)}">'
              f'<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">'
              f'<meta name="twitter:image" content="{e(img)}">')
    watch_attr = ""
    if watch:
        watch_attr = f' data-watch="{e(json.dumps(watch, ensure_ascii=True, separators=(",", ":")))}"'
    robots_tag = f'<meta name="robots" content="{e(robots)}">' if robots else ""
    verify_tag = google_verification_meta(ctx) if path == "/" else ""
    navl = lambda k, href, label: f'<a href="{href}" class="{"on" if nav == k else ""}">{label}</a>'
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(full_title)}</title>
<meta name="description" content="{e(desc[:300])}">{robots_tag}{verify_tag}
<meta name="theme-color" content="#0b0918" id="theme-color">
<script>(function(){{try{{var t=localStorage.getItem('kdh-theme');if(t==='light'){{document.documentElement.setAttribute('data-theme','light');var m=document.getElementById('theme-color');if(m)m.setAttribute('content','#f3f0fa');}}}}catch(e){{}}}})();</script>
<link rel="canonical" href="{e(canon + path)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{e(full_title)}"><meta property="og:description" content="{e(desc[:300])}">
<meta property="og:url" content="{e(base + path)}">{og_img}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(full_title)}"><meta name="twitter:description" content="{e(desc[:300])}">
<link rel="icon" href="/static/favicon-32.png?v={ASSET_V}" type="image/png" sizes="32x32"><link rel="icon" href="/favicon.ico?v={ASSET_V}" sizes="any"><link rel="apple-touch-icon" href="/static/apple-touch-icon.png?v={ASSET_V}" sizes="180x180">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap">
<link rel="stylesheet" href="/static/public.css?v={ASSET_V}">
{json_ld_tags(json_ld)}
</head><body>
<header class="hdr" id="hdr">
  <div class="hdr-in">
    <a class="logo" href="/" aria-label="Kdrama Heaven home"><picture><source type="image/webp" srcset="/static/logo.webp?v={ASSET_V}"><img class="logo-img" src="/static/logo.png?v={ASSET_V}" alt="Kdrama Heaven" width="349" height="140" decoding="async"></picture></a>
    <nav class="hnav">{navl("home", "/", "Home")}{navl("Ongoing", "/?status=ongoing#browse", "Ongoing")}{navl("Completed", "/?status=completed#browse", "Completed")}</nav>
    <div class="hdr-r">
      <button type="button" class="icon-b" id="theme-toggle" aria-label="Switch to light theme" aria-pressed="false">{ic("sun", "sun")}{ic("moon", "moon")}</button>
      <button type="button" class="icon-b" id="search-open" aria-label="Search">{ic("search")}</button>
      <a class="tg-b" href="https://t.me/{e(chan)}" target="_blank" rel="noopener">{ic("tg")}<span>@{e(chan)}</span></a>
    </div>
  </div>
  <div class="hdr-search" id="hdr-search" hidden>{search_box()}<button type="button" class="icon-b" id="search-close" aria-label="Close search">{ic("x")}</button></div>
</header>
<main id="main"{watch_attr}>
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
<script>(function(){{try{{var v=JSON.parse(localStorage.getItem('kdh-continue')||'[]');if(!Array.isArray(v)||!v.length)return;var s=document.getElementById('continue'),t=document.getElementById('continue-track');if(!s||!t)return;s.hidden=false;var n=Math.min(v.length,6),h='';while(n--)h+='<article class="card skel-card" aria-hidden="true"><div class="pst"></div><div class="card-body"><i></i><i></i></div></article>';t.innerHTML=h;}}catch(e){{}}}})();</script>
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
    featured = featured_dramas(cat, 5)
    slides, dots = [], []
    for i, d in enumerate(featured):
        nxt = (f'<span class="hmeta-i">{ic("cal")}Next: EP {d["next"]["ep"]} · {e(d["next"]["date"])}</span>'
               if d["next"] else "")
        meta = "".join(f'<span class="hmeta-i">{x}</span>' for x in [
            e(str(d["year"])) if d["year"] else "", f'{ic("star")}{e(d["imdb"])}' if d["imdb"] else "",
            e(progress(d))] if x) + nxt
        bg = backdrop(d, "hero-bg", eager=(i == 0))
        slides.append(f"""
        <article class="slide{' on' if i == 0 else ''}" data-slide="{i}">
          {bg}<div class="hero-shade"></div>
          <div class="hero-in">
            <div class="hero-txt">
              <div class="hero-kick">{status_pill(d['status'])}<span class="kick">Featured</span></div>
              <p class="hero-title">{e(d['title'])}</p>
              <div class="hmeta">{meta}</div>
              <p class="hero-syn">{e(d['synopsis'][:240] + ('…' if len(d['synopsis']) > 240 else ''))}</p>
              <div class="hero-cta"><a class="btn pri" href="{drama_url(d)}#episodes">{ic('play')}Watch</a>
                <a class="btn ghost" href="{drama_url(d)}">Details</a></div>
            </div>
            {poster_img(d, 'hero-pst', eager=(i == 0))}
          </div>
        </article>""")
        dots.append(f'<button type="button" class="dot{" on" if i == 0 else ""}" data-go="{i}" aria-label="Show {e(d["title"])}"></button>')
    hero = (f'<section class="hero" id="hero">{"".join(slides)}'
            f'<div class="hero-dots">{"".join(dots) if len(dots) > 1 else ""}</div></section>') if slides else ""
    latest_cards = "".join(card(d, f'<span class="new">{e(d["latest_label"])}</span>') for d in latest[:16])
    trending_cards = "".join(card(d, '<span class="hot">Trending</span>') for d in (cat.get("trending") or []))
    new_week = cat.get("new_week") or []
    new_cards = "".join(
        card(d, f'<span class="new">{e(d["latest_label"] or "New")}</span>') for d in new_week)
    # "New this week" is a 7-day slice of the same idea as "Latest updates".
    # Show it when there's weekly activity; otherwise keep Latest updates so the
    # home page still has a freshness row. Never both, so they don't repeat.
    fresh = (rail("New this week", new_cards, sub="Episodes added and titles that arrived this week")
             if new_cards else
             rail("Latest updates", latest_cards, sub="Freshly added episodes"))
    continue_rail = (
        '<section class="rail" id="continue" hidden>'
        '<div class="sec-h"><div><h2>Continue watching</h2>'
        "<p>Pick up where you left off — saved on this device only.</p></div>"
        '<button type="button" class="more cw-clear">Clear all</button></div>'
        '<div class="rail-track" id="continue-track"></div></section>'
    )
    st = status.lower()
    grid_items = ongoing if st == "ongoing" else completed if st == "completed" else items
    tabs = "".join(
        f'<a class="tab{" on" if st == k else ""}" href="/{("?status=" + k) if k else ""}#browse">{lbl}'
        f'<span>{n}</span></a>'
        for k, lbl, n in (("", "All", len(items)), ("ongoing", "Ongoing", len(ongoing)),
                          ("completed", "Completed", len(completed))))
    grid = ("".join(card(d) for d in grid_items) if grid_items else "")
    body = f"""
    <h1 class="sr-only">Kdrama Heaven</h1>
    {hero}
    <section class="search-band"><div class="wrap">
      <h2>Find your next K-drama</h2>
      {search_box(big=True)}
    </div></section>
    <div class="wrap">
      {continue_rail}
      {rail("Trending this week", trending_cards, sub="Most opened episodes this week")}
      {fresh}
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
    return page(ctx, title="kdrama_heaven", body=body, path="/", host=host,
                nav={"ongoing": "Ongoing", "completed": "Completed"}.get(st, "home"),
                json_ld=website_ld(canonical_origin(ctx)))


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
    sdesc = (f"Search results for “{q}” on Kdrama Heaven." if q
             else "Search ongoing and completed K-dramas on Kdrama Heaven.")
    return page(ctx, title=f"Search: {q}" if q else "Search", body=body, desc=sdesc,
                path="/search", host=host, nav="search",
                robots="noindex,follow" if q else None)


def api_search(ctx, q: str) -> dict:
    cat = catalog(ctx)
    res = search(cat, q, limit=8) if q else []
    return {"q": q, "results": [{
        "id": d["id"], "title": d["title"], "year": d["year"], "status": d["status"],
        "poster": d["poster"], "url": drama_url(d), "eps": progress(d), "h": hue(d), "i": initial(d)} for d in res]}


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
    label = (f"Season {sea['n']} · Episode {ep['n']}"
             if (d["multi"] or d.get("labeled") or sea["n"] != 1) else f"Episode {ep['n']}")
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
    lowest = min((s["n"] for s in seas), default=1) if seas else 1
    sea = next((s for s in seas if s["n"] == season), None) \
        or next((s for s in seas if s["n"] == d["cur"]), None) \
        or next((s for s in seas if s["n"] == lowest), None) \
        or (seas[0] if seas else {"n": lowest, "status": d["status"], "total": d["total"], "eps": []})
    eps = sea["eps"]
    sel = next((x for x in eps if x["n"] == epn), None) or (eps[-1] if eps else None)
    switch = ""
    if d["multi"] or d.get("labeled"):
        switch = '<div class="seasons" role="tablist">' + "".join(
            f'<a class="tab{" on" if s["n"] == sea["n"] else ""}" href="{drama_url(d)}?s={s["n"]}#episodes">'
            f'Season {s["n"]}<span>{len(s["eps"])}{"/" + str(s["total"]) if s["total"] else ""}</span></a>'
            for s in seas) + "</div>"
    latest_sea = max((s for s in seas if s.get("eps")), key=lambda s: (s["n"], s["eps"][-1]["n"]), default=None)
    latest_ep = latest_sea["eps"][-1] if latest_sea else None
    if latest_ep:
        watch_href = f'{drama_url(d)}?s={latest_sea["n"]}&amp;ep={latest_ep["n"]}#episodes'
        jump = f' data-jump="ep-{latest_sea["n"]}-{latest_ep["n"]}"' if latest_sea["n"] == sea["n"] else ""
        watch_btn = f'<a class="btn pri xl"{jump} href="{watch_href}">{ic("play")}Watch latest episode</a>'
    else:
        watch_btn = f'<a class="btn pri xl" href="#episodes">{ic("play")}Episodes</a>'
    chips = "".join(
        f'<a class="epc{" on" if sel and x["n"] == sel["n"] else ""}" href="{drama_url(d)}?s={sea["n"]}&amp;ep={x["n"]}#episodes" '
        f'data-ep="{x["n"]}" data-target="ep-{sea["n"]}-{x["n"]}">{x["n"]}</a>' for x in eps)
    if sea["total"] and len(eps) < sea["total"] and sea["status"] != "Completed":
        chips += "".join(f'<span class="epc soon" title="Coming soon">{n}</span>'
                         for n in range(max((x["n"] for x in eps), default=0) + 1, sea["total"] + 1))
    panels = "".join(ep_panel(d, sea, x, bot, bool(sel and x["n"] == sel["n"])) for x in eps)
    eps_html = (f'<div class="ep-grid" id="ep-grid">{chips}</div>{panels}' if eps else
                empty("No episodes yet", "Follow the drama on Telegram and we'll DM you when new episodes drop.",
                      f'<a class="btn pri" href="{tme(bot, "follow_" + str(d["id"]))}" target="_blank" rel="noopener">{ic("bell")}Notify me</a>'))
    facts = [("Status", status_pill(d["status"]))]
    if d["year"]:
        facts.append(("Year", e(d["year"])))
    facts.append(("Episodes", e(progress(d) + (f" · S{d['cur']}" if (d["multi"] or d.get("labeled")) else ""))))
    if d["multi"]:
        facts.append(("Seasons", e(len(seas))))
    elif d.get("labeled"):
        facts.append(("Season", e(sea["n"])))
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
    bg = backdrop(d, "dbg")
    body = f"""
    <section class="dhero">{bg}<div class="dshade"></div>
      <div class="wrap dhero-in">
        {poster_img(d, 'dpst', eager=True)}
        <div class="dinfo">
          <nav aria-label="Breadcrumb"><a class="crumb" href="/">Home</a></nav>
          <h1>{e(d['title'])}</h1>
          <div class="gchips">{genres}</div>
          {switch}
          <p class="syn">{e(d['synopsis'])}</p>
          {nxt}
          <div class="dcta">
            {watch_btn}
            <a class="btn ghost" href="{tme(bot, 'drama_' + str(d['id']))}" target="_blank" rel="noopener">{ic("tg")}Open in Telegram</a>
            <a class="btn ghost" href="{tme(bot, 'follow_' + str(d['id']))}" target="_blank" rel="noopener">{ic("bell")}Notify me</a>
          </div>
        </div>
      </div>
    </section>
    <div class="wrap dbody">
      <section class="eps" id="episodes">
        <div class="sec-h"><div><h2>Episodes</h2><p>Pick an episode, then choose 480p, 720p or 1080p.</p></div></div>
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
    desc = share_desc(d, quals)
    image = d["poster"] if (d.get("poster") and is_http(d["poster"])) else None
    watch = {
        "id": d["id"], "title": d["title"], "url": drama_url(d),
        "ep": sel["n"] if sel else None, "season": sea["n"] if sea else 1,
        "h": hue(d), "i": initial(d), "poster": d["poster"] or "",
    }
    origin = canonical_origin(ctx)
    url = origin + drama_url(d)
    return page(ctx, title=d["title"], full_title=drama_title_tag(d["title"], quals),
                body=body, desc=desc, image=image, path=drama_url(d),
                host=host, watch=watch,
                json_ld=[tv_series_ld(d, quals, url), breadcrumb_ld(d["title"], url, origin)])


def not_found(ctx, host: str = "") -> str:
    body = f"""<div class="wrap nf">
      <div class="nf-code">404</div>
      <h1>This page went off-air</h1>
      <p class="muted">The drama or page you're looking for doesn't exist or was removed.</p>
      {search_box(big=True)}
      <a class="btn ghost" href="/">Back to home</a>
    </div>"""
    return page(ctx, title="Page not found", body=body, path="/404", host=host,
                robots="noindex,follow")


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


# Posters are STREAMED, never held in memory: only file_id -> Telegram download URL is remembered
# (bounded, short TTL), and the image bytes flow upstream -> client in small chunks.
POSTER_CHUNK = 32 * 1024            # bytes per read/write
POSTER_MAX_BYTES = 8 * 1024 * 1024  # refuse anything bigger than a sane poster
_PATH_TTL = 30 * 60.0               # Telegram download links live >= 1 h
_PATH_MAX = 200
_paths: "OrderedDict[str, tuple[str, float]]" = OrderedDict()


def posters_enabled(ctx) -> bool:
    cfg = ctx.get("cfg")
    return bool(getattr(cfg, "public_posters", False)) if cfg is not None else False


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
