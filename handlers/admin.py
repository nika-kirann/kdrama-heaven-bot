"""Admin commands: /complete /edit /delete /list /stats /schedule /schedules /cleanup."""
import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

import jobs
import keyboards as kb
from utils import URL_RE, describe_links, h, local_midnight_utc, norm_quality, parse_local_dt, parse_quality_links
from .common import admin_only, arg_text, deps

log = logging.getLogger(__name__)
EDIT_FIELDS = {"title", "synopsis", "genres", "year", "poster", "total", "status", "repost", "links", "quality"}


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
    # format: /edit <id> <field> <value>   (id is required here to avoid ambiguity)
    parts = args.split(maxsplit=2)
    if len(parts) < 2 or not parts[0].isdigit() or parts[1].lower() not in EDIT_FIELDS:
        return await update.message.reply_text(
            "Usage: /edit <id> <field> <value>\nFields: title, synopsis, genres, year, poster, total, status, repost, links, quality\n"
            "Examples:\n/edit 3 year 2024\n/edit 3 quality 520p 720p   (rename; use - to delete a quality)\n"
            "/edit 3 links\nEP 5\n1080p: https://x/ep5.mkv\n(replaces those qualities for those episodes)")
    d = db.find_drama(parts[0])
    if not d:
        return await update.message.reply_text("No drama with that id.")
    field, value = parts[1].lower(), (parts[2] if len(parts) > 2 else "").strip()
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
        elif field == "poster":
            if not URL_RE.match(value):
                raise ValueError("must be an http(s) image URL")
            changes = {"poster": value}
        elif field == "genres":
            changes = {"genres": ", ".join(g.strip().title() for g in value.split(",") if g.strip())}
        else:
            if not value:
                raise ValueError("value is empty")
            changes = {field: value}
    except ValueError as e:
        return await update.message.reply_text(f"⚠️ {field} {e}")
    poster_kind_changed = field == "poster" and not d.poster
    db.update_drama(d.id, **changes)
    if poster_kind_changed:
        # A text post can't become a photo post; delete and repost.
        p = db.card_post(d.id)
        if p:
            await svc._remove(p)
        await svc.post_card(db.get_drama(d.id))
    else:
        await svc.refresh_card(d.id)
    await update.message.reply_text(f"✏️ Updated {field} for {d.title}; channel post edited.")


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
        CommandHandler("admin", admin_help),
    ]
