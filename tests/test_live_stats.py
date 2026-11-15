"""Admin Live stats: SQL aggregates, date format, cached JSON endpoint."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from db import Click
from sqlalchemy import text
from tests.test_admin_web import web  # fixture
from web import html as H

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 15, 16, 55, tzinfo=TZ)


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _stamp(db, table: str, id_col: str, pk: int, when: datetime, extra: str = "") -> None:
    with db.engine.begin() as c:
        c.execute(text(f"UPDATE {table} SET created_at = :t {extra} WHERE {id_col} = :id"),
                  {"t": _naive_utc(when) if when.tzinfo else when, "id": pk})
    db.invalidate_live_stats()


def _seed(db):
    """Dated catalog so 24h / 7d / 30d buckets are distinguishable."""
    d1 = db.add_drama(title="Lovely Runner", status="Completed", year=2024, total_episodes=16,
                      episodes={i: [("720p", f"https://x/{i}", "part"),
                                    ("1080p", f"https://x/{i}h", "part")] for i in range(1, 5)})
    d2 = db.add_drama(title="When Life Gives You Tangerines", status="Ongoing", year=2025,
                      total_episodes=16, next_ep_date="2026-11-21", air_time="20:00",
                      episodes={i: [("1080p", f"https://y/{i}", "part")] for i in (1, 2)})
    d3 = db.add_drama(title="Past Date Show", status="Ongoing", total_episodes=10,
                      next_ep_date="2026-11-01", air_time="21:00",
                      episodes={1: [("720p", "https://z/1", "part")]})
    # backdate dramas: d1 20 days ago, d2 3 days ago, d3 today-ish (leave default)
    _stamp(db, "dramas", "id", d1.id, NOW - timedelta(days=20))
    _stamp(db, "dramas", "id", d2.id, NOW - timedelta(days=3))
    # episodes for d2: one 10 days ago (outside 7d, inside 30d), one 2 days ago
    eps = db.get_drama(d2.id).episodes
    older, newer = sorted(eps, key=lambda e: e.number)
    _stamp(db, "episodes", "id", older.id, NOW - timedelta(days=10))
    _stamp(db, "episodes", "id", newer.id, NOW - timedelta(days=2))

    db.touch_user(101, "minji", started=True)
    db.touch_user(102, "seoul", started=True)
    db.touch_user(103, None, started=False)
    u101, u102, u103 = 101, 102, 103
    _stamp(db, "users", "id", u101, NOW - timedelta(days=20))
    _stamp(db, "users", "id", u102, NOW - timedelta(days=3))
    _stamp(db, "users", "id", u103, NOW - timedelta(hours=2))

    db.set_follow(101, d1.id, True)
    db.set_follow(102, d2.id, True)
    db.set_follow(101, d2.id, True)

    # clicks: mix of ages and qualities
    for _ in range(5):
        db.add_click(d2.id, 1, "1080p", 102)
    for _ in range(2):
        db.add_click(d1.id, 2, "720p", 101)
    with db.session() as s:
        clicks = list(s.scalars(__import__("sqlalchemy").select(Click).order_by(Click.id)))
        # first five are d2, last two are d1 — backdate two of the d2 clicks to 10 days ago
        for c in clicks[:2]:
            c.created_at = _naive_utc(NOW - timedelta(days=10))
        s.commit()
    db.invalidate_live_stats()

    r_open = db.add_request(101, "minji", "Please add Reply 1988")
    r_old = db.add_request(102, "seoul", "Old request")
    _stamp(db, "requests", "id", r_old.id, NOW - timedelta(days=12))
    closed = db.add_request(103, None, "Already added")
    db.add_request_reply(closed.id, "It's up!", admin_id=1, close=True)

    db.add_report(d2.id, 101, "minji", "b", episode=1)
    return d1, d2, d3


def test_live_stats_aggregates_and_upcoming_full_date(tmp_path):
    from db import Database
    db = Database(f"sqlite:///{tmp_path}/live.db")
    d1, d2, d3 = _seed(db)
    data = db.live_stats(TZ, NOW)
    t, dlt = data["totals"], data["deltas"]
    assert t["dramas"] == 3 and t["ongoing"] == 2 and t["completed"] == 1
    assert t["episodes"] == 4 + 2 + 1
    assert t["users"] == 3 and t["users_started"] == 2
    assert t["requests"] == 3 and t["requests_open"] == 2 and t["requests_closed"] == 1
    assert t["reports_open"] == 1 and t["follows"] == 3 and t["clicks"] == 7

    # 24h: only user 103 (2h ago). dramas d3 is "now". clicks/follows/requests created just now too,
    # except backdated ones.
    assert dlt["24h"]["users"] == 1
    assert dlt["7d"]["users"] == 2   # 102 (3d) + 103 (2h); 101 is 20d
    assert dlt["30d"]["users"] == 3
    assert dlt["7d"]["dramas"] == 2  # d2 (3d) + d3 (now); d1 is 20d
    assert dlt["30d"]["dramas"] == 3
    # d2 eps: one 10d (not in 7d) + one 2d; d1's 4 and d3's 1 were just created
    assert dlt["7d"]["episodes"] == dlt["24h"]["episodes"] + 1  # the 2-day-old ep is in 7d not 24h

    series = data["series"]
    assert len(series["days"]) == 30 and series["days"][-1] == "2026-11-15"
    assert series["days"][0] == "2026-10-17"
    # user 102 three days ago -> 2026-11-12
    idx_3d = series["days"].index("2026-11-12")
    assert series["users"][idx_3d] == 1
    assert series["users"][-1] == 1  # user 103 today

    # upcoming: only d2 (future date). d3's Nov 1 is in the past. Full date, no countdown, no YEAR in title.
    assert len(data["upcoming"]) == 1
    up = data["upcoming"][0]
    assert up["id"] == d2.id and up["title"] == "When Life Gives You Tangerines"
    assert up["date"] == "November 21, 2026" and up["time"] == "8:00 PM IST"
    assert up["episode"] == 3 and "(" not in up["title"]
    blob = json.dumps(data)
    assert "in 1 day" not in blob and "in 2 days" not in blob and "countdown" not in blob.lower()
    assert "Past Date Show" not in blob  # past next_ep_date excluded

    # top clicked 7d: the two 10d-old d2 clicks drop out, leaving 3 on d2 and 2 on d1
    top7 = {r["title"]: r["clicks"] for r in data["top_clicked_7d"]}
    assert top7["When Life Gives You Tangerines"] == 3
    assert top7["Lovely Runner"] == 2
    top_all = {r["title"]: r["clicks"] for r in data["top_clicked_all"]}
    assert top_all["When Life Gives You Tangerines"] == 5
    fol = {r["title"]: r["followers"] for r in data["top_followed"]}
    assert fol["When Life Gives You Tangerines"] == 2 and fol["Lovely Runner"] == 1
    q7 = {r["quality"]: r["clicks"] for r in data["top_qualities_7d"]}
    assert q7["1080p"] == 3 and q7["720p"] == 2


def test_live_stats_cache_and_invalidation(tmp_path):
    from db import Database
    db = Database(f"sqlite:///{tmp_path}/cache.db")
    a = db.cached_live_stats(TZ, NOW, ttl=60)
    b = db.cached_live_stats(TZ, NOW, ttl=60)
    assert a is b
    db.touch_user(9, "x", started=True)
    c = db.cached_live_stats(TZ, NOW, ttl=60)
    assert c is not a
    assert c["totals"]["users"] == 1


def test_sparkline_and_bar_chart_svg():
    s = H.sparkline_svg([0, 2, 1, 4])
    assert s.startswith("<svg") and "polyline" in s and "polygon" in s
    bars = H.bar_chart_svg(["2026-11-01", "2026-11-02"], [3, 0])
    assert 'class="on"' in bars and 'class="empty"' in bars
    assert "<title>2026-11-01: 3</title>" in bars


def test_api_stats_requires_admin_and_returns_payload(web):
    st, body, hdrs = web.open("/admin/api/stats")
    ctype = (hdrs.get("Content-Type") or hdrs.get("content-type") or "").lower()
    assert "application/json" not in ctype
    assert "Dashboard" not in body and ("Sign in" in body or "Admin" in body or "Telegram" in body)

    web.login_password()
    st, body, hdrs = web.open("/admin/api/stats")
    assert st == 200
    ctype = (hdrs.get("Content-Type") or hdrs.get("content-type") or "").lower()
    assert "application/json" in ctype
    data = json.loads(body)
    assert data["ok"] is True
    assert "totals" in data and "dramas" in data["deltas"]["7d"]
    assert set(data["deltas"]) == {"24h", "7d", "30d"}
    assert len(data["series"]["days"]) == 30
    assert "upcoming" in data


def test_dashboard_renders_advanced_live_stats(web):
    d1, d2, _ = _seed(web.db)
    web.login_password()
    st, body, _ = web.open("/admin")
    assert st == 200
    assert 'id="live-stats"' in body and "live-pulse" in body
    assert "Live stats" in body and "Live stats text" not in body
    assert "stats-pre" not in body
    assert f"admin.css?v={H.ASSET_V}" in body and f"admin.js?v={H.ASSET_V}" in body
    assert "When Life Gives You Tangerines" in body
    assert "November 21, 2026" in body
    assert "in 5 days" not in body and "in 6 days" not in body
    # title style: no NAME (YEAR) in upcoming / top lists (year may still appear in Recent dramas)
    assert "When Life Gives You Tangerines (2025)" not in body
    assert 'id="live-stats-data"' in body
    assert 'data-n="dramas"' in body
    assert "Top clicked" in body and "Upcoming episodes" in body and "Activity" in body
    # empty-ish cards still present
    assert "Open reports" in body and "Users" in body
