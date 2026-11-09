"""Season support: migration, newseason, addep, complete, browse picker, alerts."""
from datetime import datetime

import pytest
import sqlite3

from db import Database
from services import drama_card
from tests.conftest import ADMIN, CHANNEL, VIEWER
from tests.fakes import cb_update, msg_update
from tests.test_bot import last_text
from tests.test_features import answers
from tests.test_quality import _drama_on_channel, flat, wizard

async def _started(env, uid):
    await env.send(msg_update("/start", uid))


def _multi(env, d):
    """Turn a single-season drama into S1 complete + S2 ongoing with 5 eps."""
    env.db.update_season(d.id, 1, status="Completed", total_episodes=16)
    # pad S1 to 16 if needed is heavy; just mark complete with whatever it has
    sea = env.db.add_season(d.id, 16)
    assert sea.number == 2
    env.db.add_episodes(d.id, {i: [("720p", f"https://s2/{i}", "part")] for i in range(1, 6)}, season=2)
    return env.db.get_drama(d.id)


# ---------- migration ----------
def test_migration_backfills_season_1(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("create table dramas (id integer primary key, title varchar(200), poster varchar(500), "
              "synopsis text, genres varchar(300), year integer, status varchar(20), total_episodes integer, "
              "deleted boolean, created_at datetime, updated_at datetime)")
    c.execute("create table episodes (id integer primary key, drama_id integer, number integer, "
              "url varchar(1000), created_at datetime)")
    c.execute("insert into dramas (title, synopsis, genres, status, total_episodes, deleted) "
              "values ('Legacy', '', 'Romance', 'Ongoing', 16, 0)")
    c.execute("insert into episodes (drama_id, number, url) values (1, 1, 'https://x/1'), (1, 2, 'https://x/2')")
    c.commit(); c.close()
    db = Database(f"sqlite:///{p}")
    d = db.get_drama(1)
    assert len(d.seasons) == 1 and d.seasons[0].number == 1
    assert d.seasons[0].status == "Ongoing" and d.seasons[0].total_episodes == 16
    assert [e.number for e in d.seasons[0].episodes] == [1, 2]
    assert not d.is_multi and d.current.number == 1
    db2 = Database(f"sqlite:///{p}")  # idempotent
    assert len(db2.get_drama(1).seasons) == 1


# ---------- card: single unchanged, multi shows seasons ----------
async def test_single_season_card_unchanged(env):
    d, _ = await _drama_on_channel(env, 3)
    env.db.update_drama(d.id, total_episodes=16, imdb="8.6")
    d = env.db.get_drama(d.id)
    c = drama_card(d)
    assert "<b>Episodes</b> · <code>3/16</code>" in c
    assert "Seasons" not in c and "S1 ·" not in c
    post = [p for p in env.req.of("sendPhoto") + env.req.of("sendMessage")
            if p.get("chat_id") == CHANNEL and p.get("reply_markup")][-1]
    assert flat(post["reply_markup"])[0]["callback_data"] == f"eps:{d.id}:0"
    assert flat(post["reply_markup"])[0]["text"].startswith("▶️ Browse & Download")


async def test_multi_season_card_and_channel_button(env):
    d, _ = await _drama_on_channel(env, 16)
    env.db.update_drama(d.id, total_episodes=16)
    await env.send(msg_update(f"/complete {d.id}", ADMIN))
    await env.send(msg_update(f"/newseason {d.id} 16", ADMIN))
    for i in range(1, 6):
        await env.svc.add_episodes(d.id, {i: [("720p", f"https://s2/{i}", "part")]}, season=2)
    d = env.db.get_drama(d.id)
    c = drama_card(d)
    assert "<b>Seasons</b> · <code>2</code>" in c
    assert "<b>Episodes</b> · <code>S2 · 5/16</code>" in c
    assert d.status == "Ongoing" and d.season(1).status == "Completed"
    # channel card keyboard now opens the season picker
    await env.svc.refresh_card(d.id)
    edits = (env.req.of("editMessageReplyMarkup") + env.req.of("editMessageCaption")
             + env.req.of("editMessageText") + env.req.of("editMessageMedia"))
    with_kb = [e for e in edits if e.get("reply_markup")]
    assert with_kb, "refresh_card should send a keyboard"
    kb = flat(with_kb[-1]["reply_markup"])
    assert kb[0]["callback_data"] == f"sea:{d.id}" and "2 seasons" in kb[0]["text"]


# ---------- admin: newseason / addep / complete ----------
async def test_newseason_addep_with_and_without_season(env):
    d, _ = await _drama_on_channel(env, 2)
    env.db.update_drama(d.id, total_episodes=2)
    await env.send(msg_update(f"/complete {d.id}", ADMIN))
    assert env.db.get_drama(d.id).status == "Completed"
    await env.send(msg_update(f"/newseason {d.id} 16", ADMIN))
    d = env.db.get_drama(d.id)
    assert d.status == "Ongoing" and d.current.number == 2 and d.current.total_episodes == 16
    assert d.next_ep_date is None
    # default /addep goes to current (S2)
    await env.send(msg_update(f"/addep {d.id}\n720p: https://a/{{ep}} 1 2", ADMIN))
    d = env.db.get_drama(d.id)
    assert [e.number for e in d.season(2).episodes] == [1, 2]
    assert [e.number for e in d.season(1).episodes] == [1, 2]
    # explicit season
    await env.send(msg_update(f"/addep {d.id} s2\n720p: https://a/{{ep}} 3 4", ADMIN))
    assert [e.number for e in env.db.get_drama(d.id).season(2).episodes] == [1, 2, 3, 4]
    await env.send(msg_update(f"/edit {d.id} s2 total 20", ADMIN))
    assert env.db.get_drama(d.id).season(2).total_episodes == 20
    await env.send(msg_update(f"/addep {d.id} s9\n720p: https://x/1", ADMIN))
    assert "no Season 9" in last_text(env)


async def test_complete_per_season_then_drama(env):
    d, _ = await _drama_on_channel(env, 1)
    await env.send(msg_update(f"/newseason {d.id}", ADMIN))
    await env.send(msg_update(f"/complete {d.id} s1", ADMIN))
    d = env.db.get_drama(d.id)
    assert d.season(1).status == "Completed" and d.status == "Ongoing"
    assert "Season 1 completed" in last_text(env)
    await env.send(msg_update(f"/complete {d.id}", ADMIN))  # current = S2
    d = env.db.get_drama(d.id)
    assert d.status == "Completed" and d.season(2).status == "Completed"
    assert "fully COMPLETED" in last_text(env)


async def test_delete_season_asks_confirmation(env):
    d, _ = await _drama_on_channel(env, 1)
    await env.send(msg_update(f"/newseason {d.id}", ADMIN))
    await env.send(msg_update(f"/delete {d.id} s1", ADMIN))
    assert "Delete" in last_text(env) and "Season 1" in last_text(env)
    kb = flat(env.req.of("sendMessage")[-1]["reply_markup"])
    assert kb[0]["callback_data"] == f"delok:{d.id}:1"
    await env.send(cb_update(f"delok:{d.id}:1", ADMIN))
    d = env.db.get_drama(d.id)
    assert len(d.seasons) == 1 and d.seasons[0].number == 2
    await env.send(msg_update(f"/delete {d.id} s2", ADMIN))
    assert "only season" in last_text(env)


# ---------- browse ----------
async def test_browse_season_picker_and_single_path(env):
    d, _ = await _drama_on_channel(env, 3)
    await _started(env, VIEWER)
    # single-season: channel eps: tap DMs episode list (no picker)
    card = env.db.card_post(d.id)
    await env.send(cb_update(f"eps:{d.id}:0", VIEWER, chat_id=CHANNEL,
                             message_id=card.message_id, chat_type="channel"))
    dm = [p for p in env.req.of("sendMessage") + env.req.of("sendPhoto") if p.get("chat_id") == VIEWER][-1]
    texts = [b["text"] for b in flat(dm["reply_markup"])]
    assert any(t.startswith("EP ") for t in texts)
    assert not any("Season " in t for t in texts)

    # multi-season: private open shows picker; picking a season shows its episodes
    d = _multi(env, d)
    await env.svc.refresh_card(d.id)
    await env.send(cb_update(f"dr:{d.id}", VIEWER))
    dm = [p for p in env.req.of("sendMessage") + env.req.of("sendPhoto") if p.get("chat_id") == VIEWER][-1]
    btns = flat(dm["reply_markup"])
    assert btns[0]["text"].startswith("🔄 Season 1") or btns[0]["text"].startswith("✅ Season 1")
    assert btns[1]["callback_data"] == f"eps:{d.id}:2:0"
    await env.send(cb_update(f"eps:{d.id}:2:0", VIEWER))
    eps_kb = flat(env.req.of("editMessageReplyMarkup")[-1]["reply_markup"])
    assert any(b.get("text") == "EP 5" for b in eps_kb)
    assert any(b.get("callback_data") == f"back:{d.id}:sea" for b in eps_kb)  # back to picker
    await env.send(cb_update(f"back:{d.id}:sea", VIEWER))
    assert flat(env.req.of("editMessageReplyMarkup")[-1]["reply_markup"])[0]["callback_data"].startswith("eps:")


async def test_search_returns_drama_once(env):
    d, _ = await _drama_on_channel(env, 1)
    await env.send(msg_update(f"/newseason {d.id}", ADMIN))
    await env.send(msg_update(f"/search {d.title}", VIEWER))
    kb = flat(env.req.of("sendMessage")[-1]["reply_markup"])
    hits = [b for b in kb if b.get("callback_data") == f"dr:{d.id}"]
    assert len(hits) == 1


# ---------- alerts ----------
async def test_newseason_follower_dm(env):
    d, _ = await _drama_on_channel(env, 1)
    await _started(env, VIEWER)
    env.db.set_follow(VIEWER, d.id, True)
    await env.send(msg_update(f"/newseason {d.id} 16", ADMIN))
    dms = [p for p in env.req.of("sendMessage") if p.get("chat_id") == VIEWER]
    assert any("Season 2 is here" in (p.get("text") or "") for p in dms)
    await env.svc.add_episodes(d.id, {1: [("720p", "https://z/1", "part")]}, season=2)
    dms = [p for p in env.req.of("sendMessage") if p.get("chat_id") == VIEWER]
    assert any("S2" in (p.get("text") or "") and "just landed" in (p.get("text") or "") for p in dms)


async def test_list_and_stats_show_seasons(env):
    d, _ = await _drama_on_channel(env, 2)
    await env.send(msg_update(f"/newseason {d.id}", ADMIN))
    await env.send(msg_update("/list", ADMIN))
    assert "2 seasons" in last_text(env)
    await env.send(msg_update("/stats", ADMIN))
    assert "Seasons:" in last_text(env)


async def test_nextep_cleared_on_newseason(env):
    d, _ = await _drama_on_channel(env, 2)
    env.db.update_drama(d.id, total_episodes=16, next_ep_date="2026-11-11", air_time="20:00")
    await env.send(msg_update(f"/newseason {d.id}", ADMIN))
    d = env.db.get_drama(d.id)
    assert d.next_ep_date is None and d.air_time is None
