"""Web admin panel: auth, CSRF, CRUD via /admin, /healthz still public."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

import pytest

from config import Config
from db import Database
from health import set_context, start_health_server
from services import ChannelService
from tests.conftest import ADMIN, CHANNEL
from tests.fakes import DUMMY_TOKEN, FakeRequest
from web import auth as authlib


class FakeBot:
    def __init__(self):
        self.sent = []
        self.username = "kdrama_heaven_bot"

    async def send_message(self, chat_id, text, **kw):
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return {"message_id": len(self.sent)}

    async def send_photo(self, chat_id, photo, **kw):
        self.sent.append({"chat_id": chat_id, "photo": True})
        class P:
            file_id = "fid"
        class M:
            photo = [P()]
            message_id = 1
        return M()


@pytest.fixture
def web(tmp_path):
    cfg = Config(bot_token=DUMMY_TOKEN, channel_id=CHANNEL, admin_ids={ADMIN, 99},
                 timezone="Asia/Kolkata", database_url=f"sqlite:///{tmp_path}/w.db",
                 admin_web_password="s3cret", admin_web_secret="test-secret")
    db = Database(cfg.database_url)
    bot = FakeBot()
    # ChannelService needs a PTB bot-like object; use FakeRequest-backed mini stub via Application is heavy.
    # For web mutations we mostly need db + a svc with async methods — build a light wrapper.
    class Svc:
        def __init__(self):
            self.db, self.cfg, self.bot = db, cfg, bot
            self.username = "kdrama_heaven_bot"
        def stats_text(self):
            return "📊 stats"
        def card(self, d, limit=1024):
            from services import drama_card
            return drama_card(d)
        async def persist_poster(self, poster):
            return {"poster": poster}
        async def post_card(self, d):
            bot.sent.append({"post_card": d.id})
            db.add_post(CHANNEL, 1, "card", d.id, is_photo=False)
            return True
        async def refresh_card(self, drama_id, markup=None):
            bot.sent.append({"refresh": drama_id}); return True
        async def set_poster(self, drama_id, poster):
            db.update_drama(drama_id, poster=poster); return db.get_drama(drama_id)
        async def add_episodes(self, drama_id, episodes, start=None, season=None):
            from services import ChannelService
            # reuse real logic via a throwaway ChannelService with fake bot
            real = ChannelService(bot, db, cfg)
            # avoid follower DM spam: temporarily empty followers by not calling notify
            nums = db.add_episodes(drama_id, episodes, season=season)
            if db.get_drama(drama_id).next_ep_date:
                db.update_drama(drama_id, next_ep_date=None, air_time=None)
            await self.refresh_card(drama_id)
            return nums
        async def new_season(self, drama_id, total_episodes=None):
            sea = db.add_season(drama_id, total_episodes)
            await self.refresh_card(drama_id)
            return sea
        async def complete(self, drama_id, season=None):
            db.complete_season(drama_id, season)
            await self.refresh_card(drama_id)
        async def delete(self, drama_id):
            db.mark_deleted(drama_id); return True
        async def notify_admins(self, text, markup=None):
            pass

    svc = Svc()
    set_context(cfg=cfg, db=db, svc=svc, bot=bot, loop=None)
    srv = start_health_server(port=0, host="127.0.0.1")
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    class Client:
        def __init__(self):
            self.base, self.db, self.bot, self.cfg, self.auth = base, db, bot, cfg, authlib
            self._opener = opener
            self.jar = jar

        def open(self, path, data=None, method=None):
            headers = {}
            body = None
            if data is not None:
                body = urllib.parse.urlencode(data, doseq=True).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
            try:
                with self._opener.open(req, timeout=5) as r:
                    return r.status, r.read().decode(), dict(r.headers)
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode(), dict(e.headers)

        def login_password(self, admin_id=ADMIN, password="s3cret"):
            return self.open("/admin/login", {"mode": "password", "telegram_id": str(admin_id),
                                             "password": password})

        def csrf_from(self, html):
            m = re.search(r'name="csrf" value="([^"]+)"', html)
            assert m, "csrf missing"
            return m.group(1)

    yield Client()
    srv.shutdown()


def test_healthz_still_public(web):
    st, body, _ = web.open("/healthz")
    assert st == 200 and json.loads(body)["ok"] is True
    # no cookie → ends on login page (urllib follows the 303)
    st, body, _ = web.open("/admin")
    assert st == 200 and ("Admin" in body or "Sign in" in body or "Telegram" in body)
    assert "Dashboard" not in body


def test_non_admin_blocked_and_expired_code(web):
    st, body, _ = web.open("/admin/request-code", {"telegram_id": "12345"})
    assert st == 400 and "not an admin" in body.lower()
    # request real code
    st, body, _ = web.open("/admin/request-code", {"telegram_id": str(ADMIN)})
    assert st == 200 and "Code" in body
    from web.app import get_auth
    a = get_auth()
    code, exp = a.codes[ADMIN]
    # expire it
    a.codes[ADMIN] = (code, 0)
    st, body, _ = web.open("/admin/login", {"mode": "code", "telegram_id": str(ADMIN), "code": code})
    assert st == 403 and "Invalid or expired" in body


def test_password_login_session_and_csrf(web):
    st, body, hdrs = web.login_password()
    # 303 redirect to /admin — opener follows, we end on dashboard
    assert st == 200 and "Dashboard" in body
    st, body, _ = web.open("/admin/add")
    csrf = web.csrf_from(body)
    # CSRF missing -> 403
    st, body, _ = web.open("/admin/add", {"title": "X"})
    assert st == 403 and "CSRF" in body
    # page uses structured qualities, not a links textarea
    assert 'id="add-drama-form"' in web.open("/admin/add")[1]
    assert 'name="720p"' in web.open("/admin/add")[1] and "Episode links" not in web.open("/admin/add")[1]
    csrf = web.csrf_from(web.open("/admin/add")[1])
    st, body, _ = web.open("/admin/add", {
        "csrf": csrf, "title": "Web Drama", "year": "2026", "status": "Ongoing",
        "total": "16", "genres": "Romance", "synopsis": "hi",
        "ep_from": "1", "ep_to": "2", "720p": "https://x/{ep}",
    })
    assert st == 200 and ("Web Drama" in body or "Created" in body or "Saved" in body or "drama" in body.lower())
    d = web.db.find_drama("Web Drama")
    assert d is not None and [e.number for e in d.episodes] == [1, 2]


def test_add_edit_addep_newseason_complete_delete(web):
    web.login_password()
    _, body, _ = web.open("/admin/add")
    csrf = web.csrf_from(body)
    web.open("/admin/add", {
        "csrf": csrf, "title": "Season Show", "status": "Ongoing", "total": "2",
        "ep_from": "1", "ep_to": "2", "720p": "https://a/{ep}",
    })
    d = web.db.find_drama("Season Show")
    assert d and len(d.episodes) == 2 and not d.is_multi
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    web.open("/admin/drama/edit", {
        "csrf": csrf, "drama_id": str(d.id), "title": "Season Show",
        "status": "Ongoing", "imdb": "8.1", "nextep": "2026-11-11", "air_time": "20:00",
        "genres": "Romance", "synopsis": "x", "total": "16",
    })
    d = web.db.get_drama(d.id)
    assert d.imdb == "8.1" and d.next_ep_date == "2026-11-11" and d.current.total_episodes == 16
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    web.open("/admin/drama/newseason", {"csrf": csrf, "drama_id": str(d.id), "total": "16"})
    d = web.db.get_drama(d.id)
    assert d.is_multi and d.current.number == 2 and d.next_ep_date is None
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    assert 'id="addep-form"' in body and 'name="720p"' in body and "＋ Part" in body
    assert 'name="season"' in body  # multi shows season picker
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/addep", {
        "csrf": csrf, "drama_id": str(d.id), "season": "2", "episode": "1",
    })
    assert "At least one valid" in body
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    web.open("/admin/drama/addep", {
        "csrf": csrf, "drama_id": str(d.id), "season": "2", "episode": "1",
        "1080p": "https://b/1",
    })
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    web.open("/admin/drama/addep", {
        "csrf": csrf, "drama_id": str(d.id), "season": "2", "episode": "2",
        "720p": ["https://b/2a", "https://b/2b"],
        "720p_mirror": "https://b/2m",
        "480p": "https://b/2-480",
    })
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    web.open("/admin/drama/addep", {
        "csrf": csrf, "drama_id": str(d.id), "season": "2", "episode": "3",
        "1080p": "https://b/3",
    })
    d2 = web.db.get_drama(d.id)
    assert [e.number for e in d2.season(2).episodes] == [1, 2, 3]
    ep2 = next(e for e in d2.season(2).episodes if e.number == 2)
    groups = dict(ep2.quality_groups())
    assert "480p" in groups and "720p" in groups
    assert len(groups["720p"]) == 3  # 2 parts + 1 mirror
    # form prefills next episode
    assert 'value="4"' in body or 'id="addep-ep" value="4"' in web.open(f"/admin/drama/{d.id}")[1]
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    web.open("/admin/drama/complete", {"csrf": csrf, "drama_id": str(d.id), "season": "1"})
    assert web.db.get_drama(d.id).season(1).status == "Completed"
    assert web.db.get_drama(d.id).status == "Ongoing"
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    web.open("/admin/drama/delete", {"csrf": csrf, "drama_id": str(d.id), "season": "1"})
    assert web.db.get_drama(d.id).season(1) is None and len(web.db.get_drama(d.id).seasons) == 1
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/delete", {"csrf": csrf, "drama_id": str(d.id)})
    assert web.db.get_drama(d.id).deleted


def test_report_resolve_via_web(web):
    web.login_password()
    d = web.db.add_drama(title="R", status="Ongoing", episodes={1: [("HD", "https://x/1", "part")]})
    r = web.db.add_report(d.id, 55, "viewer", "b", episode=1, note="dead")
    _, body, _ = web.open("/admin/reports")
    assert f"#{r.id}" in body and "dead" in body
    csrf = web.csrf_from(body)
    web.open("/admin/report/resolve", {"csrf": csrf, "report_id": str(r.id), "action": "fixed"})
    assert web.db.get_report(r.id).status == "fixed"
    assert any(s.get("chat_id") == 55 for s in web.bot.sent)


def test_password_requires_admin_id(web):
    st, body, _ = web.open("/admin/login", {"mode": "password", "telegram_id": "99999", "password": "s3cret"})
    assert st == 403 and "Not an admin" in body


def test_add_drama_structured_links(web):
    web.login_password()
    _, body, _ = web.open("/admin/add")
    assert "From episode" in body and "＋ Part" in body and 'name="480p"' in body
    csrf = web.csrf_from(body)
    # no links → drama with 0 episodes
    web.open("/admin/add", {"csrf": csrf, "title": "Empty Eps", "status": "Ongoing", "total": "16"})
    d = web.db.find_drama("Empty Eps")
    assert d and len(d.episodes) == 0 and d.total_episodes == 16
    # bad URL
    _, body, _ = web.open("/admin/add")
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/add", {
        "csrf": csrf, "title": "Bad URL", "ep_from": "1", "ep_to": "2", "720p": "ftp://x/{ep}",
    })
    assert "http" in body.lower()
    assert web.db.find_drama("Bad URL") is None
    # range + parts + mirrors with {ep}
    _, body, _ = web.open("/admin/add")
    csrf = web.csrf_from(body)
    web.open("/admin/add", {
        "csrf": csrf, "title": "Range Show", "status": "Ongoing", "total": "3",
        "ep_from": "1", "ep_to": "3",
        "720p": ["https://a/{ep}-p1", "https://a/{ep}-p2"],
        "720p_mirror": "https://m/{ep}",
        "1080p": "https://b/{ep}",
    })
    d = web.db.find_drama("Range Show")
    assert [e.number for e in d.episodes] == [1, 2, 3]
    ep1 = d.episodes[0]
    groups = dict(ep1.quality_groups())
    assert [l.url for l in groups["720p"]] == ["https://a/1-p1", "https://a/1-p2", "https://m/1"]
    assert groups["1080p"][0].url == "https://b/1"
