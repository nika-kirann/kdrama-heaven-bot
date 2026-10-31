import functools
import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

log = logging.getLogger(__name__)
NOT_ALLOWED = "🙅 Sorry, only the kdrama_heaven admins can use that command. Try /browse to explore dramas!"


def deps(context):
    bd = context.bot_data
    return bd["db"], bd["svc"], bd["cfg"]


def is_admin(update: Update, context) -> bool:
    user = update.effective_user
    return bool(user and user.id in context.bot_data["cfg"].admin_ids)


def admin_only(fn):
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if not is_admin(update, context):
            uid = update.effective_user.id if update.effective_user else None
            log.info("Blocked non-admin %s from %s", uid, fn.__name__)
            if update.callback_query:
                await update.callback_query.answer(NOT_ALLOWED, show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(NOT_ALLOWED)
            return ConversationHandler.END
        return await fn(update, context, *a, **kw)
    return wrapper


def arg_text(update: Update) -> str:
    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""
