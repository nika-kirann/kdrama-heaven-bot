from datetime import timedelta

import pytest

from db import Database, Report
from tests.conftest import ADMIN, VIEWER
from tests.fakes import cb_update, msg_update
from tests.test_bot import last_text
from tests.test_quality import _drama_on_channel, flat

pytestmark = pytest.mark.asyncio


def sent_to(env, uid):
    return [p for p in env.req.of("sendMessage") if p.get("chat_id") == uid]


async def _report(env, d, code="w", ep="7", note="Ep 7 plays ep 6", uid=VIEWER):
    await env.send(cb_update(f"rep:{d.id}", uid))
    await env.send(cb_update(f"rr:{d.id}:{code}", uid))
    if ep is not None:
        await env.send(msg_update(ep, uid))
    await env.send(msg_update(note, uid) if note else cb_update("rsk:note", uid))


async def test_report_buttons_on_channel_and_private_views(env):
    d, chan = await _drama_on_channel(env, 3)
    from tests.conftest import CHANNEL
    card = [p for p in env.req.of("sendPhoto") + env.req.of("sendMessage")
            if p.get("chat_id") == CHANNEL and p.get("reply_markup")][-1]
    urls = [b.get("url", "") for b in flat(card["reply_markup"])]
    assert any(u.endswith(f"?start=report_{d.id}") for u in urls)
    await env.send(msg_update("/start", VIEWER))
    await env.send(cb_update(f"eps:{d.id}:0", VIEWER))          # private episode view
    btns = flat(env.req.of("editMessageReplyMarkup")[-1]["reply_markup"])
    assert btns[-2]["callback_data"] == f"rep:{d.id}" and "fol:" in btns[-1]["callback_data"]
    await env.send(cb_update(f"back:{d.id}", VIEWER))           # private card view: no url duplicate
    btns = flat(env.req.of("editMessageReplyMarkup")[-1]["reply_markup"])
    assert [b.get("callback_data") for b in btns].count(f"rep:{d.id}") == 1
    assert not any("start=report_" in (b.get("url") or "") for b in btns)


async def test_full_report_flow_admin_dm_and_mark_fixed(env):
    d, _ = await _drama_on_channel(env, 3)
    await env.send(msg_update(f"/start report_{d.id}", VIEWER))
    assert "What's wrong?" in last_text(env)
    await env.send(cb_update(f"rr:{d.id}:w", VIEWER))
    assert "Which episode?" in last_text(env, "editMessageText")
    await env.send(msg_update("abc", VIEWER))
    assert "just the episode number" in last_text(env)
    await env.send(msg_update("2", VIEWER))
    assert "Any details" in last_text(env)
    await env.send(msg_update("Shows EP 1 again", VIEWER))
    assert "Report <code>#1</code> was sent" in last_text(env)
    adm = sent_to(env, ADMIN)[-1]
    for s in ("Report #1", d.title, "Episode: 2", "Wrong or misaligned episode", "Shows EP 1 again", str(VIEWER)):
        assert s in adm["text"]
    assert [b["callback_data"] for b in flat(adm["reply_markup"])] == ["rpf:1", "rpd:1"]
    r = env.db.get_report(1)
    assert (r.episode, r.reason, r.status) == (2, "w", "open")
    # non-admin can't resolve
    await env.send(cb_update("rpf:1", VIEWER))
    assert env.db.get_report(1).status == "open"
    await env.send(cb_update("rpf:1", ADMIN))
    assert env.db.get_report(1).status == "fixed"
    assert "Marked fixed" in last_text(env, "editMessageText")
    assert "✅ Fixed!" in sent_to(env, VIEWER)[-1]["text"] and "EP 2" in sent_to(env, VIEWER)[-1]["text"]
    await env.send(cb_update("rpf:1", ADMIN))
    assert "Already fixed" in env.req.of("answerCallbackQuery")[-1]["text"]


async def test_other_reason_skips_episode_and_dismiss(env):
    d, _ = await _drama_on_channel(env, 3)
    await _report(env, d, code="o", ep=None, note=None)
    r = env.db.get_report(1)
    assert r.reason == "o" and r.episode is None and r.note is None
    n = len(sent_to(env, VIEWER))
    await env.send(cb_update("rpd:1", ADMIN))
    assert env.db.get_report(1).status == "dismissed" and len(sent_to(env, VIEWER)) == n


async def test_skip_episode_step(env):
    d, _ = await _drama_on_channel(env, 3)
    await env.send(cb_update(f"rep:{d.id}", VIEWER))
    await env.send(cb_update(f"rr:{d.id}:b", VIEWER))
    await env.send(cb_update("rsk:ep", VIEWER))
    await env.send(cb_update("rsk:note", VIEWER))
    assert env.db.get_report(1).reason == "b" and env.db.get_report(1).episode is None


async def test_rate_limit_per_user_per_drama(env):
    d, _ = await _drama_on_channel(env, 3)
    await _report(env, d)
    await env.send(cb_update(f"rep:{d.id}", VIEWER))
    assert "wait about" in last_text(env)
    await _report(env, d, uid=77)               # other user is fine
    assert env.db.open_reports()[0] == 2
    with env.db.session() as s:                  # 11 minutes later
        for r in s.query(Report).all():
            r.created_at -= timedelta(minutes=11)
        s.commit()
    await _report(env, d)
    assert env.db.open_reports()[0] == 3


async def test_reports_command_and_stats(env, cfg):
    d, _ = await _drama_on_channel(env, 3)
    await env.send(msg_update("/reports", ADMIN))
    assert "No open reports" in last_text(env)
    await _report(env, d, code="m", ep="3", note="EP 3 not uploaded")
    await env.send(msg_update("/reports", VIEWER))
    assert "only the kdrama_heaven admins" in last_text(env)
    await env.send(msg_update("/reports", ADMIN))
    msgs = sent_to(env, ADMIN)
    t = next(m["text"] for m in reversed(msgs) if "Open reports" in m["text"])
    assert "Open reports</b> (1)" in t and "EP 3 · Episode missing" in t and "EP 3 not uploaded" in t
    assert flat(msgs[-1]["reply_markup"])[0]["callback_data"] == "rpf:1"
    await env.send(msg_update("/stats", ADMIN))
    assert "Open reports: 1" in last_text(env)
    assert Database(cfg.database_url).open_reports()[0] == 1   # table auto-created / persisted
