import pytest

from tests.conftest import ADMIN, VIEWER
from tests.fakes import msg_update
from tests.test_bot import add_drama_via_wizard, last_text

pytestmark = pytest.mark.asyncio


def media_edits(env):
    return env.req.of("editMessageMedia")


async def test_caption_photo_updates_poster_and_card(env):
    d = await add_drama_via_wizard(env)
    await env.send(msg_update(photo="NEW_PHOTO", user_id=ADMIN, caption=f"/edit {d.id} poster"))
    assert env.db.get_drama(d.id).poster == "NEW_PHOTO"
    m = media_edits(env)[-1]["media"]
    assert m["media"] == "NEW_PHOTO" and m["type"] == "photo" and "Queen of" in m["caption"]
    assert "Poster updated" in last_text(env)


async def test_reply_to_photo(env):
    d = await add_drama_via_wizard(env)
    photo = msg_update(photo="REPLY_PHOTO", user_id=ADMIN)
    await env.send(msg_update(f"/edit {d.id} poster", ADMIN, reply=photo))
    assert env.db.get_drama(d.id).poster == "REPLY_PHOTO"
    assert media_edits(env)


async def test_reply_to_image_document(env):
    d = await add_drama_via_wizard(env)
    doc = msg_update(user_id=ADMIN, document="DOC_ID")
    await env.send(msg_update(f"/edit {d.id} poster", ADMIN, reply=doc))
    assert env.req.of("getFile")[-1]["file_id"] == "DOC_ID"
    assert env.db.get_drama(d.id).poster == "x"  # re-uploaded as a photo -> photo file_id
    assert media_edits(env)


async def test_url_still_works_and_bad_value(env):
    d = await add_drama_via_wizard(env)
    await env.send(msg_update(f"/edit {d.id} poster https://img.example/p.jpg", ADMIN))
    assert env.db.get_drama(d.id).poster == "https://img.example/p.jpg"
    await env.send(msg_update(f"/edit {d.id} poster nope", ADMIN))
    assert "photo or an http(s)" in last_text(env)


async def test_await_next_photo_and_cancel(env):
    d = await add_drama_via_wizard(env)
    await env.send(msg_update(f"/edit {d.id} poster", ADMIN))
    assert "Send the new poster photo" in last_text(env)
    await env.send(msg_update(photo="LATER", user_id=ADMIN))
    assert env.db.get_drama(d.id).poster == "LATER"
    await env.send(msg_update(f"/edit {d.id} poster", ADMIN))
    await env.send(msg_update("/cancel", ADMIN))
    assert "Cancelled" in last_text(env)
    await env.send(msg_update(photo="IGNORED", user_id=ADMIN))
    assert env.db.get_drama(d.id).poster == "LATER"


async def test_text_post_is_reposted_with_photo(env):
    d = await add_drama_via_wizard(env)
    env.db.update_drama(d.id, poster=None)
    p = env.db.card_post(d.id)
    env.db.conn.execute("UPDATE posts SET is_photo=0 WHERE id=?", (p.id,)) if hasattr(env.db, "conn") else None
    n = len(env.req.of("sendPhoto"))
    await env.send(msg_update(photo="P2", user_id=ADMIN, caption=f"/edit {d.id} poster"))
    assert env.db.get_drama(d.id).poster == "P2"
    assert len(env.req.of("sendPhoto")) > n or media_edits(env)


async def test_non_admin_blocked(env):
    d = await add_drama_via_wizard(env)
    await env.send(msg_update(photo="EVIL", user_id=VIEWER, caption=f"/edit {d.id} poster"))
    assert "only the kdrama_heaven admins" in last_text(env)
    photo = msg_update(photo="EVIL", user_id=VIEWER)
    await env.send(msg_update(f"/edit {d.id} poster", VIEWER, reply=photo))
    await env.send(msg_update(photo="EVIL", user_id=VIEWER))
    assert env.db.get_drama(d.id).poster == "POSTER_FILE_ID"
    assert not media_edits(env)
