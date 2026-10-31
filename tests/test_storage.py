"""Telegram storage layer: backup, restore after data loss, posters, debounced flush. Fake network only."""
import asyncio
import itertools
import json
import os
import sqlite3
import time

import pytest
from telegram import Bot

import main
from config import Config
from db import Database
from storage import BACKUP_NAME, LocalStorage, TelegramStorage, make_storage
from tests.conftest import ADMIN, CHANNEL
from tests.fakes import BOT_USER, DUMMY_TOKEN, FakeRequest, msg_update

STORE = -1009999999999


class StorageFake(FakeRequest):
    """Simulates a storage channel: documents/photos kept in memory, pinned message, getFile + download."""

    def __init__(self):
        super().__init__()
        self.files = {}          # file_id -> bytes
        self.messages = {}       # message_id -> message json
        self.pinned = None
        self.fid = itertools.count(1)

    async def do_request(self, url, method, request_data=None, **kw):
        if "/file/bot" in url:   # File.download_*
            self.calls.append(("download", {"url": url}))
            return 200, self.files[url.rsplit("/", 1)[-1]]
        self._upload = {}
        if request_data and request_data.multipart_data:
            for name, val in request_data.multipart_data.items():
                self._upload[name] = val[1] if isinstance(val, tuple) else val
        return await super().do_request(url, method, request_data, **kw)

    def _doc(self, data):
        fid = f"DOC{next(self.fid)}"
        self.files[fid] = data
        return {"file_id": fid, "file_unique_id": fid + "u", "file_name": BACKUP_NAME, "file_size": len(data)}

    def _result(self, api, p):
        if api == "getChat":
            r = {"id": STORE, "type": "channel", "title": "store", "accent_color_id": 0, "max_reaction_count": 11}
            if self.pinned:
                r["pinned_message"] = self.messages[self.pinned]
            return r
        if api == "sendDocument":
            m = self._msg(p) | {"document": self._doc(next(iter(self._upload.values())))}
            self.messages[m["message_id"]] = m
            return m
        if api == "editMessageMedia":
            m = self.messages[p["message_id"]] | {"document": self._doc(next(iter(self._upload.values())))}
            self.messages[p["message_id"]] = m
            return m
        if api == "pinChatMessage":
            self.pinned = p["message_id"]
            return True
        if api == "sendPhoto":
            fid = f"STORED_{p.get('photo')}"
            self.files[fid] = b"\x89PNGfake"
            m = self._msg(p, photo=[{"file_id": fid, "file_unique_id": fid + "u", "width": 9, "height": 9}])
            self.messages[m["message_id"]] = m
            return m
        if api == "getFile":
            return {"file_id": p["file_id"], "file_unique_id": "u", "file_path": p["file_id"]}
        return super()._result(api, p)


def _cfg(tmp_path, **kw):
    return Config(bot_token=DUMMY_TOKEN, channel_id=CHANNEL, admin_ids={ADMIN}, database_url=f"sqlite:///{tmp_path}/k.db",
                  storage_backend="telegram", storage_channel_id=STORE, flush_delay=0.05, **kw)


async def _bot(req):
    b = Bot(DUMMY_TOKEN, request=req, get_updates_request=FakeRequest())
    await b.initialize()
    return b


def _titles(path):
    return [r[0] for r in sqlite3.connect(path).execute("select title from dramas order by id")]


@pytest.mark.asyncio
async def test_fresh_start_backup_then_restore_after_data_loss(tmp_path):
    req = StorageFake()
    bot = await _bot(req)
    path = str(tmp_path / "k.db")
    db = Database(f"sqlite:///{path}")
    st = TelegramStorage(bot, STORE, path, delay=0.05)
    assert await st.restore() is False            # fresh: nothing pinned
    db.on_commit = st.schedule_flush
    await st.flush()
    assert req.pinned and st.backup_msg_id == req.pinned
    db.add_drama(title="Queen of Tears", synopsis="", genres="Romance")
    await asyncio.sleep(0.2)
    assert len(req.of("editMessageMedia")) >= 1   # flush replaced the pinned doc in place

    # simulate the Koyeb disk being wiped
    db.engine.dispose()
    os.remove(path)
    db2 = Database(f"sqlite:///{path}")
    assert _titles(path) == []
    st2 = TelegramStorage(bot, STORE, path)
    assert await st2.restore() is True
    db2.reload()
    assert [d.title for d in db2.list_dramas()[0]] == ["Queen of Tears"]
    assert st2.backup_msg_id == req.pinned


@pytest.mark.asyncio
async def test_debounced_flush_coalesces_writes(tmp_path):
    req = StorageFake()
    bot = await _bot(req)
    path = str(tmp_path / "k.db")
    db = Database(f"sqlite:///{path}")
    st = TelegramStorage(bot, STORE, path, delay=0.1)
    await st.restore()
    db.on_commit = st.schedule_flush
    for i in range(5):
        db.add_drama(title=f"D{i}")
    await asyncio.sleep(0.02)
    assert st.flushes == 0                       # still waiting
    await asyncio.sleep(0.3)
    assert st.flushes == 1                       # 5+ commits -> one upload
    doc = req.messages[req.pinned]["document"]["file_id"]
    snap = tmp_path / "snap.db"
    snap.write_bytes(req.files[doc])
    assert _titles(str(snap)) == [f"D{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_close_flushes_and_edit_failure_falls_back_to_new_pin(tmp_path):
    req = StorageFake()
    bot = await _bot(req)
    path = str(tmp_path / "k.db")
    db = Database(f"sqlite:///{path}")
    st = TelegramStorage(bot, STORE, path, delay=10)
    await st.restore()
    await st.flush()
    first = req.pinned
    db.on_commit = st.schedule_flush
    db.add_drama(title="Late write")
    req.fail_next["editMessageMedia"] = {"ok": False, "error_code": 400, "description": "Bad Request: message to edit not found"}
    await st.close()                             # shutdown flush, no 10 s wait
    assert req.pinned != first and req.of("deleteMessage")
    snap = tmp_path / "s.db"
    snap.write_bytes(req.files[req.messages[req.pinned]["document"]["file_id"]])
    assert _titles(str(snap)) == ["Late write"]


@pytest.mark.asyncio
async def test_restore_ignores_non_sqlite_pin(tmp_path):
    req = StorageFake()
    bot = await _bot(req)
    m = req._msg({"chat_id": STORE}) | {"document": req._doc(b"not a db")}
    req.messages[m["message_id"]] = m
    req.pinned = m["message_id"]
    path = str(tmp_path / "k.db")
    Database(f"sqlite:///{path}").add_drama(title="Keep me")
    assert await TelegramStorage(bot, STORE, path).restore() is False
    assert _titles(path) == ["Keep me"]


@pytest.mark.asyncio
async def test_poster_round_trip_via_wizard(tmp_path):
    """Full app with telegram backend: /add with a photo -> poster stored in storage channel -> survives data loss."""
    cfg = _cfg(tmp_path, poster_cache_dir=str(tmp_path / "cache"))
    req = StorageFake()
    from telegram.ext import Application
    app = Application.builder().token(DUMMY_TOKEN).request(req).get_updates_request(FakeRequest()).build()
    db = Database(cfg.database_url)
    from services import ChannelService
    import handlers
    st = make_storage(cfg, app.bot, db.path)
    app.bot_data.update(cfg=cfg, db=db, storage=st, svc=ChannelService(app.bot, db, cfg, st))
    handlers.register(app)
    await app.initialize()
    await main.start_storage(app)
    from telegram import Update
    from tests.fakes import cb_update
    for u in [msg_update("/add", ADMIN), msg_update("Lovely Runner", ADMIN), msg_update(user_id=ADMIN, photo=True),
              msg_update("/skip", ADMIN), msg_update("/skip", ADMIN), msg_update("/skip", ADMIN), msg_update("/skip", ADMIN),
              cb_update("st:Ongoing", ADMIN), msg_update("1", ADMIN), msg_update("720p: https://ex.com/1.mp4", ADMIN)]:
        await app.process_update(Update.de_json(u, app.bot))
    photos = req.of("sendPhoto")
    assert photos[0]["chat_id"] == STORE and photos[0]["photo"] == "POSTER_FILE_ID"
    assert photos[1]["chat_id"] == CHANNEL and photos[1]["photo"] == "STORED_POSTER_FILE_ID"
    d = db.find_drama("Lovely Runner")
    assert d.poster == "STORED_POSTER_FILE_ID" and d.poster_msg_id
    assert os.listdir(tmp_path / "cache")                      # optional local cache
    assert await st.poster_bytes(d.poster) == b"\x89PNGfake"   # downloadable via get_file
    await app.shutdown()
    await st.close()

    # data loss -> restore -> poster reference still there
    db.engine.dispose(); os.remove(db.path)
    db2 = Database(cfg.database_url)
    st2 = TelegramStorage(app.bot, STORE, db2.path)
    await app.bot.initialize()
    assert await st2.restore()
    db2.reload()
    d2 = db2.find_drama("Lovely Runner")
    assert d2.poster == "STORED_POSTER_FILE_ID" and len(d2.episodes) == 1


def test_local_backend_default_and_factory(tmp_path):
    assert Config().storage_backend in {"local", "telegram"}
    c = Config(storage_backend="local")
    assert isinstance(make_storage(c, None, "x"), LocalStorage)
    t = make_storage(_cfg(tmp_path), None, "x")
    assert isinstance(t, TelegramStorage) and t.chat_id == STORE
    c2 = _cfg(tmp_path); c2.storage_channel_id = None
    assert make_storage(c2, None, "x").chat_id == CHANNEL     # falls back to CHANNEL_ID


def test_relative_db_url_resolves_to_app_dir():
    from config import APP_DIR, _db_url
    assert _db_url("sqlite:///kdrama.db") == "sqlite:///" + os.path.join(APP_DIR, "kdrama.db")
    assert _db_url("sqlite:////tmp/x.db") == "sqlite:////tmp/x.db"


def test_migration_adds_poster_msg_id(tmp_path):
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("create table dramas (id integer primary key, title varchar(200), poster varchar(500), synopsis text, "
              "genres varchar(300), year integer, status varchar(20), total_episodes integer, deleted boolean, "
              "created_at datetime, updated_at datetime)")
    c.execute("insert into dramas (title, poster, synopsis, genres, status, deleted) values ('Old', 'fid', '', '', 'Ongoing', 0)")
    c.commit(); c.close()
    db = Database(f"sqlite:///{p}")
    d = db.find_drama("Old")
    assert d.poster == "fid" and d.poster_msg_id is None
    db.update_drama(d.id, poster_msg_id=5)
    assert db.get_drama(d.id).poster_msg_id == 5


@pytest.mark.asyncio
async def test_app_lifecycle_restore_then_post_stop_flush(tmp_path):
    from telegram.ext import Application
    cfg = _cfg(tmp_path)
    req = StorageFake()
    app = Application.builder().token(DUMMY_TOKEN).request(req).get_updates_request(FakeRequest()).build()
    db = Database(cfg.database_url)
    st = make_storage(cfg, app.bot, db.path)
    from services import ChannelService
    app.bot_data.update(cfg=cfg, db=db, storage=st, svc=ChannelService(app.bot, db, cfg, st))
    old = db.add_drama(title="Love in Disguise", poster="OLD_LOCAL_FID")   # added while backend was local
    await app.initialize()
    await main.start_storage(app)            # fresh start -> poster copied, first backup pinned
    assert req.pinned and db.on_commit
    d = db.get_drama(old.id)
    assert d.poster == "STORED_OLD_LOCAL_FID" and d.poster_msg_id
    st.delay = 60
    db.add_request(5, "u", "Please add Moving")
    await main.post_stop(app)                # shutdown flush without waiting 60 s
    snap = tmp_path / "s.db"
    snap.write_bytes(req.files[req.messages[req.pinned]["document"]["file_id"]])
    assert [r[0] for r in sqlite3.connect(snap).execute("select text from requests")] == ["Please add Moving"]
    await app.shutdown()
