"""/add wizard and /addep conversation."""
import logging

from telegram import Update
from telegram.ext import (CallbackQueryHandler, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler, filters)

import keyboards as kb
from utils import URL_RE, h, parse_links
from .common import admin_only, arg_text, deps

log = logging.getLogger(__name__)
TITLE, POSTER, SYNOPSIS, GENRES, YEAR, STATUS, TOTAL, LINKS = range(8)
EP_LINKS = 20
SKIP = "(send /skip to leave it empty)"


@admin_only
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["draft"] = {}
    await update.effective_message.reply_text("🎬 New drama! What's the <b>title</b>? (/cancel anytime)",
                                              parse_mode="HTML")
    return TITLE


async def got_title(update: Update, context):
    context.user_data["draft"]["title"] = update.message.text.strip()[:200]
    await update.message.reply_text(f"🖼 Send the <b>poster</b> as a photo or an image URL {SKIP}", parse_mode="HTML")
    return POSTER


async def got_poster(update: Update, context):
    msg = update.message
    if msg.photo:
        context.user_data["draft"]["poster"] = msg.photo[-1].file_id
    elif msg.text and URL_RE.match(msg.text.strip()):
        context.user_data["draft"]["poster"] = msg.text.strip()
    else:
        await msg.reply_text("That isn't a photo or an http(s) URL. Try again or /skip.")
        return POSTER
    await msg.reply_text(f"📝 Now the <b>synopsis</b> {SKIP}", parse_mode="HTML")
    return SYNOPSIS


async def skip_poster(update, context):
    await update.message.reply_text(f"📝 Now the <b>synopsis</b> {SKIP}", parse_mode="HTML")
    return SYNOPSIS


async def got_synopsis(update, context):
    context.user_data["draft"]["synopsis"] = update.message.text.strip()
    return await ask_genres(update)


async def ask_genres(update):
    await update.message.reply_text(f"🏷 <b>Genres</b>, comma separated (e.g. Romance, Comedy) {SKIP}", parse_mode="HTML")
    return GENRES


async def skip_synopsis(update, context):
    return await ask_genres(update)


async def got_genres(update, context):
    context.user_data["draft"]["genres"] = ", ".join(g.strip().title() for g in update.message.text.split(",") if g.strip())
    return await ask_year(update)


async def ask_year(update):
    await update.message.reply_text(f"📅 Release <b>year</b>? {SKIP}", parse_mode="HTML")
    return YEAR


async def skip_genres(update, context):
    return await ask_year(update)


async def got_year(update, context):
    t = update.message.text.strip()
    if not (t.isdigit() and 1950 <= int(t) <= 2100):
        await update.message.reply_text("Please send a 4-digit year like 2024, or /skip.")
        return YEAR
    context.user_data["draft"]["year"] = int(t)
    return await ask_status(update)


async def ask_status(update):
    await update.message.reply_text("📡 Status?", reply_markup=kb.status_keyboard())
    return STATUS


async def skip_year(update, context):
    return await ask_status(update)


async def got_status(update, context):
    q = update.callback_query
    await q.answer()
    status = q.data.split(":", 1)[1]
    context.user_data["draft"]["status"] = status
    await q.edit_message_text(f"Status: {status}")
    await q.message.reply_text(f"🔢 <b>Total episodes</b> (number) {SKIP}", parse_mode="HTML")
    return TOTAL


async def got_total(update, context):
    t = update.message.text.strip()
    if not t.isdigit() or int(t) < 1:
        await update.message.reply_text("Send a number like 16, or /skip.")
        return TOTAL
    context.user_data["draft"]["total_episodes"] = int(t)
    return await ask_links(update)


async def ask_links(update):
    await update.message.reply_text(
        "🔗 <b>Episode links</b>. Either:\n"
        "• one link per line (EP 1, EP 2, …), or\n"
        "• a pattern with <code>{ep}</code> plus optional start and end episode, e.g.\n"
        "<code>https://example.com/drama/{ep}.mp4 1 16</code>\n"
        "(end defaults to total episodes) " + SKIP, parse_mode="HTML")
    return LINKS


async def skip_total(update, context):
    return await ask_links(update)


async def got_links(update, context):
    draft = context.user_data["draft"]
    try:
        links, start = parse_links(update.message.text, draft.get("total_episodes"))
    except ValueError as e:
        await update.message.reply_text(f"⚠️ {e}. Try again or /skip.")
        return LINKS
    return await finish(update, context, links, start or 1)


async def skip_links(update, context):
    return await finish(update, context, [], 1)


async def finish(update, context, links, start):
    db, svc, _ = deps(context)
    draft = context.user_data.pop("draft")
    draft.setdefault("status", "Ongoing")
    d = db.add_drama(**draft, links=links, start_episode=start)
    try:
        await svc.post_card(d)
        await update.message.reply_text(f"✅ Posted <b>{h(d.title)}</b> (id {d.id}) with {len(d.episodes)} episodes.",
                                        parse_mode="HTML")
    except Exception as e:
        log.exception("Posting card failed")
        await update.message.reply_text(f"Saved as id {d.id}, but posting to the channel failed: {e}\n"
                                        f"Check the bot is a channel admin, then use /edit {d.id} repost")
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.pop("draft", None)
    context.user_data.pop("addep", None)
    await update.effective_message.reply_text("Cancelled 👍")
    return ConversationHandler.END


# ---------------- /addep ----------------
@admin_only
async def addep_start(update: Update, context):
    db, svc, _ = deps(context)
    text = arg_text(update)
    ref, _, rest = text.partition("\n")
    d = db.find_drama(ref)
    if not d:
        await update.message.reply_text("Usage: /addep <drama title or id>\n(optional: links on the next lines)")
        return ConversationHandler.END
    if rest.strip():
        return await _do_addep(update, context, d.id, rest)
    context.user_data["addep"] = d.id
    last = max((e.number for e in d.episodes), default=0)
    await update.message.reply_text(
        f"Adding to <b>{h(d.title)}</b> (has {len(d.episodes)} eps, next is EP {last + 1}).\n"
        "Send links one per line, or a pattern like <code>https://x/{ep}.mp4 9 10</code>", parse_mode="HTML")
    return EP_LINKS


async def addep_links(update, context):
    return await _do_addep(update, context, context.user_data.pop("addep"), update.message.text)


async def _do_addep(update, context, drama_id, text):
    db, svc, _ = deps(context)
    d = db.get_drama(drama_id)
    try:
        links, start = parse_links(text, None)
        if "{ep}" in text and len(text.split()) < 3:
            raise ValueError("For /addep patterns give start and end, e.g. https://x/{ep}.mp4 9 10")
    except ValueError as e:
        context.user_data["addep"] = drama_id
        await update.message.reply_text(f"⚠️ {e}")
        return EP_LINKS
    if not links:
        await update.message.reply_text("No links given.")
        return ConversationHandler.END
    nums = await svc.add_episodes(d.id, links, start)
    await update.message.reply_text(f"✅ Added EP {nums[0]}–{nums[-1]} to {d.title}; channel post updated.")
    return ConversationHandler.END


def handlers():
    text = filters.TEXT & ~filters.COMMAND
    add = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            TITLE: [MessageHandler(text, got_title)],
            POSTER: [MessageHandler(filters.PHOTO | text, got_poster), CommandHandler("skip", skip_poster)],
            SYNOPSIS: [MessageHandler(text, got_synopsis), CommandHandler("skip", skip_synopsis)],
            GENRES: [MessageHandler(text, got_genres), CommandHandler("skip", skip_genres)],
            YEAR: [MessageHandler(text, got_year), CommandHandler("skip", skip_year)],
            STATUS: [CallbackQueryHandler(got_status, pattern=r"^st:")],
            TOTAL: [MessageHandler(text, got_total), CommandHandler("skip", skip_total)],
            LINKS: [MessageHandler(text, got_links), CommandHandler("skip", skip_links)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="add_wizard", conversation_timeout=1800,
    )
    addep = ConversationHandler(
        entry_points=[CommandHandler("addep", addep_start)],
        states={EP_LINKS: [MessageHandler(text, addep_links)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        name="addep", conversation_timeout=900,
    )
    return [add, addep]
