"""Admin commands: /complete /edit /delete /list /stats /schedule /schedules /cleanup."""
import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import jobs
import keyboards as kb
from utils import URL_RE, describe_links, h, local_midnight_utc, norm_quality, parse_local_dt, parse_quality_links
from .common import admin_only, is_admin, arg_text, deps

log = logging.getLogger(__name__)
EDIT_FIELDS = {"title", "synopsis", "genres", "year", "poster", "total", "status", "repost", "links", "quality", "audio", "imdb", "nextep"}


def _parse_season_ref(text: str):
    """'<drama> [sN]' -> (drama_ref, season_or_None)."""
    text = (text or "").strip()
    bits = text.rsplit(maxsplit=1)
    if len(bits) == 2 and bits[1].lower().startswith("s") and bits[1][1:].isdigit():
        return bits[0], int(bits[1][1:])
    return text, None


@admin_only
async def complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db, svc, _ = deps(context)
    ref, season = _parse_season_ref(arg_text(update))
    d = db.find_drama(ref)
    if not d:
        return await update.message.reply_text("Usage: /complete <drama title or id> [sN]")
    if season is not None:
        if not d.season(season):
            return await update.message.reply_text(f"{d.title} has no Season {season}.")
        if d.season(season).status == "Completed":
            return await update.message.reply_text(f"{d.title} Season {season} is already completed.")
    elif d.status == "Completed":
        return await update.message.reply_text(f"{d.title} is already completed.")
    target = season or (d.current.number if d.current else 1)
    await svc.complete(d.id, season)
    d = db.get_drama(d.id)
    if d.status == "Completed":
        await update.message.reply_text(f"✅ {d.title} fully COMPLETED (all seasons) and the post was updated.")
    else:
        await update.message.reply_text(f"✅ {d.title} Season {target} completed; drama still ongoing.")


@admin_only
async def newseason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db, svc, _ = deps(context)
    raw = arg_text(update)
    parts = raw.rsplit(maxsplit=1)
    total = None
    if len(parts) == 2 and parts[1].isdigit() and db.find_drama(parts[0]):
        ref, total = parts[0], int(parts[1])
    else:
        ref = raw
    d = db.find_drama(ref)
    if not d:
        return await update.message.reply_text("Usage: /newseason <drama id or title> [total_eps]")
    sea = await svc.new_season(d.id, total)
    await update.message.reply_text(
        f"🆕 {d.title} Season {sea.number} started"
        + (f" ({sea.total_episodes} eps planned)" if sea.total_episodes else "")
        + "; channel post updated, followers notified.")




@admin_only
async def edit(update: Update, context):
    db, svc, _ = deps(context)
    args = arg_text(update)
    msg = update.effective_message
    # format: /edit <id> <field> <value>  OR  /edit <id> sN <field> <value>
    parts = args.split(maxsplit=3)
    season_edit = None
    if len(parts) >= 3 and parts[0].isdigit() and parts[1].lower().startswith("s") and parts[1][1:].isdigit():
        season_edit = int(parts[1][1:])
        field = parts[2].lower()
        value = (parts[3] if len(parts) > 3 else "").strip()
        # alias: eps → total
        if field == "eps":
            field = "total"
        if field not in {"total", "status"}:
            return await msg.reply_text("Season fields: /edit <id> sN total <n>   or   /edit <id> sN status Ongoing|Completed")
    else:
        parts = args.split(maxsplit=2)
        if len(parts) < 2 or not parts[0].isdigit() or parts[1].lower() not in EDIT_FIELDS:
            return await msg.reply_text(
                "Usage: /edit <id> <field> <value>\nFields: title, synopsis, genres, year, poster, total, status, audio, imdb, nextep, repost, links, quality\n"
                "/edit 3 s2 total 16   (season-specific total)\n"
                "/edit 3 nextep 2026-11-11 [20:00]   (next-episode date, optional IST time; cleared on /addep|/newseason; - to clear)\n"
                "Examples:\n/edit 3 year 2024\n"
                "/edit 3 poster: send a photo with that caption, reply to a photo with it, add an https URL, "
                "or send it alone and then the photo\n/edit 3 quality 520p 720p   (rename; use - to delete a quality)\n"
                "/edit 3 links\nEP 5\n1080p: https://x/ep5.mkv\n(replaces those qualities for those episodes)")
        field, value = parts[1].lower(), (parts[2] if len(parts) > 2 else "").strip()
    d = db.find_drama(parts[0])
    if not d:
        return await update.message.reply_text("No drama with that id.")
    if season_edit is not None:
        if not d.season(season_edit):
            return await msg.reply_text(f"{d.title} has no Season {season_edit}.")
        try:
            if field == "total":
                if not value.isdigit():
                    raise ValueError("needs a number")
                db.update_season(d.id, season_edit, total_episodes=int(value))
            else:
                if value.title() not in {"Ongoing", "Completed"}:
                    raise ValueError("must be Ongoing or Completed")
                db.update_season(d.id, season_edit, status=value.title())
        except ValueError as e:
            return await msg.reply_text(f"⚠️ {field} {e}")
        await svc.refresh_card(d.id)
        return await msg.reply_text(f"✏️ Updated Season {season_edit} {field} for {d.title}; channel post edited.")
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
        if field == "year":
            if not value.isdigit():
                raise ValueError("needs a number")
            changes = {"year": int(value)}
        elif field == "total":
            if not value.isdigit():
                raise ValueError("needs a number")
            # drama-level total edits the current season's total (and mirrors onto the drama)
            cur = d.current.number if d.current else 1
            db.update_season(d.id, cur, total_episodes=int(value))
            await svc.refresh_card(d.id)
            return await msg.reply_text(f"✏️ Updated total for {d.title} S{cur}; channel post edited.")
        elif field == "status":
            if value.title() not in {"Ongoing", "Completed"}:
                raise ValueError("must be Ongoing or Completed")
            if value.title() == "Completed":
                # complete every season
                for sea in d.seasons:
                    if sea.status != "Completed":
                        db.update_season(d.id, sea.number, status="Completed")
            else:
                cur = d.current.number if d.current else 1
                db.update_season(d.id, cur, status="Ongoing")
            await svc.refresh_card(d.id)
            return await msg.reply_text(f"✏️ Updated status for {d.title}; channel post edited.")
        elif field == "nextep":
            from datetime import date as _date
            if value == "-":
                changes = {"next_ep_date": None, "air_time": None}
            else:
                import re as _re
                m = _re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:\s+([01]?\d|2[0-3]):([0-5]\d))?", value)
                try:
                    if not m:
                        raise ValueError
                    day = _date.fromisoformat(m.group(1)).isoformat()
                except ValueError:
                    raise ValueError("must be a date like 2026-11-11, optionally with a time: 2026-11-11 20:00 (or - to clear)")
                changes = {"next_ep_date": day, "air_time": f"{int(m.group(2)):02d}:{m.group(3)}" if m.group(2) else None}
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
    ref, season = _parse_season_ref(arg_text(update))
    d = db.find_drama(ref)
    if not d:
        return await update.message.reply_text("Usage: /delete <drama title or id> [sN]")
    if season is not None:
        if not d.season(season):
            return await update.message.reply_text(f"{d.title} has no Season {season}.")
        if len(d.seasons) <= 1:
            return await update.message.reply_text("Can't delete the only season — /delete the whole drama instead.")
        return await update.message.reply_text(
            f"Delete <b>{h(d.title)}</b> Season {season} ({len(d.season(season).episodes)} eps)? This can't be undone.",
            parse_mode="HTML", reply_markup=kb.confirm_delete_season(d.id, season))
    ok = await svc.delete(d.id)
    note = "" if ok else "\n(Telegram wouldn't delete the post now; /cleanup will retry. Posts older than 48h must be deleted by hand.)"
    await update.message.reply_text(f"🗑 Deleted {d.title}.{note}")


@admin_only
async def delete_season_confirm(update: Update, context):
    db, svc, _ = deps(context)
    q = update.callback_query
    if q.data == "delno":
        await q.answer("Cancelled")
        return await q.edit_message_text("Cancelled 👍")
    _, did, sn = q.data.split(":")
    d = db.get_drama(int(did))
    if not d or not d.season(int(sn)):
        return await q.answer("Already gone.", show_alert=True)
    ok = db.delete_season(d.id, int(sn))
    await q.answer("Deleted" if ok else "Failed")
    if ok:
        await svc.refresh_card(d.id)
        await q.edit_message_text(f"🗑 Deleted {d.title} Season {sn}; channel post updated.")
    else:
        await q.edit_message_text("Couldn't delete that season (is it the last one?).")


def _list_page(db, page: int):
    dramas, total = db.list_dramas(offset=page * kb.PER_PAGE, limit=kb.PER_PAGE, order="title")
    lines = [f"📚 <b>Dramas</b> ({total})"] + [
        f"<code>{d.id}</code> {h(d.title)} — {d.status}, "
        + (f"{len(d.seasons)} seasons, S{d.current.number} {len(d.current.episodes)}"
           f"{'/' + str(d.current.total_episodes) if d.current and d.current.total_episodes else ''} eps"
           if d.is_multi else f"{len(d.episodes)} eps") for d in dramas]
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
    _, svc, _ = deps(context)
    await update.message.reply_text(svc.stats_text(), parse_mode="HTML")


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
        "/add — new drama wizard\n/addep &lt;drama&gt; [sN] — add episodes\n"
        "/newseason &lt;drama&gt; [total_eps]\n/complete &lt;drama&gt; [sN]\n"
        "/edit &lt;id&gt; &lt;field&gt; &lt;value&gt;  (also: /edit &lt;id&gt; sN total 16)\n"
        "/delete &lt;drama&gt; [sN]\n/list\n/stats\n/reports — open viewer reports\n"
        "/schedule &lt;drama|-&gt; YYYY-MM-DD HH:MM &lt;text&gt;\n/schedules, /unschedule &lt;id&gt;\n"
        "/cleanup\n/digest — post today's digest now\n/cancel", parse_mode="HTML")


def handlers():
    return [
        CommandHandler("complete", complete), CommandHandler("newseason", newseason),
        CommandHandler("edit", edit), CommandHandler("delete", delete),
        CallbackQueryHandler(delete_season_confirm, pattern=r"^(delok:\d+:\d+|delno)$"),
        CommandHandler("list", list_cmd), CallbackQueryHandler(list_page, pattern=r"^list:\d+$"),
        CommandHandler("stats", stats), CommandHandler("schedule", schedule),
        CommandHandler("schedules", schedules), CommandHandler("unschedule", unschedule),
        CommandHandler("cleanup", cleanup), CommandHandler("digest", digest_now),
        CommandHandler("admin", admin_help), CommandHandler("cancel", cancel_poster),
        MessageHandler(filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE), poster_photo),
    ]
