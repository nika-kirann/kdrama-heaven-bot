import sqlite3

import pytest

from db import Database
from keyboards import episodes_keyboard, links_keyboard, quality_keyboard
from tests.conftest import ADMIN, CHANNEL, VIEWER
from tests.fakes import cb_update, msg_update
from utils import parse_quality_links

pytestmark = pytest.mark.asyncio

MIXED = """480p: https://a.com/1.mp4
480p: https://a.com/2.mp4
720p
https://b.com/1-part1, https://b.com/1-part2
https://b.com/2.mp4
1080p: https://c.com/{ep}.mkv 1 2
4k: https://m1.com/1 | https://m2.com/1"""


def flat(markup):
    d = markup if isinstance(markup, dict) else markup.to_dict()
    return [b for row in d["inline_keyboard"] for b in row]


# ---------- parsing ----------
async def test_parse_mixed_formats():
    eps = parse_quality_links(MIXED)
    assert sorted(eps) == [1, 2]
    e1 = eps[1]
    assert ("480p", "https://a.com/1.mp4", "part") in e1
    assert [u for q, u, k in e1 if q == "720p"] == ["https://b.com/1-part1", "https://b.com/1-part2"]
    assert ("1080p", "https://c.com/1.mkv", "part") in e1
    assert [(q, k) for q, u, k in e1 if q == "4K"] == [("4K", "mirror"), ("4K", "mirror")]
    assert [q for q, *_ in eps[2]] == ["480p", "720p", "1080p"]


@pytest.mark.parametrize("text,expect", [
    ("https://x/1\nhttps://x/2", {1: [("HD", "https://x/1", "part")], 2: [("HD", "https://x/2", "part")]}),
    ("https://x/{ep}.mp4 2 3", {2: [("HD", "https://x/2.mp4", "part")], 3: [("HD", "https://x/3.mp4", "part")]}),
    ("520p: https://y/1", {1: [("520p", "https://y/1", "part")]}),
    ("720P = https://y/1", {1: [("720p", "https://y/1", "part")]}),
    ("EP 9\n1080p: https://z/9\n480p: https://w/9", {9: [("1080p", "https://z/9", "part"), ("480p", "https://w/9", "part")]}),
])
async def test_parse_legacy_and_custom(text, expect):
    assert parse_quality_links(text) == expect


async def test_parse_pattern_defaults_to_total_and_start():
    eps = parse_quality_links("1080p: https://c/{ep}.mkv", total=3)
    assert sorted(eps) == [1, 2, 3]
    eps = parse_quality_links("720p: https://c/{ep}.mkv", start=7)
    assert list(eps) == [7]


@pytest.mark.parametrize("bad", ["bad link", "480p: notaurl", "720p: https://x/{ep} 5 2", "480p"])
async def test_parse_errors(bad):
    with pytest.raises(ValueError):
        parse_quality_links(bad)


# ---------- wizard + navigation ----------
async def wizard(env, links=MIXED, title="Lovely Runner"):
    s = env.send
    for step in ["/add", title, "/skip", "/skip", "/skip", "/skip", "/skip"]:
        await s(msg_update(step, ADMIN))
    await s(cb_update("st:Ongoing", ADMIN))
    await s(msg_update("2", ADMIN))
    await s(msg_update(links, ADMIN))
    return env.db.find_drama(title)


async def test_wizard_with_qualities_and_navigation(env):
    d = await wizard(env)
    assert [e.number for e in d.episodes] == [1, 2]
    ep1 = d.episodes[0]
    assert [q for q, _ in ep1.quality_groups()] == ["480p", "720p", "1080p", "4K"]
    card = [p for p in env.req.of("sendMessage") if p["chat_id"] == CHANNEL][0]
    assert card["chat_id"] == CHANNEL and "<b>Quality</b> · <code>480p 720p 1080p 4K</code>" in card["text"]
    post = env.db.card_post(d.id)
    chan = dict(chat_id=CHANNEL, message_id=post.message_id, chat_type="channel")

    # channel tap -> private copy in the viewer's DM, channel post untouched
    before = len(env.req.of("editMessageReplyMarkup"))
    await env.send(cb_update(f"eps:{d.id}:0", VIEWER, **chan))
    assert len(env.req.of("editMessageReplyMarkup")) == before
    dm = env.req.of("sendMessage")[-1]
    assert dm["chat_id"] == VIEWER
    eb = flat(dm["reply_markup"])
    assert eb[0]["callback_data"] == f"ep:{d.id}:1:0"
    chan = dict(chat_id=VIEWER, message_id=101, chat_type="private")  # all further taps happen in the DM

    # EP 1 -> quality keyboard, edited in place on the private message
    await env.send(cb_update(f"ep:{d.id}:1:0", VIEWER, **chan))
    e = env.req.of("editMessageReplyMarkup")[-1]
    assert e["message_id"] == 101 and e["chat_id"] == VIEWER
    qb = flat(e["reply_markup"])
    labels = [b["text"] for b in qb]
    assert labels[:4] == ["🎞 480p", "🎞 720p (2 parts)", "🎞 1080p", "🎞 4K (2 mirrors)"]
    assert qb[0]["url"] == "https://a.com/1.mp4" and qb[2]["url"] == "https://c.com/1.mkv"
    assert qb[-1]["callback_data"] == f"eps:{d.id}:0"

    # multi-part
    await env.send(cb_update(qb[1]["callback_data"], VIEWER, **chan))
    pb = flat(env.req.of("editMessageReplyMarkup")[-1]["reply_markup"])
    assert [(b["text"], b.get("url")) for b in pb[:2]] == [("720p Part 1", "https://b.com/1-part1"),
                                                          ("720p Part 2", "https://b.com/1-part2")]
    assert pb[-1]["callback_data"] == f"ep:{d.id}:1:0"
    # multi-mirror
    await env.send(cb_update(qb[3]["callback_data"], VIEWER, **chan))
    mb = flat(env.req.of("editMessageReplyMarkup")[-1]["reply_markup"])
    assert [b["text"] for b in mb[:2]] == ["4K Mirror 1", "4K Mirror 2"]
    # back to card keeps Request/Search
    await env.send(cb_update(f"back:{d.id}", VIEWER, **chan))
    bb = flat(env.req.of("editMessageReplyMarkup")[-1]["reply_markup"])
    assert "start=request" in bb[1]["url"] and "start=browse" in bb[2]["url"]


async def test_pagination_with_qualities(env):
    d = await wizard(env, links="480p: https://a/{ep} 1 23\n1080p: https://c/{ep} 1 23")
    k = flat(episodes_keyboard(d, 2))
    assert [b["text"] for b in k if b["text"].startswith("EP")] == ["EP 21", "EP 22", "EP 23"]
    assert any(b["text"] == "⬅️ Prev" for b in k)
    qk = flat(quality_keyboard(d, 22, 2))
    assert qk[1]["url"] == "https://c/22" and qk[-1]["callback_data"] == f"eps:{d.id}:2"
    assert links_keyboard(d, 99, 0) is None and quality_keyboard(d, 99) is None


async def test_addep_with_qualities_edits_post(env):
    d = await wizard(env)
    post = env.db.card_post(d.id)
    await env.send(msg_update(f"/addep {d.id}", ADMIN))
    await env.send(msg_update("480p: https://a.com/3.mp4\n1080p: https://c.com/3.mkv | https://m.com/3.mkv", ADMIN))
    d = env.db.get_drama(d.id)
    ep3 = d.episodes[-1]
    assert ep3.number == 3 and [q for q, _ in ep3.quality_groups()] == ["480p", "1080p"]
    edit = env.req.of("editMessageCaption") or env.req.of("editMessageText")
    assert edit[-1]["message_id"] == post.message_id and "<b>Episodes</b> · <code>3" in (edit[-1].get("text") or edit[-1].get("caption"))
    ann = [p for p in env.req.of("sendMessage") if p["chat_id"] == CHANNEL][-1]
    assert "New episodes" in ann["text"] and "EP 3 (480p, 1080p)" in ann["text"]
    # add a missing quality to an existing episode with an EP header; others kept
    await env.send(msg_update(f"/addep {d.id}\nEP 3\n720p: https://b.com/3.mp4", ADMIN))
    ep3 = env.db.get_drama(d.id).episodes[-1]
    assert [q for q, _ in ep3.quality_groups()] == ["480p", "1080p", "720p"]
    assert len(env.db.get_drama(d.id).episodes) == 3


async def test_edit_links_and_quality(env):
    d = await wizard(env)
    await env.send(msg_update(f"/edit {d.id} links\nEP 2\n480p: https://new.com/2.mp4", ADMIN))
    ep2 = env.db.get_drama(d.id).episodes[1]
    assert dict(ep2.quality_groups())["480p"][0].url == "https://new.com/2.mp4"
    assert "720p" in dict(ep2.quality_groups())  # untouched quality kept
    await env.send(msg_update(f"/edit {d.id} quality 4k 2160p", ADMIN))
    assert "Renamed 2 4K links → 2160p" in env.req.of("sendMessage")[-1]["text"]
    await env.send(msg_update(f"/edit {d.id} quality 1080p -", ADMIN))
    d2 = env.db.get_drama(d.id)
    assert all("1080p" not in dict(e.quality_groups()) for e in d2.episodes)
    last_edit = (env.req.of("editMessageCaption") + env.req.of("editMessageText"))[-1]
    assert "2160p" in (last_edit.get("text") or last_edit.get("caption")) and "1080p" not in (last_edit.get("text") or last_edit.get("caption"))
    await env.send(msg_update("/stats", ADMIN))
    assert "Links per quality: 480p 2, 720p 3, 2160p 2" in env.req.of("sendMessage")[-1]["text"]


async def test_non_admin_still_blocked(env):
    for cmd in ["/addep 1\n480p: https://x/1", "/edit 1 links\n480p: https://x/1", "/edit 1 quality 4k 8k"]:
        await env.send(msg_update(cmd, VIEWER))
        assert "only the kdrama_heaven admins" in env.req.of("sendMessage")[-1]["text"]


# ---------- migration / backward compatibility ----------
OLD_SCHEMA = """
CREATE TABLE dramas (id INTEGER NOT NULL, title VARCHAR(200) NOT NULL, poster VARCHAR(500), synopsis TEXT NOT NULL,
 genres VARCHAR(300) NOT NULL, year INTEGER, status VARCHAR(20) NOT NULL, total_episodes INTEGER, deleted BOOLEAN NOT NULL,
 created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, PRIMARY KEY (id));
CREATE TABLE requests (id INTEGER NOT NULL, user_id INTEGER NOT NULL, username VARCHAR(100), text TEXT NOT NULL,
 created_at DATETIME NOT NULL, PRIMARY KEY (id));
CREATE TABLE episodes (id INTEGER NOT NULL, drama_id INTEGER NOT NULL, number INTEGER NOT NULL, url VARCHAR(1000) NOT NULL,
 created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(drama_id) REFERENCES dramas (id));
CREATE TABLE posts (id INTEGER NOT NULL, drama_id INTEGER, chat_id VARCHAR(100) NOT NULL, message_id INTEGER NOT NULL,
 kind VARCHAR(20) NOT NULL, is_photo BOOLEAN NOT NULL, removed BOOLEAN NOT NULL, created_at DATETIME NOT NULL,
 PRIMARY KEY (id), FOREIGN KEY(drama_id) REFERENCES dramas (id));
CREATE TABLE schedules (id INTEGER NOT NULL, drama_id INTEGER, run_at DATETIME NOT NULL, text TEXT NOT NULL,
 status VARCHAR(20) NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), FOREIGN KEY(drama_id) REFERENCES dramas (id));
INSERT INTO dramas VALUES (1,'Old Show',NULL,'syn','Romance',2023,'Ongoing',16,0,'2026-10-30 10:00:00','2026-10-30 10:00:00');
INSERT INTO episodes VALUES (1,1,1,'https://old.com/1.mp4','2026-10-30 10:00:00');
INSERT INTO episodes VALUES (2,1,2,'https://old.com/2.mp4','2026-10-30 10:00:00');
INSERT INTO posts VALUES (1,1,'-1001234567890',55,'card',0,0,'2026-10-30 10:00:00');
"""


async def test_migration_from_old_schema(tmp_path, cfg):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.close()
    db = Database(f"sqlite:///{path}")  # create_all adds episode_links, leaves old tables intact
    d = db.find_drama("Old Show")
    groups = d.episodes[0].quality_groups()
    assert groups[0][0] == "HD" and groups[0][1][0].url == "https://old.com/1.mp4"
    # legacy single link stays a direct URL button
    assert flat(episodes_keyboard(d, 0))[0]["url"] == "https://old.com/1.mp4"
    # adding a 1080p link to a legacy episode keeps its HD link
    db.add_episodes(d.id, parse_quality_links("EP 1\n1080p: https://new.com/1.mkv"))
    ep1 = db.get_drama(d.id).episodes[0]
    assert [q for q, _ in ep1.quality_groups()] == ["HD", "1080p"]
    assert flat(episodes_keyboard(db.get_drama(d.id), 0))[0]["callback_data"] == "ep:1:1:0"
    db.add_episodes(d.id, parse_quality_links("480p: https://n/3", start=3))
    assert db.links_per_quality() == {"HD": 2, "1080p": 1, "480p": 1}
    assert db.card_post(d.id).message_id == 55
    Database(f"sqlite:///{path}")  # re-running the migration is a no-op


async def _drama_on_channel(env, n=23):
    d = await wizard(env, links=f"480p: https://a/{{ep}} 1 {n}\n1080p: https://c/{{ep}} 1 {n}")
    return d, dict(chat_id=CHANNEL, message_id=env.db.card_post(d.id).message_id, chat_type="channel")


async def test_channel_taps_never_edit_channel_post(env):
    d, chan = await _drama_on_channel(env)
    for data in (f"eps:{d.id}:0", f"eps:{d.id}:1", f"ep:{d.id}:12:1", f"ql:{d.id}:12:0:1", f"back:{d.id}"):
        await env.send(cb_update(data, VIEWER, **chan))
    edits = env.req.of("editMessageReplyMarkup") + env.req.of("editMessageCaption") + env.req.of("editMessageText")
    assert not [e for e in edits if e.get("chat_id") == CHANNEL and e.get("message_id") == chan["message_id"]]
    assert all(p["chat_id"] == VIEWER for p in env.req.of("sendMessage")[-5:])


async def test_private_navigation_stays_in_dm(env):
    d, chan = await _drama_on_channel(env)
    await env.send(cb_update(f"eps:{d.id}:0", VIEWER, **chan))
    priv = dict(chat_id=VIEWER, message_id=555, chat_type="private")
    await env.send(cb_update(f"eps:{d.id}:2", VIEWER, **priv))
    e = env.req.of("editMessageReplyMarkup")[-1]
    assert (e["chat_id"], e["message_id"]) == (VIEWER, 555)
    assert [b["text"] for b in flat(e["reply_markup"]) if b["text"].startswith("EP")] == ["EP 21", "EP 22", "EP 23"]
    await env.send(cb_update(f"ep:{d.id}:22:2", VIEWER, **priv))
    e = env.req.of("editMessageReplyMarkup")[-1]
    assert e["chat_id"] == VIEWER and flat(e["reply_markup"])[1]["url"] == "https://c/22"


async def test_deep_link_fallback_when_cannot_dm(env):
    d, chan = await _drama_on_channel(env)
    env.req.blocked.add(VIEWER)
    n_edits = len(env.req.of("editMessageReplyMarkup"))
    await env.send(cb_update(f"eps:{d.id}:1", VIEWER, **chan))
    ans = env.req.of("answerCallbackQuery")[-1]
    assert ans["url"] == f"https://t.me/kdrama_heaven_bot?start=drama_{d.id}"
    assert len(env.req.of("editMessageReplyMarkup")) == n_edits
    # after /start drama_<id> the viewer gets the private browse card
    env.req.blocked.clear()
    await env.send(msg_update(f"/start drama_{d.id}", VIEWER))
    dm = env.req.of("sendMessage")[-1]
    assert dm["chat_id"] == VIEWER and flat(dm["reply_markup"])[0]["callback_data"] == f"ep:{d.id}:1:0"


async def test_multi_viewer_independence(env):
    d, chan = await _drama_on_channel(env)
    a, b = 7, 8
    await env.send(cb_update(f"eps:{d.id}:2", a, **chan))
    await env.send(cb_update(f"eps:{d.id}:0", b, **chan))
    sent = {p["chat_id"]: p for p in env.req.of("sendMessage") if p["chat_id"] in (a, b)}
    first = lambda p: [x["text"] for x in flat(p["reply_markup"]) if x["text"].startswith("EP")][0]
    assert first(sent[a]) == "EP 21" and first(sent[b]) == "EP 1"
    await env.send(cb_update(f"eps:{d.id}:1", a, chat_id=a, message_id=900, chat_type="private"))
    await env.send(cb_update(f"ep:{d.id}:3:0", b, chat_id=b, message_id=901, chat_type="private"))
    ea, eb = env.req.of("editMessageReplyMarkup")[-2:]
    assert (ea["chat_id"], ea["message_id"]) == (a, 900) and (eb["chat_id"], eb["message_id"]) == (b, 901)
    assert first(ea) == "EP 11" and flat(eb["reply_markup"])[0]["url"] == "https://a/3"
