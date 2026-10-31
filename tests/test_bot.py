from datetime import datetime, timedelta, timezone

import pytest

import jobs
from db import Post, utcnow
from keyboards import episodes_keyboard
from services import drama_card
from tests.conftest import ADMIN, CHANNEL, VIEWER
from tests.fakes import cb_update, msg_update
from utils import parse_links, parse_local_dt

pytestmark = pytest.mark.asyncio


def last_text(env, method="sendMessage"):
    return env.req.of(method)[-1].get("text") or env.req.of(method)[-1].get("caption")


async def add_drama_via_wizard(env, title="Queen of <Tears>", links="https://example.com/qot/{ep}.mp4 1"):
    s = env.send
    await s(msg_update("/add", ADMIN))
    await s(msg_update(title, ADMIN))
    await s(msg_update(photo=True, user_id=ADMIN))
    await s(msg_update("A chaebol heiress & her husband… <b>drama</b>", ADMIN))
    await s(msg_update("romance, comedy", ADMIN))
    await s(msg_update("2024", ADMIN))
    await s(msg_update("/skip", ADMIN))  # audio
    await s(cb_update("st:Ongoing", ADMIN))
    await s(msg_update("16", ADMIN))
    await s(msg_update(links, ADMIN))
    return env.db.find_drama(title)


# ---------- pure helpers ----------
async def test_parse_links_variants():
    assert parse_links("https://a/1\nhttps://a/2") == (["https://a/1", "https://a/2"], None)
    links, start = parse_links("https://x/{ep}.mp4 3", total=5)
    assert links == ["https://x/3.mp4", "https://x/4.mp4", "https://x/5.mp4"] and start == 3
    assert parse_links("https://x/{ep}.mp4 2 3")[0] == ["https://x/2.mp4", "https://x/3.mp4"]
    with pytest.raises(ValueError):
        parse_links("not a link")


async def test_schedule_time_parsing_is_ist(cfg):
    utc, a, b = parse_local_dt("Drama 2026-11-01 20:00 hello", cfg.tz)
    assert utc == datetime(2026, 11, 1, 14, 30)


# ---------- permissions ----------
@pytest.mark.parametrize("cmd", ["/add", "/addep x", "/complete x", "/edit 1 year 2020", "/delete x",
                                 "/list", "/stats", "/schedule x 2030-01-01 10:00 hi", "/cleanup"])
async def test_non_admin_blocked(env, cmd):
    await env.send(msg_update(cmd, VIEWER))
    assert "only the kdrama_heaven admins" in last_text(env)
    assert not env.req.of("sendPhoto")


# ---------- wizard ----------
async def test_add_wizard_posts_card_and_saves(env):
    d = await add_drama_via_wizard(env)
    assert d and d.year == 2024 and d.status == "Ongoing" and d.total_episodes == 16
    assert d.genres == "Romance, Comedy" and d.poster == "POSTER_FILE_ID"
    assert [e.number for e in d.episodes] == list(range(1, 17))
    photo = env.req.of("sendPhoto")[-1]
    assert photo["chat_id"] == CHANNEL and photo["parse_mode"] == "HTML"
    cap = photo["caption"]
    assert "Queen of &lt;Tears&gt;" in cap and "&lt;b&gt;drama&lt;/b&gt;" in cap and "ONGOING 🔄" in cap
    kb = photo["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["callback_data"] == f"eps:{d.id}:0"
    assert "start=request" in kb[1][0]["url"]
    assert env.db.card_post(d.id).is_photo


async def test_wizard_validation_and_skip(env):
    s = env.send
    await s(msg_update("/add", ADMIN))
    await s(msg_update("No Poster Show", ADMIN))
    await s(msg_update("/skip", ADMIN))
    await s(msg_update("/skip", ADMIN))
    await s(msg_update("/skip", ADMIN))
    await s(msg_update("nineteen", ADMIN))
    assert "4-digit year" in last_text(env)
    await s(msg_update("/skip", ADMIN))
    await s(msg_update("/skip", ADMIN))  # audio
    await s(cb_update("st:Completed", ADMIN))
    await s(msg_update("/skip", ADMIN))
    await s(msg_update("bad link", ADMIN))
    assert "valid http" in last_text(env)
    await s(msg_update("https://e.com/1\nhttps://e.com/2", ADMIN))
    d = env.db.find_drama("No Poster Show")
    assert d.status == "Completed" and len(d.episodes) == 2 and not d.poster
    assert env.db.card_post(d.id).is_photo is False


async def test_cancel(env):
    await env.send(msg_update("/add", ADMIN))
    await env.send(msg_update("/cancel", ADMIN))
    assert "Cancelled" in last_text(env)


# ---------- episodes / edit in place ----------
async def test_addep_edits_post_and_announces(env):
    d = await add_drama_via_wizard(env, links="https://e.com/{ep} 1 8")
    card = env.db.card_post(d.id)
    await env.send(msg_update(f"/addep {d.id}", ADMIN))
    await env.send(msg_update("https://e.com/9\nhttps://e.com/10", ADMIN))
    edit = env.req.of("editMessageCaption")[-1]
    assert edit["message_id"] == card.message_id and "<b>Episodes</b> · <code>10/16</code>" in edit["caption"]
    ann = env.req.of("sendMessage")[-2]
    assert ann["chat_id"] == CHANNEL and "New episodes" in ann["text"] and "EP 9–10" in ann["text"]
    # inline form
    await env.send(msg_update("/addep queen of\nhttps://e.com/{ep} 11 12", ADMIN))
    assert len(env.db.get_drama(d.id).episodes) == 12


async def test_complete_and_edit(env):
    d = await add_drama_via_wizard(env)
    await env.send(msg_update(f"/complete {d.title}", ADMIN))
    assert "COMPLETED ✅" in env.req.of("editMessageCaption")[-1]["caption"]
    assert env.db.get_drama(d.id).status == "Completed"
    await env.send(msg_update(f"/edit {d.id} title Queen of Tears", ADMIN))
    assert "Queen of Tears" in env.req.of("editMessageCaption")[-1]["caption"]
    await env.send(msg_update(f"/edit {d.id} year abc", ADMIN))
    assert "needs a number" in last_text(env)


async def test_episode_pagination(env):
    d = await add_drama_via_wizard(env, links="https://e.com/{ep} 1 23")
    k = episodes_keyboard(env.db.get_drama(d.id), 0).to_dict()["inline_keyboard"]
    flat = [b for row in k for b in row]
    assert [b["text"] for b in flat if b["text"].startswith("EP")] == [f"EP {i}" for i in range(1, 11)]
    assert any(b["text"] == "Next ➡️" for b in flat) and not any(b["text"] == "⬅️ Prev" for b in flat)
    last = [b for row in episodes_keyboard(d, 2).to_dict()["inline_keyboard"] for b in row]
    assert [b["text"] for b in last if b["text"].startswith("EP")] == ["EP 21", "EP 22", "EP 23"]
    # tapping in the channel never edits the shared post; the viewer gets a private copy in DM
    card = env.db.card_post(d.id)
    before = len(env.req.of("editMessageReplyMarkup"))
    await env.send(cb_update(f"eps:{d.id}:1", VIEWER, chat_id=CHANNEL, message_id=card.message_id, chat_type="channel"))
    assert len(env.req.of("editMessageReplyMarkup")) == before
    dm = [m for m in env.req.of("sendMessage") + env.req.of("sendPhoto") if m["chat_id"] == VIEWER][-1]
    assert dm["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://e.com/11"
    assert "Sent to your private chat" in env.req.of("answerCallbackQuery")[-1]["text"]
    await env.send(cb_update(f"back:{d.id}", VIEWER, chat_id=CHANNEL, message_id=card.message_id, chat_type="channel"))
    assert len(env.req.of("editMessageReplyMarkup")) == before


async def test_delete_list_stats(env):
    d1 = await add_drama_via_wizard(env, title="Alpha")
    d2 = await add_drama_via_wizard(env, title="Beta")
    await env.send(msg_update("/complete Beta", ADMIN))
    await env.send(msg_update("/stats", ADMIN))
    t = last_text(env)
    assert "Dramas: 2" in t and "1 ongoing" in t and "1 completed" in t and "Episodes: 32" in t
    await env.send(msg_update("/delete Alpha", ADMIN))
    assert env.req.of("deleteMessage")[-1]["message_id"] == env.db.session().get(Post, 1).message_id
    assert env.db.find_drama("Alpha") is None
    for i in range(12):
        env.db.add_drama(title=f"Extra {i:02d}")
    await env.send(msg_update("/list", ADMIN))
    m = env.req.of("sendMessage")[-1]
    assert "Dramas</b> (13)" in m["text"]
    assert m["reply_markup"]["inline_keyboard"][-2][-1]["callback_data"] == "list:1"
    await env.send(cb_update("list:1", ADMIN))
    assert "Dramas</b> (13)" in env.req.of("editMessageText")[-1]["text"]


# ---------- browse / search / request ----------
async def test_browse_and_search(env):
    await add_drama_via_wizard(env, title="Lovely Runner")
    env.db.add_drama(title="Moving", genres="Action, Fantasy", year=2023, status="Completed")
    await env.send(msg_update("/start", VIEWER))
    assert env.req.of("sendMessage")[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "br:search:0"
    await env.send(cb_update("br:completed:0", VIEWER))
    kb = env.req.of("editMessageText")[-1]["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["text"].endswith("Moving (2023)")
    await env.send(cb_update("br:genres:0", VIEWER))
    assert "br:genre:0:" in env.req.of("editMessageText")[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    for q, expect in [("/search lovely", "Lovely Runner"), ("/search 2023", "Moving"), ("/search fantasy", "Moving")]:
        await env.send(msg_update(q, VIEWER))
        assert expect in env.req.of("sendMessage")[-1]["reply_markup"]["inline_keyboard"][0][0]["text"]
    d = env.db.find_drama("Moving")
    await env.send(cb_update(f"dr:{d.id}", VIEWER))
    assert "Moving" in env.req.of("sendMessage")[-1]["text"]


async def test_request_forwarded_to_admin(env):
    await env.send(msg_update("/start request", VIEWER))
    await env.send(msg_update("Please add Crash Landing on You <3", VIEWER))
    dm = [p for p in env.req.of("sendMessage") if p["chat_id"] == ADMIN][-1]
    assert "Drama request" in dm["text"] and "&lt;3" in dm["text"]
    assert "Thanks" in last_text(env)


# ---------- scheduling ----------
async def test_schedule_one_minute_ahead_runs(env):
    d = await add_drama_via_wizard(env)
    when_local = (datetime.now(timezone.utc) + timedelta(minutes=1)).astimezone(env.cfg.tz)
    await env.send(msg_update(f"/schedule {d.id} {when_local:%Y-%m-%d %H:%M} EP 9 tonight!", ADMIN))
    assert "Scheduled #1" in last_text(env)
    job = env.app.job_queue.get_jobs_by_name("schedule:1")[0]
    sc = env.db.get_schedule(1)
    assert abs((job.job.trigger.run_date.astimezone(timezone.utc).replace(tzinfo=None) - sc.run_at).total_seconds()) < 1
    await job.run(env.app)  # simulate the clock reaching run time
    assert "EP 9 tonight!" in last_text(env) and env.req.of("sendMessage")[-1]["chat_id"] == CHANNEL
    assert env.db.get_schedule(1).status == "sent"
    await env.svc.run_schedule(1)  # idempotent
    assert sum("EP 9 tonight!" in p["text"] for p in env.req.of("sendMessage")) == 1


async def test_schedules_persist_and_restore(env):
    sc = env.db.add_schedule(utcnow() + timedelta(hours=2), "later")
    past = env.db.add_schedule(utcnow() - timedelta(hours=2), "missed while offline")
    jobs.setup_jobs(env.app)
    names = {j.name for j in env.app.job_queue.jobs()}
    assert {"daily_digest", "daily_cleanup", f"schedule:{sc.id}", f"schedule:{past.id}"} <= names
    digest = env.app.job_queue.get_jobs_by_name("daily_digest")[0]
    nt = digest.trigger if hasattr(digest, "trigger") else digest.job.trigger
    assert "hour='10'" in repr(nt) and "Asia/Kolkata" in repr(nt)


async def test_schedule_past_rejected(env):
    await env.send(msg_update("/schedule - 2020-01-01 10:00 old", ADMIN))
    assert "past" in last_text(env)


async def test_daily_digest(env):
    await add_drama_via_wizard(env, links="https://e.com/{ep} 1 3")
    msg = await env.svc.daily_digest()
    t = env.req.of("sendMessage")[-1]["text"]
    assert msg and "New episodes today" in t and "EP 1–3" in t


# ---------- cleanup ----------
async def test_cleanup_old_service_and_deleted(env):
    d = await add_drama_via_wizard(env)
    await env.svc.add_episodes(d.id, ["https://e.com/17"])
    with env.db.session() as s:
        svc_post = s.query(Post).filter_by(kind="service").one()
        svc_post.created_at = utcnow() - timedelta(days=8)
        s.commit()
        svc_id, svc_msg = svc_post.id, svc_post.message_id
    fresh = await env.svc.add_episodes(d.id, ["https://e.com/18"])
    other = env.db.add_drama(title="Gone")
    await env.svc.post_card(other)
    env.db.mark_deleted(other.id)  # deleted drama whose post is still up
    other_msg = env.db.card_post(other.id).message_id
    await env.send(msg_update("/cleanup", ADMIN))
    deleted = {p["message_id"] for p in env.req.of("deleteMessage")}
    assert svc_msg in deleted and other_msg in deleted
    assert env.db.card_post(d.id) is not None  # live card untouched
    assert "Removed 2" in last_text(env)
    await env.svc.cleanup()
    assert len(env.req.of("deleteMessage")) == 2  # nothing left


async def test_flood_wait_retry(env, monkeypatch):
    import utils
    slept = []

    async def fake_sleep(s):
        slept.append(s)
    monkeypatch.setattr(utils.asyncio, "sleep", fake_sleep)
    env.req.fail_next["sendMessage"] = {"ok": False, "error_code": 429, "description": "Too Many Requests",
                                        "parameters": {"retry_after": 3}}
    await env.svc._send("hello", "service")
    assert slept and slept[0] >= 3 and env.req.of("sendMessage")[-1]["text"] == "hello"


async def test_caption_truncated():
    from db import Drama
    d = Drama(id=1, title="T", synopsis="<x>" * 1000, genres="A", status="Ongoing")
    d.episodes = []
    assert len(drama_card(d)) <= 1024
