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
    log.info("Logged in as @%s, channel=%s, admins=%s", me.username, config.channel_id, sorted(config.admin_ids))
    await app.bot.set_my_commands([BotCommand("start", "Main menu"), BotCommand("browse", "Browse dramas"),
                                   BotCommand("search", "Search by title, genre or year")])
    jobs.setup_jobs(app)


def build_app(cfg=config, db=None) -> Application:
    app = Application.builder().token(cfg.bot_token).post_init(post_init).build()
    db = db or Database(cfg.database_url)
    app.bot_data.update(cfg=cfg, db=db, svc=ChannelService(app.bot, db, cfg))
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
