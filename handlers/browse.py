"""Viewer side: /start, /browse, /search, episode pagination, drama cards, requests."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, TypeHandler, filters

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
    if arg.startswith("follow_") and arg[7:].isdigit():
        d = db.get_drama(int(arg[7:]))
        if d and not d.deleted:
            db.set_follow(update.effective_user.id, d.id, True)
            await update.message.reply_text(
                f"🔔 You're following <b>{h(d.title)}</b>. I'll DM you when new episodes drop!",
                parse_mode=ParseMode.HTML)
            return await send_card(update.message, d, context.bot_data.get("svc"))
    if arg.startswith("report_") and arg[7:].isdigit():
        d = db.get_drama(int(arg[7:]))
        if d and not d.deleted:
            from . import report
            return await report.begin(update.message.reply_text, context, update.effective_user.id, d)
    did = arg[6:] if arg.startswith("drama_") else arg[1:] if arg.startswith("d") else ""
    if did.isdigit():
        d = db.get_drama(int(did))
        if d and not d.deleted:
            return await send_card(update.message, d, context.bot_data.get("svc"))
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


async def send_card(message, d, svc=None):
    await dm_card(message.get_bot(), message.chat_id, d, svc=svc)


async def dm_card(bot, chat_id, d, markup=None, svc=None):
    """Send a viewer their own private copy of a drama card (with its own keyboard)."""
    card = svc.card if svc else drama_card
    markup = markup or (kb.episodes_keyboard(d, 0) if d.episodes else None)
    if svc is not None and isinstance(chat_id, int) and chat_id > 0:
        markup = kb.with_follow(markup, d.id, svc.db.is_following(chat_id, d.id))
    if d.poster:
        return await safe_call(bot.send_photo, chat_id, photo=d.poster, caption=card(d),
                               parse_mode=ParseMode.HTML, reply_markup=markup)
    return await safe_call(bot.send_message, chat_id, card(d, 4096), parse_mode=ParseMode.HTML,
                           reply_markup=markup)


def deep_link(bot, drama_id) -> str:
    return f"https://t.me/{bot.username}?start=drama_{drama_id}"


async def respond(q, context, d, markup, note=None, follow=True):
    """Private chats: edit this viewer's own message in place.
    Channel/group posts: NEVER touch the shared keyboard. DM the viewer a private copy instead,
    or, if the bot can't DM them yet, answer with a deep link that opens the bot."""
    if q.message and q.message.chat.type == "private":
        await q.answer(note)
        db = context.bot_data["db"]
        if follow:
            markup = kb.with_follow(markup, d.id, db.is_following(q.from_user.id, d.id))
        return await safe_call(q.edit_message_reply_markup, reply_markup=markup)
    try:
        await dm_card(context.bot, q.from_user.id, d, markup, svc=context.bot_data.get("svc"))
    except (Forbidden, BadRequest) as e:
        log.info("Can't DM %s (%s); sending deep link", q.from_user.id, e)
        try:
            return await q.answer(url=deep_link(context.bot, d.id))
        except BadRequest:
            return await q.answer("💜 Start @%s first, then tap again to browse privately." % context.bot.username,
                                  show_alert=True)
    await q.answer("📩 Sent to your private chat with the bot, browse there!")


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
    await send_card(q.message, d, context.bot_data.get("svc"))


async def on_episodes(update: Update, context):
    """Channel taps go to the viewer's DM; DM taps edit that private message."""
    db, _, _ = deps(context)
    q = update.callback_query
    _, did, page = q.data.split(":")
    d = db.get_drama(int(did))
    if not d or d.deleted:
        return await q.answer("This drama was removed.", show_alert=True)
    if not d.episodes:
        return await q.answer("No episodes yet, stay tuned! 💜", show_alert=True)
    await respond(q, context, d, kb.episodes_keyboard(d, int(page)))


async def on_quality(update: Update, context):
    db, _, _ = deps(context)
    q = update.callback_query
    parts = q.data.split(":")
    d = db.get_drama(int(parts[1]))
    if not d or d.deleted:
        return await q.answer("This drama was removed.", show_alert=True)
    if parts[0] == "ep":
        markup = kb.quality_keyboard(d, int(parts[2]), int(parts[3]))
        msg = f"EP {parts[2]}: pick a quality"
    else:
        markup = kb.links_keyboard(d, int(parts[2]), int(parts[3]), int(parts[4]))
        if markup:
            ep = kb._episode(d, int(parts[2]))
            groups = ep.quality_groups() if ep else []
            if int(parts[3]) < len(groups):
                db.add_click(d.id, int(parts[2]), groups[int(parts[3])][0], q.from_user.id)
        msg = f"EP {parts[2]}: open each part/mirror"
    if not markup:
        return await q.answer("That episode isn't available anymore.", show_alert=True)
    await respond(q, context, d, markup, msg, follow=False)


async def on_back(update: Update, context):
    db, svc, _ = deps(context)
    q = update.callback_query
    d = db.get_drama(int(q.data.split(":")[1]))
    if not d or d.deleted:
        return await q.answer()
    if q.message and q.message.chat.type == "private":
        await q.answer()
        markup = kb.with_follow(kb.card_keyboard(d, svc.username), d.id, db.is_following(q.from_user.id, d.id))
        return await safe_call(q.edit_message_reply_markup, reply_markup=markup)
    await respond(q, context, d, kb.episodes_keyboard(d, 0) if d.episodes else None)


async def track_user(update: Update, context):
    """Runs first for every update: remember users (new-users stats; who can be DMed)."""
    u = update.effective_user
    if not u or u.is_bot:
        return
    chat = update.effective_chat
    db = context.bot_data["db"]
    try:
        db.touch_user(u.id, u.username, started=bool(chat and chat.type == "private"))
    except Exception:
        log.warning("touch_user failed", exc_info=True)


async def on_follow(update: Update, context):
    db, svc, _ = deps(context)
    q = update.callback_query
    parts = q.data.split(":")
    d = db.get_drama(int(parts[1]))
    if not d or d.deleted:
        return await q.answer("That drama is no longer available.", show_alert=True)
    uid = q.from_user.id
    want = (parts[2] == "1") if len(parts) > 2 else not db.is_following(uid, d.id)
    private = q.message and q.message.chat.type == "private"
    user = db.get_user(uid)
    if want and not private and not (user and user.started and not user.blocked):
        # The bot can't DM someone who never started it: send them through a deep link.
        try:
            return await q.answer(url=f"https://t.me/{context.bot.username}?start=follow_{d.id}")
        except BadRequest:
            return await q.answer(f"💜 Start @{context.bot.username} first, then tap Follow again.", show_alert=True)
    db.set_follow(uid, d.id, want)
    note = (f"🔔 Following {d.title}! You'll get a DM for new episodes." if want
            else f"🔕 Unfollowed {d.title}.")
    if private and q.message.reply_markup:
        await q.answer(note)
        return await safe_call(q.edit_message_reply_markup,
                               reply_markup=kb.with_follow(q.message.reply_markup, d.id, want))
    await q.answer(note, show_alert=not private)


async def on_my_follows(update: Update, context):
    db, _, _ = deps(context)
    q = update.callback_query
    await q.answer()
    ds = db.follows_of(q.from_user.id)
    rows = [[InlineKeyboardButton(f"🔔 {d.title}", callback_data=f"dr:{d.id}")] for d in ds[:50]]
    rows.append([InlineKeyboardButton("↩️ Menu", callback_data="br:menu:0")])
    text = (f"🔔 <b>My follows</b> ({len(ds)})\nTap one to open it." if ds
            else "🔔 You aren't following anything yet. Open a drama and tap 🔔 Follow.")
    await safe_call(q.edit_message_text, text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows))


async def on_noop(update: Update, context):
    await update.callback_query.answer()


async def on_text(update: Update, context):
    db, svc, _ = deps(context)
    awaiting = context.user_data.pop("awaiting", None)
    text = update.message.text.strip()
    if awaiting in ("report_ep", "report_note"):
        from . import report
        return await report.on_text(update, context, awaiting)
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
        CallbackQueryHandler(on_quality, pattern=r"^(ep:\d+:\d+:\d+|ql:\d+:\d+:\d+:\d+)$"),
        CallbackQueryHandler(on_noop, pattern=r"^noop$"), MessageHandler(private_text, on_text),
        CallbackQueryHandler(on_follow, pattern=r"^fol:\d+(:[01])?$"),
        CallbackQueryHandler(on_my_follows, pattern=r"^my:follows$"),
    ]
