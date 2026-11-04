import sqlite3
from datetime import datetime, timedelta

import pytest

import jobs
from db import Database
from services import drama_card, next_line
from tests.conftest import ADMIN, CHANNEL, VIEWER
from tests.fakes import cb_update, msg_update
from tests.test_bot import last_text
from tests.test_quality import _drama_on_channel, flat

pytestmark = pytest.mark.asyncio


def answers(env):
    return env.req.of("answerCallbackQuery")


async def _started(env, uid):
    await env.send(msg_update("/start", uid))


# ---------- follows ----------
async def test_follow_from_channel_requires_start_then_deep_link(env):
    d, chan = await _drama_on_channel(env, 3)
    card = [p for p in env.req.of("sendMessage") + env.req.of("sendPhoto") if p["chat_id"] == CHANNEL and p.get("reply_markup")][0]
    btn = [b for b in flat(card["reply_markup"]) if b.get("callback_data", "").startswith("fol:")]
    assert btn and btn[0]["callback_data"] == f"fol:{d.id}"
    await env.send(cb_update(f"fol:{d.id}", 55, **chan))
    assert answers(env)[-1]["url"].endswith(f"?start=follow_{d.id}")
    assert not env.db.is_following(55, d.id)
    await env.send(msg_update(f"/start follow_{d.id}", 55))
    assert env.db.is_following(55, d.id)
    assert any("You're following" in (p.get("text") or "") for p in env.req.of("sendMessage"))


async def test_channel_toggle_for_started_user_and_private_button(env):
    d, chan = await _drama_on_channel(env, 3)
    await _started(env, VIEWER)
    await env.send(cb_update(f"fol:{d.id}", VIEWER, **chan))
    assert env.db.is_following(VIEWER, d.id) and "Following" in answers(env)[-1]["text"]
    await env.send(cb_update(f"fol:{d.id}", VIEWER, **chan))
    assert not env.db.is_following(VIEWER, d.id)
    # private view: per-viewer label flips
    await env.send(cb_update(f"eps:{d.id}:0", VIEWER, chat_id=VIEWER, message_id=500, chat_type="private"))
    assert flat(env.req.of("editMessageReplyMarkup")[-1]["reply_markup"])[-1]["text"] == "🔔 Follow"
    await env.send(cb_update(f"fol:{d.id}:1", VIEWER, chat_id=VIEWER, message_id=500, chat_type="private"))
    # fake callback message has no markup -> just answered; check DB
    assert env.db.is_following(VIEWER, d.id)
    await env.send(cb_update(f"eps:{d.id}:0", VIEWER, chat_id=VIEWER, message_id=500, chat_type="private"))
    assert flat(env.req.of("editMessageReplyMarkup")[-1]["reply_markup"])[-1]["text"] == "🔕 Unfollow"


async def test_my_follows_view(env):
    d, _ = await _drama_on_channel(env, 2)
    await _started(env, VIEWER)
    assert "My follows" in str(env.req.of("sendMessage")[-1]["reply_markup"])
    await env.send(cb_update("my:follows", VIEWER))
    assert "aren't following" in env.req.of("editMessageText")[-1]["text"]
    env.db.set_follow(VIEWER, d.id, True)
    await env.send(cb_update("my:follows", VIEWER))
    e = env.req.of("editMessageText")[-1]
    assert "My follows</b> (1)" in e["text"] and flat(e["reply_markup"])[0]["callback_data"] == f"dr:{d.id}"


async def test_new_episode_alerts_rate_limited_and_drop_blocked(env):
    d, _ = await _drama_on_channel(env, 2)
    for uid in (10, 11, 12):
        await _started(env, uid)
        env.db.set_follow(uid, d.id, True)
    env.db.set_follow(13, d.id, True)
    env.db.touch_user(13, None, started=False)  # followed but never started
    env.req.blocked.add(11)
    res = await env.svc.add_episodes(d.id, {3: [("720p", "https://x/3", "part")]})
    dms = [p for p in env.req.of("sendMessage") if p["chat_id"] in (10, 12) and "New for you" in p["text"]]
    assert len(dms) == 2 and "New for you" in dms[0]["text"] and "EP 3" in dms[0]["text"]
    assert flat(dms[0]["reply_markup"])[0]["url"].endswith(f"?start=drama_{d.id}")
    assert not env.db.is_following(11, d.id) and env.db.get_user(11).blocked
    assert not [p for p in env.req.of("sendMessage") if p["chat_id"] == 13]
    out = await env.svc.notify_followers(d.id, "x")
    assert out == {"sent": 2, "blocked": 0, "skipped": 1}


async def test_complete_alerts_followers(env):
    d, _ = await _drama_on_channel(env, 2)
    await _started(env, 10)
    env.db.set_follow(10, d.id, True)
    await env.send(msg_update(f"/complete {d.id}", ADMIN))
    assert "series is complete" in [p for p in env.req.of("sendMessage") if p["chat_id"] == 10][-1]["text"]


async def test_migration_old_db_gets_new_tables_and_columns(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("create table dramas (id integer primary key, title varchar(200), poster varchar(500), synopsis text, "
              "genres varchar(300), year integer, status varchar(20), total_episodes integer, deleted boolean, "
              "created_at datetime, updated_at datetime)")
    c.execute("insert into dramas (title, synopsis, genres, status, deleted) values ('Old', '', '', 'Ongoing', 0)")
    c.commit(); c.close()
    db = Database(f"sqlite:///{p}")
    d = db.find_drama("Old")
    assert d.next_ep_date is None
    db.update_drama(d.id, next_ep_date="2026-11-11", air_time="20:00")
    db.set_follow(9, d.id, True); db.add_click(d.id, 1, "720p"); db.touch_user(9)
    db2 = Database(f"sqlite:///{p}")  # re-open (as after a Telegram restore) is idempotent
    assert db2.followers(d.id) == [9] and db2.get_drama(d.id).air_time == "20:00"


# ---------- next episode (admin-set date only) ----------
async def test_countdown_line_and_card(env):
    d, _ = await _drama_on_channel(env, 6)
    env.db.update_drama(d.id, total_episodes=16, air_days="5,6")   # legacy column is ignored
    tz = env.cfg.tz
    thu = datetime(2026, 11, 5, 12, 0, tzinfo=tz)  # Thursday
    d = env.db.get_drama(d.id)
    assert next_line(d, tz, thu) is None and "NEXT EPISODE" not in drama_card(d, tz=tz, now=thu)
    await env.send(msg_update(f"/edit {d.id} airdays Sat,Sun 20:00", ADMIN))
    assert "nextep" in last_text(env) and "airdays" not in last_text(env)
    await env.send(msg_update(f"/edit {d.id} nextep 2026-11-11 20:00", ADMIN))
    d = env.db.get_drama(d.id)
    assert (d.next_ep_date, d.air_time) == ("2026-11-11", "20:00")
    assert next_line(d, tz, thu) == "Ep 7 · Wed 20:00 (in 6 days)"
    assert ("🟨 <b>NEXT EPISODE</b>\n┃ <b>November 11, 2026</b> · 8:00 PM IST\n┃ <i>Ep 7 · Wed · in 6 days</i>"
            in drama_card(d, tz=tz, now=thu))
    assert "today" in drama_card(d, tz=tz, now=datetime(2026, 11, 11, 22, 0, tzinfo=tz))
    assert "NEXT EPISODE" not in drama_card(d, tz=tz, now=datetime(2026, 11, 12, 9, 0, tzinfo=tz))  # past
    await env.send(msg_update(f"/edit {d.id} nextep 2026-11-11", ADMIN))   # time optional
    d = env.db.get_drama(d.id)
    assert d.air_time is None
    assert "┃ <b>November 11, 2026</b>\n┃ <i>Ep 7 · Wed · in 6 days</i>" in drama_card(d, tz=tz, now=thu)
    for bad in ("11/11", "2026-11-11 25:00", "2026-13-01"):
        await env.send(msg_update(f"/edit {d.id} nextep {bad}", ADMIN))
        assert "date like 2026-11-11" in last_text(env)
    await env.send(msg_update(f"/edit {d.id} nextep -", ADMIN))
    assert env.db.get_drama(d.id).next_ep_date is None
    await env.send(msg_update(f"/edit {d.id} nextep 2026-11-11 20:00", ADMIN))
    await env.svc.add_episodes(d.id, {7: [("720p", "https://x/7", "part")]})
    d = env.db.get_drama(d.id)
    assert d.next_ep_date is None and d.air_time is None
    env.db.update_drama(d.id, next_ep_date="2026-11-11")
    assert "NEXT EPISODE" not in drama_card(env.db.update_drama(d.id, status="Completed"), tz=tz, now=thu)


async def test_daily_countdown_refresh_only_when_changed(env):
    d, _ = await _drama_on_channel(env, 2)
    env.db.update_drama(d.id, air_days="5", total_episodes=16)
    env.svc.now = datetime(2026, 11, 5, 1, 0, tzinfo=env.cfg.tz)
    assert await env.svc.refresh_countdowns() == 0          # airdays alone no longer does anything
    env.db.update_drama(d.id, next_ep_date="2026-11-07")
    cap = lambda: (env.req.of("editMessageCaption") + env.req.of("editMessageText"))[-1]
    cap_text = lambda: cap().get("caption") or cap().get("text")
    assert await env.svc.refresh_countdowns() == 1
    assert "in 2 days" in cap_text()
    assert await env.svc.refresh_countdowns() == 0
    env.svc.now += timedelta(days=1)
    assert await env.svc.refresh_countdowns() == 1
    assert "tomorrow" in cap_text()
    env.svc.now += timedelta(days=2)                         # date passed -> block removed
    assert await env.svc.refresh_countdowns() == 1
    assert "NEXT EPISODE" not in cap_text()
    assert await env.svc.refresh_countdowns() == 0
    env.db.update_drama(d.id, status="Completed")
    assert await env.svc.refresh_countdowns() == 0


# ---------- stats ----------
async def test_click_tracking_and_stats(env):
    d, chan = await _drama_on_channel(env, 3)
    await _started(env, VIEWER)
    for _ in range(3):
        await env.send(cb_update(f"ql:{d.id}:1:1:0", VIEWER, **chan))   # 1080p
    await env.send(cb_update(f"ql:{d.id}:2:0:0", VIEWER, **chan))       # 480p
    env.db.set_follow(VIEWER, d.id, True)
    await env.send(msg_update("/stats", ADMIN))
    t = last_text(env)
    assert "Top clicked (7d)" in t and "· 4" in t
    assert "Most-used quality</b>: 1080p (3 in 7d)" in t
    assert "Followers</b>: 1 follows" in t and "Users</b>: 2 total, +2 in 7d" in t
    assert "Requests: 0" in t


async def test_weekly_summary_job_and_dm(env):
    class JQ:
        def __init__(self): self.daily = []
        def run_daily(self, cb, time, days=None, name=None): self.daily.append((name, time, days))
        def run_once(self, *a, **k): pass
    env.app.bot_data["cfg"] = env.cfg
    jq = JQ()
    app = type("A", (), {"bot_data": env.app.bot_data, "job_queue": jq})()
    jobs.setup_jobs(app)
    w = [x for x in jq.daily if x[0] == "weekly_summary"][0]
    assert w[2] == (0,) and (w[1].hour, w[1].minute) == (10, 0)
    assert "daily_countdown" in [x[0] for x in jq.daily]
    await env.svc.weekly_summary()
    assert "Weekly summary" in [p for p in env.req.of("sendMessage") if p["chat_id"] == ADMIN][-1]["text"]
