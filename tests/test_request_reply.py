"""Admin replies to drama requests over Telegram: 💬 Reply button, /reply, /cancel, /requests."""
from tests.conftest import ADMIN, VIEWER
from tests.fakes import cb_update, msg_update


def dms(env, chat_id):
    return [p for p in env.req.of("sendMessage") if p["chat_id"] == chat_id]


async def _make_request(env, text="Please add Moving"):
    await env.send(msg_update("/start request", VIEWER))
    await env.send(msg_update(text, VIEWER))
    return env.db.list_requests()[0]


async def test_request_notification_has_reply_button_and_flow(env):
    r = await _make_request(env)
    note = dms(env, ADMIN)[-1]
    assert note["reply_markup"]["inline_keyboard"][0][0] == {"text": "💬 Reply", "callback_data": f"rqr:{r.id}"}
    await env.send(cb_update(f"rqr:{r.id}", ADMIN))
    assert "Send your reply text now" in dms(env, ADMIN)[-1]["text"]
    await env.send(msg_update("Added! Check the channel 🎉", ADMIN))
    assert dms(env, VIEWER)[-1]["text"] == '💬 Reply to your request "Please add Moving":\n\nAdded! Check the channel 🎉'
    assert "Reply sent to @user2" in dms(env, ADMIN)[-1]["text"]
    r2 = env.db.get_request(r.id)
    assert r2.status == "closed" and r2.reply_text == "Added! Check the channel 🎉"
    # next admin text is a normal search again, not another reply
    n = len(dms(env, VIEWER))
    await env.send(msg_update("Moving", ADMIN))
    assert len(dms(env, VIEWER)) == n


async def test_reply_button_cancel(env):
    r = await _make_request(env)
    await env.send(cb_update(f"rqr:{r.id}", ADMIN))
    await env.send(msg_update("/cancel", ADMIN))
    assert f"Cancelled the reply to request #{r.id}" in dms(env, ADMIN)[-1]["text"]
    n = len(dms(env, VIEWER))
    await env.send(msg_update("hello there", ADMIN))
    assert len(dms(env, VIEWER)) == n and env.db.get_request(r.id).status == "open"


async def test_reply_command_and_non_admin(env):
    r = await _make_request(env, "Reply 1988 pls")
    await env.send(msg_update(f"/reply {r.id} Coming soon, stay tuned", ADMIN))
    assert dms(env, VIEWER)[-1]["text"] == '💬 Reply to your request "Reply 1988 pls":\n\nComing soon, stay tuned'
    assert env.db.get_request(r.id).status == "closed"
    await env.send(msg_update("/reply", ADMIN))
    assert "Usage: /reply" in dms(env, ADMIN)[-1]["text"]
    await env.send(msg_update("/reply 999 hi", ADMIN))
    assert "not found" in dms(env, ADMIN)[-1]["text"]
    n = len(dms(env, VIEWER))
    await env.send(msg_update(f"/reply {r.id} sneaky", VIEWER))
    assert "only the kdrama_heaven admins" in dms(env, VIEWER)[-1]["text"] and len(dms(env, VIEWER)) == n + 1
    # /reply <id> alone asks for the text
    await env.send(msg_update(f"/reply {r.id}", ADMIN))
    assert "Send your reply text now" in dms(env, ADMIN)[-1]["text"]


async def test_reply_command_failed_dm_not_marked(env):
    r = await _make_request(env)
    env.req.blocked.add(VIEWER)
    await env.send(msg_update(f"/reply {r.id} Sorry, not available right now", ADMIN))
    assert "blocked the bot" in dms(env, ADMIN)[-1]["text"]
    r2 = env.db.get_request(r.id)
    assert r2.status == "open" and r2.reply_text is None
    assert env.db.request_replies([r.id])[r.id] == []


async def test_requests_command_lists_open_with_buttons(env):
    r = await _make_request(env)
    await env.send(msg_update("/requests", ADMIN))
    m = dms(env, ADMIN)[-1]
    assert "Open drama requests" in m["text"] and f"#{r.id}" in m["text"]
    assert m["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == f"rqr:{r.id}"
