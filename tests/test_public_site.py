"""Public catalog website: home, search API, drama page quality picker, link redirects, 404, escaping."""
import json
import re
import urllib.request

import pytest

from tests.test_admin_web import web  # noqa: F401  (fixture: server + db + fake bot)
from web import public as P


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def raw(web, path):
    op = urllib.request.build_opener(NoRedirect)
    try:
        with op.open(web.base + path, timeout=5) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")


def seed(db):
    a = db.add_drama(title="Lovely Runner", status="Completed", year=2024, genres="Romance, Fantasy",
                     total_episodes=2, synopsis="Time travel romance.",
                     episodes={1: [("720p", "https://cdn.x/lr1-720.mkv", "part")],
                               2: [("720p", "https://cdn.x/lr2-720.mkv", "part")]})
    b = db.add_drama(title="Squid Game", status="Ongoing", year=2021, total_episodes=9,
                     episodes={1: [("480p", "https://cdn.x/sg1-480.mkv", "part"),
                                   ("1080p", "https://cdn.x/sg1-1080-p1.mkv", "part"),
                                   ("1080p", "https://cdn.x/sg1-1080-p2.mkv", "part"),
                                   ("1080p", "https://mirror.x/sg1-1080.mkv", "mirror")]})
    db.update_drama(b.id, next_ep_date="2099-11-11", air_time="20:00")
    P.invalidate()
    return a, b


def test_home_lists_rows_and_full_next_date(web):
    a, b = seed(web.db)
    st, hdrs, body = raw(web, "/")
    assert st == 200 and hdrs["Content-Type"].startswith("text/html")
    for s in ("Latest updates", "Ongoing", "Completed", "Lovely Runner", "Squid Game", 'href="/drama/'):
        assert s in body
    assert "November 11, 2099" in body and "days" not in body.lower().split("<body")[1].replace("holidays", "")
    assert 'og:title' in body and 'rel="icon"' in body and "/static/public.css?v=" in body
    assert 'alt="Kdrama Heaven"' in body
    assert f"/static/logo.webp?v={P.ASSET_V}" in body and f"/static/logo.png?v={P.ASSET_V}" in body
    assert f"/static/favicon-32.png?v={P.ASSET_V}" in body
    assert "t.me/kdrama_heaven" in body and "start=request" in body
    assert 'loading="lazy"' in body or "pst-ph" in body
    # status filter tabs (no category system)
    st, _, body = raw(web, "/?status=ongoing")
    grid = body.split('id="browse"')[1]
    assert "Squid Game" in grid and "Lovely Runner" not in grid.split("cta-band")[0]
    assert "genre" not in body.lower().replace("gchip", "")
    # admin + health untouched
    st, _, body = raw(web, "/healthz")
    assert st == 200 and json.loads(body)["ok"] is True
    st, hdrs, _ = raw(web, "/admin")
    assert st == 303 and hdrs["Location"] == "/admin/login"


def test_search_api_and_page(web):
    seed(web.db)
    st, hdrs, body = raw(web, "/api/search?q=squid")
    j = json.loads(body)
    assert st == 200 and hdrs["Content-Type"].startswith("application/json")
    assert [r["title"] for r in j["results"]] == ["Squid Game"]
    assert set(j["results"][0]) == {"id", "title", "year", "status", "poster", "url", "eps", "h", "i"}
    assert json.loads(raw(web, "/api/search?q=LOVELY")[2])["results"][0]["title"] == "Lovely Runner"
    assert json.loads(raw(web, "/api/search?q=squd%20game")[2])["results"][0]["title"] == "Squid Game"  # typo
    assert json.loads(raw(web, "/api/search?q=")[2])["results"] == []
    st, _, body = raw(web, "/search?q=lovely")
    assert st == 200 and "Lovely Runner" in body and "Squid Game" not in body.split("<main")[1].split("</main>")[0]
    st, _, body = raw(web, "/search?q=zzzz")
    assert "No dramas found" in body and "start=request" in body


def test_search_api_rate_limited(web, monkeypatch):
    seed(web.db)
    monkeypatch.setattr(P, "RATE_N", 3)
    P._rate.clear()
    codes = [raw(web, "/api/search?q=lo")[0] for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429
    P._rate.clear()


def test_drama_page_quality_buttons_and_links(web):
    a, b = seed(web.db)
    st, _, body = raw(web, f"/drama/{b.id}")
    assert st == 200 and "<h1>Squid Game</h1>" in body and "Squid Game (2021)" not in body
    panel = body.split('id="ep-1-1"')[1].split('class="ep-help"')[0]
    assert ">480p<" in panel and ">1080p<" in panel and "720p" not in panel
    assert "Part 2" in panel and "Mirror" in panel
    assert "November 11, 2099" in body and "start=report_%d" % b.id in body and "start=request" in body
    assert "start=drama_%d" % b.id in body
    # quality links go through /go/<id> and land on the same URL the bot gives
    hrefs = re.findall(r'href="(/go/\d+)"', panel)
    st, hdrs, _ = raw(web, hrefs[0])
    assert st == 302 and hdrs["Location"] == "https://cdn.x/sg1-480.mkv"
    targets = {raw(web, h)[1]["Location"] for h in hrefs}
    assert targets == {"https://cdn.x/sg1-480.mkv", "https://cdn.x/sg1-1080-p1.mkv",
                       "https://cdn.x/sg1-1080-p2.mkv", "https://mirror.x/sg1-1080.mkv"}
    # first part of each quality counts as one click in the bot's stats
    from db import Click
    with web.db.session() as s:
        qs = sorted(c.quality for c in s.query(Click).filter(Click.drama_id == b.id))
    assert qs == ["1080p", "480p", "480p"]  # 480p opened twice above; parts 2 / mirrors not counted
    # slug URLs work; single-season page has no season switcher
    assert raw(web, f"/drama/{a.id}-lovely-runner")[0] == 200
    assert 'class="seasons"' not in raw(web, f"/drama/{a.id}")[2]


def test_non_http_link_uses_bot_deep_link_and_seasons(web):
    d = web.db.add_drama(title="Storage Show", status="Ongoing",
                         episodes={1: [("720p", "tg-storage:12345", "part")]})
    web.db.add_season(d.id, 4)
    web.db.add_episodes(d.id, {1: [("1080p", "https://x/s2e1", "part")]}, season=2)
    P.invalidate()
    body = raw(web, f"/drama/{d.id}?s=1")[2]
    href = re.search(r'id="ep-1-1".*?href="(/go/\d+)"', body, re.S).group(1)
    assert raw(web, href)[1]["Location"] == f"https://t.me/kdrama_heaven_bot?start=drama_{d.id}"
    assert 'class="seasons"' in body and "Season 2" in body
    assert 'id="ep-2-1"' in raw(web, f"/drama/{d.id}?s=2")[2]


def test_404_and_deleted(web):
    a, _ = seed(web.db)
    for path in ("/nope", "/drama/99999", "/go/99999"):
        st, hdrs, body = raw(web, path)
        assert st == 404 and "went off-air" in body and hdrs["Cache-Control"] == "no-store"
    web.db.mark_deleted(a.id)
    P.invalidate()
    assert raw(web, f"/drama/{a.id}")[0] == 404
    assert "Lovely Runner" not in raw(web, "/")[2]


def test_output_is_escaped_and_no_admin_data(web):
    evil = '<script>alert("x")</script>'
    d = web.db.add_drama(title=evil, status="Ongoing", synopsis="<img src=x onerror=alert(1)>", genres="<b>g</b>",
                         episodes={1: [("720p", 'https://x/1"><script>', "part")]})
    web.db.add_request(777001, "secretuser", "private request text")
    P.invalidate()
    for path in ("/", f"/drama/{d.id}", "/search?q=" + urllib.request.quote(evil)):
        body = raw(web, path)[2]
        assert "<script>alert" not in body and "<img src=x" not in body and "<b>g</b>" not in body
        assert "secretuser" not in body and "private request text" not in body and "777001" not in body
    api = raw(web, "/api/search?q=script")[2]
    assert "</script>" not in api and json.loads(api)["results"][0]["title"] == evil
    st, hdrs, _ = raw(web, "/static/public.css?v=1")
    assert st == 200 and "max-age" in hdrs["Cache-Control"]


def test_logo_and_favicon_assets(web):
    st, hdrs, _ = raw(web, f"/static/logo.webp?v={P.ASSET_V}")
    assert st == 200 and hdrs["Content-Type"].startswith("image/webp")
    assert "max-age=604800" in hdrs["Cache-Control"]
    st, hdrs, _ = raw(web, f"/static/logo.png?v={P.ASSET_V}")
    assert st == 200 and hdrs["Content-Type"].startswith("image/png")
    st, hdrs, body = raw(web, "/favicon.ico")
    assert st == 200 and "image/" in hdrs["Content-Type"] and "max-age=604800" in hdrs["Cache-Control"]
    st, hdrs, _ = raw(web, "/apple-touch-icon.png")
    assert st == 200 and hdrs["Content-Type"].startswith("image/png")
    st, _, body = raw(web, "/admin/login")
    assert st == 200 and 'alt="Kdrama Heaven"' in body and f"/static/logo.webp?v=" in body


# ---------------- posters: streamed, never cached in RAM ----------------
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

FAKE_TOKEN_PATH = "/file/bot123456:SECRETTOKEN/photos/file_7.jpg"
IMG = b"\xff\xd8\xff" + bytes(range(256)) * 800  # ~200 KB "jpeg"


@pytest.fixture
def tg_files():
    hits = {"n": 0, "fail": 0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            hits["n"] += 1
            if hits["fail"]:
                hits["fail"] -= 1
                self.send_response(404); self.send_header("Content-Length", "0"); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(IMG)))
            self.end_headers()
            self.wfile.write(IMG)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    hits["url"] = f"http://127.0.0.1:{srv.server_address[1]}{FAKE_TOKEN_PATH}"
    yield hits
    srv.shutdown()


def _wire_get_file(web, tg_files):
    calls = []

    async def get_file(file_id):
        calls.append(file_id)

        class F:
            file_path = tg_files["url"]
        return F()
    web.bot.get_file = get_file
    return calls


@pytest.fixture
def posters_on(web):
    web.cfg.public_posters = True
    P.invalidate()
    yield
    web.cfg.public_posters = False
    P.invalidate()


def test_poster_streamed_with_cache_headers_and_no_token(web, tg_files, posters_on):
    P._paths.clear()
    calls = _wire_get_file(web, tg_files)
    d = web.db.add_drama(title="Poster Show", status="Ongoing", poster="AgACfileid123")
    P.invalidate()
    body = raw(web, f"/drama/{d.id}")[2]
    src = re.search(r'src="(/poster/%d\.jpg\?v=\d+)"' % d.id, body).group(1)
    op = urllib.request.build_opener(NoRedirect)
    with op.open(web.base + src, timeout=5) as r:
        data, hdrs = r.read(), dict(r.headers)
    assert data == IMG and hdrs["Content-Type"] == "image/jpeg"
    assert hdrs["Cache-Control"] == "public, max-age=604800, immutable" and hdrs["ETag"].startswith('"p-')
    assert "SECRETTOKEN" not in json.dumps(hdrs) and "SECRETTOKEN" not in body
    # repeat view with ETag -> 304, Telegram not contacted again
    req = urllib.request.Request(web.base + src, headers={"If-None-Match": hdrs["ETag"]})
    try:
        op.open(req, timeout=5)
        assert False, "expected 304"
    except urllib.error.HTTPError as e:
        assert e.code == 304 and e.headers["ETag"] == hdrs["ETag"]
    assert tg_files["n"] == 1
    # second full fetch reuses the small file_id -> path map (one get_file call total)
    raw(web, src)
    assert calls == ["AgACfileid123"] and tg_files["n"] == 2
    # stale Telegram link -> asks get_file again once
    tg_files["fail"] = 1
    st, _, _ = raw(web, src)
    assert st == 200 and len(calls) == 2
    # nothing image-sized is kept in memory
    assert not hasattr(P, "_posters")
    assert all(isinstance(v[0], str) for v in P._paths.values())


def test_file_path_map_is_bounded():
    P._paths.clear()
    for i in range(P._PATH_MAX + 50):
        P.remember_file_url(f"f{i}", f"https://x/{i}")
    assert len(P._paths) == P._PATH_MAX and "f0" not in P._paths and P.cached_file_url(f"f{P._PATH_MAX + 49}")
    P._paths.clear()


def test_posters_off_by_default_uses_title_tiles(web, tg_files):
    assert web.cfg.public_posters is False          # default: no posters on the public site
    calls = _wire_get_file(web, tg_files)
    d = web.db.add_drama(title="Tiles Only", status="Ongoing", poster="AgACfileid999")
    h = web.db.add_drama(title="Http Poster", status="Ongoing", poster="https://img.example/p.jpg")
    P.invalidate()
    for path in ("/", f"/drama/{d.id}", f"/drama/{h.id}"):
        body = raw(web, path)[2]
        main = body.split("<main")[1]
        assert "<img" not in main and "background-image" not in main
        assert "/poster/" not in body and "img.example" not in body
        # polished tile: per-drama hue, big initial, title on the tile; gradient backdrop
        assert re.search(r'class="pst[^"]*" style="--h:\d+"><span class="pst-ph" aria-hidden="true">[A-Z]</span>'
                         r'<span class="pst-t">', main)
        assert ('class="hero-bg ph" style="--h:' in main) or ('class="dbg ph" style="--h:' in main)
    assert '<span class="pst-t">Tiles Only</span>' in raw(web, f"/drama/{d.id}")[2]
    assert raw(web, f"/poster/{d.id}.jpg")[0] == 404
    r = json.loads(raw(web, "/api/search?q=tiles")[2])["results"][0]
    assert r["poster"] is None and r["i"] == "T" and 252 <= r["h"] < 322
    assert calls == [] and tg_files["n"] == 0


def test_tile_hue_is_stable_and_initial_skips_symbols():
    a = {"id": 7, "title": "\u2018Moving\u2019"}
    assert P.hue(a) == P.hue({"id": 7, "title": "x"}) and 252 <= P.hue(a) < 322
    assert P.initial(a) == "M" and P.initial({"id": 1, "title": ""}) == "?"


def test_catalog_uses_sql_aggregates_not_episode_rows(web, monkeypatch):
    d = web.db.add_drama(title="Agg Show", status="Ongoing", total_episodes=16,
                         episodes={e: [("720p", f"https://x/{e}.mkv", "part")] for e in range(1, 6)})
    monkeypatch.setattr(type(web.db), "list_dramas", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ORM load")))
    P.invalidate()
    x = P.catalog({"db": web.db, "cfg": web.cfg})["by_id"][d.id]
    assert (x["have"], x["total"], x["latest_label"], x["cur"], x["multi"]) == (5, 16, "EP 5", 1, False)
    P.invalidate()


def test_catalog_snapshot_is_bounded(web, monkeypatch):
    for i in range(5):
        web.db.add_drama(title=f"Bounded {i}", status="Ongoing", synopsis="x" * 5000)
    monkeypatch.setattr(P, "CATALOG_MAX", 3)
    P.invalidate()
    cat = P.catalog({"db": web.db, "cfg": web.cfg})
    assert len(cat["items"]) == 3 and all(len(x["synopsis"]) <= P.SYNOPSIS_MAX for x in cat["items"])
    # the cached snapshot is card-level only: episode links are loaded per drama page, never cached
    assert all("seasons" not in x for x in cat["items"])
    P.invalidate()


def test_public_posters_env_flag(monkeypatch):
    from config import Config
    monkeypatch.delenv("PUBLIC_POSTERS", raising=False)
    assert Config().public_posters is False         # off unless explicitly enabled
    monkeypatch.setenv("PUBLIC_POSTERS", "1")
    assert Config().public_posters is True
    monkeypatch.setenv("PUBLIC_POSTERS", "0")
    assert Config().public_posters is False


# ---------------- website-only poster URL (browser loads it; server never fetches) ----------------
def test_web_poster_url_rendered_directly_everywhere(web, tg_files):
    calls = _wire_get_file(web, tg_files)
    url = "https://img.example/p.jpg?a=1&b=2"
    d = web.db.add_drama(title="Web Poster Drama", status="Ongoing", poster="AgACtelegramonly",
                         web_poster_url=url, episodes={1: [("720p", "https://x/1.mkv", "part")]})
    plain = web.db.add_drama(title="Plain Tile Drama", status="Ongoing")
    P.invalidate()
    esc = "https://img.example/p.jpg?a=1&amp;b=2"
    home = raw(web, "/")[2]
    # card + hero tile + hero backdrop: direct <img>, lazy, no referrer, removes itself on error (tile fallback)
    imgs = re.findall(r'<img[^>]*src="%s"[^>]*>' % re.escape(esc), home)
    assert len(imgs) >= 3
    assert all('loading="lazy"' in i and 'referrerpolicy="no-referrer"' in i and "onerror=" in i for i in imgs)
    assert 'class="hero-bg ph has-img"' in home and 'class="bgimg"' in home
    page = raw(web, f"/drama/{d.id}")[2]
    assert re.search(r'class="dbg ph has-img"[^>]*><span>W</span><img class="bgimg" src="%s"' % re.escape(esc), page)
    assert re.search(r'class="pst dpst"[^>]*><span class="pst-ph"[^>]*>W</span><span class="pst-t">[^<]+</span><img src="%s"' % re.escape(esc), page)
    # no background-image CSS, no /poster proxy, no Telegram contact
    assert "background-image" not in page and "/poster/" not in page + home
    assert calls == [] and tg_files["n"] == 0
    # search suggestions carry the URL for the client to render
    r = json.loads(raw(web, "/api/search?q=web+poster")[2])["results"][0]
    assert r["poster"] == url
    # a drama without one keeps the gradient tile
    pp = raw(web, f"/drama/{plain.id}")[2]
    assert 'class="dbg ph" style="--h:' in pp and "<img" not in pp.split("<main")[1]


def test_web_poster_url_rejects_non_http_and_injection(web):
    bad = ["javascript:alert(1)", "data:image/png;base64,AAA", 'https://x.example/a.jpg" onerror="alert(1)',
           "https://x.example/a b.jpg", "//x.example/a.jpg", "https://", "ftp://x/y.jpg", "https://x/" + "a" * 1001]
    for u in bad:
        assert P.clean_web_poster(u) is None, u
    assert P.clean_web_poster("  HTTPS://x.example/a.jpg  ") == "HTTPS://x.example/a.jpg"
    d = web.db.add_drama(title="Evil Poster", status="Ongoing", web_poster_url='javascript:alert(1)')
    P.invalidate()
    body = raw(web, f"/drama/{d.id}")[2]
    assert "javascript:" not in body and 'class="dbg ph" style="--h:' in body


def test_web_poster_overrides_telegram_streaming_when_both(web, tg_files, posters_on):
    calls = _wire_get_file(web, tg_files)
    d = web.db.add_drama(title="Both Posters", status="Ongoing", poster="AgACboth", web_poster_url="https://img.example/w.jpg")
    P.invalidate()
    body = raw(web, f"/drama/{d.id}")[2]
    assert 'src="https://img.example/w.jpg"' in body and "/poster/" not in body
    assert raw(web, f"/poster/{d.id}.jpg")[0] == 404 and calls == []
