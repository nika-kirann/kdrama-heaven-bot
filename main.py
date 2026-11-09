"""kdrama_heaven bot entry point: python main.py"""
import logging
import re
import sys

from telegram import BotCommand, Update
from telegram.error import InvalidToken, TelegramError
from telegram.ext import Application, ContextTypes

import handlers
import jobs
from config import config
from db import Database
from services import ChannelService
from storage import make_storage
from health import set_context, start_health_server

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("kdrama_bot")
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message and update.effective_chat.type == "private":
        try:
            await update.effective_message.reply_text("😵 Something went wrong. Please try again.")
        except TelegramError:
            pass


async def post_init(app: Application):
    me = await app.bot.get_me()
    cfg = app.bot_data["cfg"]
    log.info("Logged in as @%s, channel=%s, admins=%s", me.username, cfg.channel_id, sorted(cfg.admin_ids))
    import asyncio
    set_context(cfg=cfg, db=app.bot_data["db"], svc=app.bot_data["svc"],
                bot=app.bot, loop=asyncio.get_running_loop())
    await start_storage(app)
    await app.bot.set_my_commands([BotCommand("start", "Main menu"), BotCommand("browse", "Browse dramas"),
                                   BotCommand("search", "Search by title, genre or year")])
    jobs.setup_jobs(app)


async def start_storage(app: Application):
    """Restore the DB from Telegram (if enabled) before polling starts."""
    st, db = app.bot_data["storage"], app.bot_data["db"]
    if st.backend == "telegram":
        if await st.restore():
            db.reload()
        db.on_commit = st.schedule_flush
        await sync_posters(app)
        await st.flush()  # make sure a backup exists right away (fresh start)
        log.info("Storage: telegram (chat %s, backup message %s)", st.chat_id, st.backup_msg_id)
    else:
        log.info("Storage: local (%s)", db.path)


async def sync_posters(app: Application) -> int:
    """Copy posters that aren't in the storage channel yet (e.g. added while STORAGE_BACKEND=local)."""
    db, svc = app.bot_data["db"], app.bot_data["svc"]
    n = 0
    for d in db.list_dramas(limit=10000)[0]:
        if d.poster and not d.poster_msg_id:
            ch = await svc.persist_poster(d.poster)
            if ch.get("poster_msg_id"):
                db.update_drama(d.id, **ch)
                n += 1
    log.info("Storage: %s poster(s) copied to the storage channel", n)
    return n


async def post_stop(app: Application):
    await app.bot_data["storage"].close()


def build_app(cfg=config, db=None) -> Application:
    app = Application.builder().token(cfg.bot_token).post_init(post_init).post_stop(post_stop).build()
    db = db or Database(cfg.database_url)
    storage = make_storage(cfg, app.bot, db.path)
    app.bot_data.update(cfg=cfg, db=db, storage=storage, svc=ChannelService(app.bot, db, cfg, storage))
    handlers.register(app)
    app.add_error_handler(on_error)
    return app


def main() -> int:
    if not config.bot_token:
        log.error("BOT_TOKEN is missing. Copy .env.example to .env and paste the token from @BotFather.")
        return 1
    if not TOKEN_RE.match(config.bot_token):
        log.error("BOT_TOKEN doesn't look like a BotFather token (expected '123456789:ABC...'). Check your .env.")
        return 1
    if not config.admin_ids:
        log.warning("ADMIN_IDS is empty: nobody can use admin commands. Get your id from @userinfobot.")
    try:
        start_health_server()
        build_app().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except InvalidToken:
        log.error("Telegram rejected BOT_TOKEN (invalid or revoked). Get a fresh one from @BotFather.")
        return 1
    except TelegramError as e:
        log.error("Telegram error on startup: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
