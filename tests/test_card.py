import io
from types import SimpleNamespace as NS

from PIL import Image

from banner import render_banner
from services import audio_tags, drama_card
from tests.conftest import ADMIN, CHANNEL, VIEWER
from tests.fakes import cb_update, msg_update


class Ep:
    def __init__(self, n, qs):
        self.number, self._qs = n, qs

    def quality_groups(self):
        return [(q, []) for q in self._qs]


def fake(**kw):
    base = dict(id=7, title="Love <&> Code", year=2025, status="Ongoing", total_episodes=16, synopsis="",
                genres="Romance, Slice of life", audio=None, imdb=None,
                episodes=[Ep(1, ["720p", "1080p"]), Ep(2, ["480p", "1080p"])])
    base.update(kw)
    d = NS(**base)
    d.genre_list = [g.strip() for g in d.genres.split(",") if g.strip()]
    return d


def test_card_layout_and_escaping():
    c = drama_card(fake(synopsis="A <b>bold</b> & sweet story", imdb="8.2"), brand="@kdrama_heaven")
    assert "✦ <b>Love &lt;&amp;&gt; Code</b> ✦" in c
    assert "<i>2025 · K-Drama</i>" in c and "<code>ONGOING 🔄</code>" in c and "<code>2/16</code>" in c
    assert "<b>Quality</b> · <code>720p 1080p 480p</code>" in c
    assert "<b>Audio</b> · <code>[Korean] [Eng Sub]</code>" in c and "⭐ 8.2/10" in c
    assert "#Romance #SliceOfLife" in c and "&lt;b&gt;bold&lt;/b&gt; &amp; sweet" in c
    assert c.rstrip().endswith("✦ <b>Powered by</b> @kdrama_heaven  ·  <code>#7</code>")
    assert "<b>bold</b>" not in c


def test_card_audio_custom_and_no_imdb():
    d = fake(audio="Korean / Hindi Dub, Eng Sub", status="Completed")
    assert audio_tags(d) == "[Korean] [Hindi Dub] [Eng Sub]"
    c = drama_card(d)
    assert "COMPLETED ✅" in c and "IMDb" not in c


def test_card_truncation_fits_caption():
    c = drama_card(fake(synopsis="word & more " * 400))
    assert len(c) <= 1024 and "…</blockquote>" in c and "Powered by" in c
    assert len(drama_card(fake(synopsis="x " * 5000), 4096)) <= 4096


def test_banner_png():
    png = render_banner("A Very Long Drama Title That Needs Wrapping Nicely", "Completed",
                        ["Romance", "Drama"], 2026, 10, 16, ["720p", "1080p"])
    im = Image.open(io.BytesIO(png))
    assert im.format == "PNG" and im.size == (1280, 720)
    assert render_banner("X", seed=1) == render_banner("X", seed=1)


async def test_banner_used_when_no_poster_and_private_browse_intact(env):
    env.cfg.banner = True
    s = env.send
    for step in ["/add", "Banner Show", "/skip", "/skip", "/skip", "/skip", "Korean, Eng Sub | 7.9"]:
        await s(msg_update(step, ADMIN))
    await s(cb_update("st:Ongoing", ADMIN))
    await s(msg_update("2", ADMIN))
    await s(msg_update("720p: https://a/{ep} 1 2", ADMIN))
    d = env.db.find_drama("Banner Show")
    assert d.audio == "Korean, Eng Sub" and d.imdb == "7.9"
    post = [p for p in env.req.of("sendPhoto") if p["chat_id"] == CHANNEL][-1]
    assert "⭐ 7.9/10" in post["caption"]
    kb = post["reply_markup"]["inline_keyboard"]
    assert kb[0][0]["text"].startswith("▶️ Browse & Download") and kb[0][0]["callback_data"] == f"eps:{d.id}:0"
    card = env.db.card_post(d.id)
    assert card.is_photo
    n = len(env.req.of("editMessageReplyMarkup"))
    await s(cb_update(f"eps:{d.id}:0", VIEWER, chat_id=CHANNEL, message_id=card.message_id, chat_type="channel"))
    assert len(env.req.of("editMessageReplyMarkup")) == n
    # status change refreshes the generated banner image too
    await s(msg_update(f"/edit {d.id} status completed", ADMIN))
    assert env.req.of("editMessageMedia")


async def test_edit_audio_and_imdb(env):
    from tests.test_quality import wizard
    d = await wizard(env)
    await env.send(msg_update(f"/edit {d.id} audio Korean, Hindi Dub", ADMIN))
    await env.send(msg_update(f"/edit {d.id} imdb 8.4", ADMIN))
    d = env.db.get_drama(d.id)
    assert d.audio == "Korean, Hindi Dub" and d.imdb == "8.4"
    await env.send(msg_update(f"/edit {d.id} imdb eleven", ADMIN))
    assert "rating like" in env.req.of("sendMessage")[-1]["text"]
