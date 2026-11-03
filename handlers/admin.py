"""Admin commands: /complete /edit /delete /list /stats /schedule /schedules /cleanup."""
import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import jobs
import keyboards as kb
from utils import URL_RE, describe_links, h, local_midnight_utc, norm_quality, parse_local_dt, parse_quality_links
from .common import admin_only, is_admin, arg_text, deps

log = logging.getLogger(__name__)
EDIT_FIELDS = {"title", "synopsis", "genres", "year", "poster", "total", "status", "repost", "links", "quality", "audio", "imdb"}


@admin_only
async def complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db, svc, _ = deps(context)
    d = db.find_drama(arg_text(update))
    if not d:
        return await update.message.reply_text("Usage: /complete <drama title or id>")
    if d.status == "Completed":
        return await update.message.reply_text(f"{d.title} is already completed.")
    await svc.complete(d.id)
    await update.message.reply_text(f"✅ {d.title} marked COMPLETED and the post was updated.")


@admin_only
async def edit(update: Update, context):
    db, svc, _ = deps(context)
    args = arg_text(update)
    msg = update.effective_message
    # format: /edit <id> <field> <value>   (id is required here to avoid ambiguity)
    parts = args.split(maxsplit=2)
    if len(parts) < 2 or not parts[0].isdigit() or parts[1].lower() not in EDIT_FIELDS:
        return await msg.reply_text(
            "Usage: /edit <id> <field> <value>\nFields: title, synopsis, genres, year, poster, total, status, audio, imdb, repost, links, quality\n"
            "Examples:\n/edit 3 year 2024\n"
            "/edit 3 poster: send a photo with that caption, reply to a photo with it, add an https URL, "
            "or send it alone and then the photo\n/edit 3 quality 520p 720p   (rename; use - to delete a quality)\n"
            "/edit 3 links\nEP 5\n1080p: https://x/ep5.mkv\n(replaces those qualities for those episodes)")
    d = db.find_drama(parts[0])
    if not d:
        return await update.message.reply_text("No drama with that id.")
    field, value = parts[1].lower(), (parts[2] if len(parts) > 2 else "").strip()
    if field == "poster":
        return await edit_poster(update, context, d, value)
    if field == "links":
        try:
            eps = parse_quality_links(value, None, start=1)
        except ValueError as e:
            return await update.message.reply_text(f"⚠️ {e}")
        if not eps:
            return await update.message.reply_text("Put the links on the lines after /edit <id> links (start with 'EP n').")
        db.add_episodes(d.id, eps)
        await svc.refresh_card(d.id)
        return await update.message.reply_text(f"🔗 Updated links {describe_links(eps)} for {d.title}; channel post edited.")
    if field == "quality":
        bits = value.split()
        if len(bits) != 2:
            return await update.message.reply_text("Usage: /edit <id> quality <old> <new>   or   /edit <id> quality <old> -")
        new = None if bits[1] == "-" else norm_quality(bits[1])
        n = db.rename_quality(d.id, norm_quality(bits[0]), new)
        if not n:
            return await update.message.reply_text(f"No {bits[0]} links on {d.title}.")
        await svc.refresh_card(d.id)
        return await update.message.reply_text(
            f"🎞 {'Renamed' if new else 'Removed'} {n} {norm_quality(bits[0])} links" + (f" → {new}" if new else "") + ".")
    if field == "repost":
        await svc.post_card(d)
        return await update.message.reply_text("📤 Reposted the card to the channel.")
    try:
        if field in {"year", "total"}:
            if not value.isdigit():
                raise ValueError("needs a number")
            changes = {"year" if field == "year" else "total_episodes": int(value)}
        elif field == "status":
            if value.title() not in {"Ongoing", "Completed"}:
                raise ValueError("must be Ongoing or Completed")
            changes = {"status": value.title()}
        elif field == "audio":
            changes = {"audio": ", ".join(p.strip() for p in value.replace("/", ",").split(",") if p.strip())[:100] or None}
        elif field == "imdb":
            if value in {"-", ""}:
                changes = {"imdb": None}
            else:
                v = value.split("/")[0].strip()
                if not (v.replace(".", "", 1).isdigit() and 0 <= float(v) <= 10):
                    raise ValueError("must be a rating like 8.2 (or - to clear)")
                changes = {"imdb": v}
        elif field == "genres":
            changes = {"genres": ", ".join(g.strip().title() for g in value.split(",") if g.strip())}
        else:
            if not value:
                raise ValueError("value is empty")
            changes = {field: value}
    except ValueError as e:
        return await update.message.reply_text(f"⚠️ {field} {e}")
    db.update_drama(d.id, **changes)
    await svc.refresh_card(d.id)
    await update.message.reply_text(f"✏️ Updated {field} for {d.title}; channel post edited.")


async def _photo_ref(context, message):
    """file_id of a photo (largest size) or an image document (re-uploaded as a photo) in message."""
    if message is None:
        return None
    if message.photo:
        return message.photo[-1].file_id
    doc = message.document
    if doc and (doc.mime_type or "").startswith("image/"):
        f = await context.bot.get_file(doc.file_id)
        data = bytes(await f.download_as_bytearray())
        sent = await context.bot.send_photo(message.chat_id, photo=data, caption="🖼 poster preview",
                                            disable_notification=True)
        return sent.photo[-1].file_id
    return None


async def _apply_poster(update, context, d, poster):
    _, svc, _ = deps(context)
    await svc.set_poster(d.id, poster)
    await update.effective_message.reply_text(f"🖼 Poster updated for {d.title}; channel post edited.")


async def edit_poster(update, context, d, value):
    """/edit <id> poster: photo with that caption, a reply to a photo, an https URL, or ask for one."""
    msg = update.effective_message
    poster = await _photo_ref(context, msg) or await _photo_ref(context, msg.reply_to_message)
    if poster:
        return await _apply_poster(update, context, d, poster)
    if value:
        if not URL_RE.match(value):
            return await msg.reply_text("⚠️ poster must be a photo or an http(s) image URL")
        return await _apply_poster(update, context, d, value)
    context.user_data["awaiting_poster"] = d.id
    await msg.reply_text(f"🖼 Send the new poster photo for {d.title} now (or /cancel).")


async def poster_photo(update: Update, context):
    """A photo/image sent after `/edit <id> poster`, or with that caption."""
    db, _, _ = deps(context)
    msg = update.effective_message
    if (msg.caption or "").startswith("/edit"):
        context.user_data.pop("awaiting_poster", None)
        return await edit(update, context)  # admin_only inside; arg_text reads the caption
    if not is_admin(update, context):
        return
    did = context.user_data.pop("awaiting_poster", None)
    d = db.get_drama(did) if did else None
    if not d:
        return
    poster = await _photo_ref(context, msg)
    if not poster:
        context.user_data["awaiting_poster"] = did
        return await msg.reply_text("That isn't an image. Send a photo, or /cancel.")
    await _apply_poster(update, context, d, poster)


async def cancel_poster(update: Update, context):
    if context.user_data.pop("awaiting_poster", None):
        await update.message.reply_text("Cancelled the poster change.")


@admin_only
async def delete(update: Update, context):
    db, svc, _ = deps(context)
    d = db.find_drama(arg_text(update))
    if not d:
        return await update.message.reply_text("Usage: /delete <drama title or id>")
    ok = await svc.delete(d.id)
    note = "" if ok else "\n(Telegram wouldn't delete the post now; /cleanup will retry. Posts older than 48h must be deleted by hand.)"
    await update.message.reply_text(f"🗑 Deleted {d.title}.{note}")


def _list_page(db, page: int):
    dramas, total = db.list_dramas(offset=page * kb.PER_PAGE, limit=kb.PER_PAGE, order="title")
    lines = [f"📚 <b>Dramas</b> ({total})"] + [
        f"<code>{d.id}</code> {h(d.title)} — {d.status}, {len(d.episodes)} eps" for d in dramas]
    return "\n".join(lines), kb.drama_list(dramas, total, page, "list")


@admin_only
async def list_cmd(update: Update, context):
    db, _, _ = deps(context)
    text, markup = _list_page(db, 0)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=markup)


@admin_only
async def list_page(update: Update, context):
    db, _, _ = deps(context)
    q = update.callback_query
    await q.answer()
    text, markup = _list_page(db, int(q.data.split(":")[1]))
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=markup)


@admin_only
async def stats(update: Update, context):
    db, _, cfg = deps(context)
    s = db.stats(local_midnight_utc(cfg.tz))
    await update.message.reply_text(
        "📊 <b>kdrama_heaven stats</b>\n"
        f"Dramas: {s['dramas']} (🔄 {s['ongoing']} ongoing / ✅ {s['completed']} completed)\n"
        f"Episodes: {s['episodes']}\nPosts today: {s['posts_today']}\n"
        f"Requests: {s['requests']}\nPending schedules: {s['pending_schedules']}"
        + ("\nLinks per quality: " + ", ".join(f"{h(q)} {n}" for q, n in db.links_per_quality().items())
           if db.links_per_quality() else ""), parse_mode="HTML")


@admin_only
async def schedule(update: Update, context):
    db, _, cfg = deps(context)
    args = arg_text(update)
    try:
        run_at, a, b = parse_local_dt(args, cfg.tz)
    except ValueError:
        return await update.message.reply_text(
            "Usage: /schedule <drama title or id | -> YYYY-MM-DD HH:MM <text>\n"
            "Example: /schedule Queen of Tears 2026-11-01 20:00 EP 9 drops tonight!\n"
            f"Times are {cfg.timezone}. Use - instead of a drama for a plain announcement.")
    ref, text = args[:a].strip(), args[b:].strip()
    from db import utcnow
    if run_at <= utcnow():
        return await update.message.reply_text("That time is in the past.")
    drama_id = None
    if ref and ref != "-":
        d = db.find_drama(ref)
        if not d:
            return await update.message.reply_text(f"No drama matching '{ref}'.")
        drama_id = d.id
    if not text and not drama_id:
        return await update.message.reply_text("Add some text to post.")
    sc = db.add_schedule(run_at, text, drama_id)
    jobs.queue_schedule(context.job_queue, sc)
    await update.message.reply_text(f"⏰ Scheduled #{sc.id} for {args[a:b]} ({cfg.timezone}).")


@admin_only
async def schedules(update: Update, context):
    db, _, cfg = deps(context)
    from datetime import timezone as tz
    rows = db.pending_schedules()
    if not rows:
        return await update.message.reply_text("No pending schedules.")
    lines = [f"#{s.id} {s.run_at.replace(tzinfo=tz.utc).astimezone(cfg.tz):%Y-%m-%d %H:%M} — {h(s.text[:50])}" for s in rows]
    await update.message.reply_text("⏰ Pending:\n" + "\n".join(lines), parse_mode="HTML")


@admin_only
async def unschedule(update: Update, context):
    db, _, _ = deps(context)
    sid = arg_text(update)
    if not sid.isdigit() or not db.get_schedule(int(sid)):
        return await update.message.reply_text("Usage: /unschedule <schedule id>")
    db.set_schedule_status(int(sid), "cancelled")
    for job in context.job_queue.get_jobs_by_name(f"schedule:{sid}"):
        job.schedule_removal()
    await update.message.reply_text(f"Cancelled schedule #{sid}.")


@admin_only
async def cleanup(update: Update, context):
    _, svc, cfg = deps(context)
    n = await svc.cleanup()
    await update.message.reply_text(f"🧹 Removed {n} old service messages (older than {cfg.cleanup_days} days) "
                                    "and deleted dramas' posts.")


@admin_only
async def digest_now(update: Update, context):
    _, svc, _ = deps(context)
    msg = await svc.daily_digest()
    await update.message.reply_text("📅 Digest posted." if msg else "No new episodes in the last day.")


@admin_only
async def admin_help(update: Update, context):
    await update.message.reply_text(
        "🛠 <b>Admin commands</b>\n"
        "/add — new drama wizard\n/addep &lt;drama&gt; — add episodes\n/complete &lt;drama&gt;\n"
        "/edit &lt;id&gt; &lt;field&gt; &lt;value&gt;\n/delete &lt;drama&gt;\n/list\n/stats\n"
        "/schedule &lt;drama|-&gt; YYYY-MM-DD HH:MM &lt;text&gt;\n/schedules, /unschedule &lt;id&gt;\n"
        "/cleanup\n/digest — post today's digest now\n/cancel", parse_mode="HTML")


def handlers():
    return [
        CommandHandler("complete", complete), CommandHandler("edit", edit), CommandHandler("delete", delete),
        CommandHandler("list", list_cmd), CallbackQueryHandler(list_page, pattern=r"^list:\d+$"),
        CommandHandler("stats", stats), CommandHandler("schedule", schedule),
        CommandHandler("schedules", schedules), CommandHandler("unschedule", unschedule),
        CommandHandler("cleanup", cleanup), CommandHandler("digest", digest_now),
        CommandHandler("admin", admin_help), CommandHandler("cancel", cancel_poster),
        MessageHandler(filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE), poster_photo),
    ]
