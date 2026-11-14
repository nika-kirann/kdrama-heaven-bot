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
            return r.status, dict(r.headers), r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()


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
    assert set(j["results"][0]) == {"id", "title", "year", "status", "poster", "url", "eps"}
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
