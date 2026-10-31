import os
import sys

import pytest
import pytest_asyncio

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)
os.environ.pop("BOT_TOKEN", None)

from telegram import Update  # noqa: E402
from telegram.ext import Application  # noqa: E402

import handlers  # noqa: E402
from config import Config  # noqa: E402
from db import Database  # noqa: E402
from services import ChannelService  # noqa: E402
from tests.fakes import DUMMY_TOKEN, FakeRequest  # noqa: E402

ADMIN = 1
VIEWER = 2
CHANNEL = -1001234567890


@pytest.fixture
def cfg(tmp_path):
    c = Config(bot_token=DUMMY_TOKEN, channel_id=CHANNEL, admin_ids={ADMIN}, timezone="Asia/Kolkata",
               daily_digest_time="10:00", cleanup_days=7, database_url=f"sqlite:///{tmp_path}/t.db")
    return c


@pytest_asyncio.fixture
async def env(cfg):
    req = FakeRequest()
    app = Application.builder().token(DUMMY_TOKEN).request(req).get_updates_request(FakeRequest()).build()
    db = Database(cfg.database_url)
    app.bot_data.update(cfg=cfg, db=db, svc=ChannelService(app.bot, db, cfg))
    handlers.register(app)
    await app.initialize()

    async def send(raw):
        await app.process_update(Update.de_json(raw, app.bot))

    class Env:
        pass
    e = Env()
    e.app, e.req, e.db, e.svc, e.cfg, e.send = app, req, db, app.bot_data["svc"], cfg, send
    yield e
    await app.shutdown()
