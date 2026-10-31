"""Viewer side: /start, /browse, /search, episode pagination, drama cards, requests."""
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import keyboards as kb
from services import drama_card
from utils import h, safe_call
from .common import arg_text, deps

log = logging.getLogger(__name__)
WELCOME = ("💜 <b>Welcome to kdrama_heaven!</b>\n"
           "Find ongoing and completed K-dramas, browse episodes, or request a drama.")
PAGE = kb.PER_PAGE


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = context.args[0] if context.args else ""
    db, _, _ = deps(context)
    if arg == "request":
        context.user_data["awaiting"] = "request"
        return await update.message.reply_text("🙋 Which drama would you like us to add? Send the name.")
    if arg.startswith("d") and arg[1:].isdigit():
        d = db.get_drama(int(arg[1:]))
        if d and not d.deleted:
            return await send_card(update.message, d)
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML, reply_markup=kb.main_menu())


async def browse(update: Update, context):
    await update.message.reply_text("📺 What would you like to browse?", reply_markup=kb.main_menu())


async def search_cmd(update: Update, context):
    q = arg_text(update)
    if not q:
        context.user_data["awaiting"] = "search"
        return await update.message.reply_text("🔎 Send a title, genre or year to search.")
    await show_search(update.message.reply_text, context, q, 0)


async def show_search(send, context, text, page):
    db, _, _ = deps(context)
    dramas, total = db.search(text, offset=page * PAGE, limit=PAGE)
    if not total:
        return await send(f"No dramas found for “{text}”. Try another title, genre or year, or request it!",
                          reply_markup=kb.main_menu())
    await send(f"🔎 Results for “{text}” ({total}):",
               reply_markup=kb.drama_list(dramas, total, page, "br:search", text[:40]))


async def send_card(message, d):
    markup = kb.episodes_keyboard(d, 0) if d.episodes else None
    if d.poster:
        await safe_call(message.reply_photo, photo=d.poster, caption=drama_card(d),
                        parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await safe_call(message.reply_text, drama_card(d, 4096), parse_mode=ParseMode.HTML, reply_markup=markup)


async def on_browse(update: Update, context):
    db, _, _ = deps(context)
    q = update.callback_query
    parts = q.data.split(":", 3)
    kind, page = parts[1], int(parts[2])
    arg = parts[3] if len(parts) > 3 else ""
    await q.answer()
    edit = q.edit_message_text
    if kind == "menu":
        return await edit("📺 What would you like to browse?", reply_markup=kb.main_menu())
    if kind == "request":
        context.user_data["awaiting"] = "request"
        return await q.message.reply_text("🙋 Which drama would you like us to add? Send the name.")
    if kind == "search":
        if arg:
            return await show_search(edit, context, arg, page)
        context.user_data["awaiting"] = "search"
        return await q.message.reply_text("🔎 Send a title, genre or year to search.")
    if kind == "genres":
        genres = db.top_genres()
        return await edit("🏷 Top genres:" if genres else "No genres yet.", reply_markup=kb.genres_keyboard(genres))
    status = {"ongoing": "Ongoing", "completed": "Completed"}.get(kind)
    genre = arg if kind == "genre" else None
    dramas, total = db.list_dramas(status=status, genre=genre, offset=page * PAGE, limit=PAGE)
    label = {"ongoing": "🔄 Ongoing", "completed": "✅ Completed", "latest": "🆕 Latest"}.get(kind, f"🏷 {genre}")
    await edit(f"{label} ({total}):" if total else f"{label}: nothing here yet.",
               reply_markup=kb.drama_list(dramas, total, page, f"br:{kind}", arg))


async def on_drama(update: Update, context):
    db, _, _ = deps(context)
    q = update.callback_query
    d = db.get_drama(int(q.data.split(":")[1]))
    if not d or d.deleted:
        return await q.answer("That drama is no longer available.", show_alert=True)
    await q.answer()
    await send_card(q.message, d)


async def on_episodes(update: Update, context):
    """Works both on the channel post (edits its keyboard in place) and on DM cards."""
    db, _, _ = deps(context)
    q = update.callback_query
    _, did, page = q.data.split(":")
    d = db.get_drama(int(did))
    if not d or d.deleted:
        return await q.answer("This drama was removed.", show_alert=True)
    if not d.episodes:
        return await q.answer("No episodes yet, stay tuned! 💜", show_alert=True)
    await q.answer()
    await safe_call(q.edit_message_reply_markup, reply_markup=kb.episodes_keyboard(d, int(page)))


async def on_back(update: Update, context):
    db, svc, _ = deps(context)
    q = update.callback_query
    d = db.get_drama(int(q.data.split(":")[1]))
    await q.answer()
    if d:
        await safe_call(q.edit_message_reply_markup, reply_markup=kb.card_keyboard(d, svc.username))


async def on_noop(update: Update, context):
    await update.callback_query.answer()


async def on_text(update: Update, context):
    db, svc, _ = deps(context)
    awaiting = context.user_data.pop("awaiting", None)
    text = update.message.text.strip()
    if awaiting == "request":
        u = update.effective_user
        r = db.add_request(u.id, u.username, text[:500])
        who = f"@{u.username}" if u.username else h(u.full_name)
        await svc.notify_admins(f"🙋 <b>Drama request #{r.id}</b> from {who} (<code>{u.id}</code>):\n{h(text[:500])}")
        return await update.message.reply_text("💜 Thanks! Your request was sent to the admins.")
    # default: treat any text in DM as a search
    await show_search(update.message.reply_text, context, text, 0)


def handlers():
    private_text = filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE
    return [
        CommandHandler("start", start), CommandHandler("browse", browse), CommandHandler("search", search_cmd),
        CallbackQueryHandler(on_browse, pattern=r"^br:"), CallbackQueryHandler(on_drama, pattern=r"^dr:\d+$"),
        CallbackQueryHandler(on_episodes, pattern=r"^eps:\d+:\d+$"), CallbackQueryHandler(on_back, pattern=r"^back:\d+$"),
        CallbackQueryHandler(on_noop, pattern=r"^noop$"), MessageHandler(private_text, on_text),
    ]
