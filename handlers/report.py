"""Viewer problem reports (missing / misaligned episode, broken link) -> admin DMs with Fixed/Dismiss."""
import logging
from datetime import timedelta

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler

import keyboards as kb
from db import utcnow
from utils import h, safe_call
from .common import admin_only, deps

log = logging.getLogger(__name__)
COOLDOWN = timedelta(minutes=10)
EP_REASONS = {"m", "w", "b"}
STATUS_LABEL = {"fixed": "✅ Marked fixed", "dismissed": "🗑 Dismissed"}


def _cooldown_left(db, uid, drama_id):
    last = db.last_report_at(uid, drama_id)
    if last and utcnow() - last < COOLDOWN:
        return max(1, int((COOLDOWN - (utcnow() - last)).total_seconds() // 60) + 1)
    return 0


def _who(u):
    return f"@{h(u.username)}" if u.username else h(u.full_name or str(u.id))


async def begin(send, context, uid, d):
    """Shared entry for the private ⚠️ Report button and /start report_<id>."""
    db, _, _ = deps(context)
    left = _cooldown_left(db, uid, d.id)
    if left:
        return await send(f"⏳ You already reported <b>{h(d.title)}</b> recently. "
                          f"Please wait about {left} min before sending another.", parse_mode=ParseMode.HTML)
    context.user_data.pop("awaiting", None)
    context.user_data["report"] = {"drama": d.id}
    await send(f"⚠️ <b>Report a problem</b> · {h(d.title)}\nWhat's wrong?",
               parse_mode=ParseMode.HTML, reply_markup=kb.report_reasons(d.id))


async def on_report(update: Update, context):
    db, _, _ = deps(context)
    q = update.callback_query
    d = db.get_drama(int(q.data.split(":")[1]))
    if not d or d.deleted:
        return await q.answer("That drama is no longer available.", show_alert=True)
    await q.answer()
    await begin(q.message.reply_text, context, q.from_user.id, d)


async def on_reason(update: Update, context):
    db, _, _ = deps(context)
    q = update.callback_query
    _, did, code = q.data.split(":")
    d = db.get_drama(int(did))
    if not d or d.deleted or code not in kb.REPORT_REASONS:
        return await q.answer("That drama is no longer available.", show_alert=True)
    await q.answer()
    context.user_data["report"] = {"drama": d.id, "reason": code}
    label = kb.REPORT_REASONS[code]
    if code in EP_REASONS:
        context.user_data["awaiting"] = "report_ep"
        last = d.episodes[-1].number if d.episodes else 0
        return await safe_call(q.edit_message_text,
                               f"⚠️ <b>{h(d.title)}</b> · {label}\nWhich episode? Send a number"
                               + (f" (1–{last})" if last else "") + ", or tap Skip.",
                               parse_mode=ParseMode.HTML, reply_markup=kb.skip("ep"))
    context.user_data["awaiting"] = "report_note"
    await safe_call(q.edit_message_text, f"⚠️ <b>{h(d.title)}</b> · {label}\n"
                    "Describe the problem in a message, or tap Skip.",
                    parse_mode=ParseMode.HTML, reply_markup=kb.skip("note"))


async def _ask_note(send):
    await send("📝 Any details to add? Send a short message, or tap Skip.", reply_markup=kb.skip("note"))


async def on_skip(update: Update, context):
    q = update.callback_query
    step = q.data.split(":")[1]
    rep = context.user_data.get("report")
    if not rep or "reason" not in rep:
        return await q.answer("This report expired. Tap ⚠️ Report again.", show_alert=True)
    await q.answer()
    if step == "ep":
        context.user_data["awaiting"] = "report_note"
        return await _ask_note(q.message.reply_text)
    context.user_data.pop("awaiting", None)
    await submit(q.message.reply_text, context, q.from_user, None)


async def on_text(update: Update, context, awaiting: str) -> None:
    """Called by the browse text handler while a report is in progress."""
    text = update.message.text.strip()
    rep = context.user_data.get("report") or {}
    if "reason" not in rep:
        return await update.message.reply_text("This report expired. Tap ⚠️ Report again.")
    if awaiting == "report_ep":
        n = text.lstrip("#").lower().removeprefix("ep").strip()
        if not n.isdigit() or not 0 < int(n) < 10000:
            context.user_data["awaiting"] = "report_ep"
            return await update.message.reply_text("Please send just the episode number, e.g. 7, or tap Skip.",
                                                   reply_markup=kb.skip("ep"))
        rep["episode"] = int(n)
        context.user_data["awaiting"] = "report_note"
        return await _ask_note(update.message.reply_text)
    await submit(update.message.reply_text, context, update.effective_user, text[:500])


async def submit(send, context, user, note):
    db, svc, _ = deps(context)
    rep = context.user_data.pop("report", None) or {}
    d = db.get_drama(rep.get("drama", 0))
    if not d or d.deleted:
        return await send("That drama is no longer available.")
    left = _cooldown_left(db, user.id, d.id)
    if left:
        return await send(f"⏳ You already reported this drama recently. Please wait about {left} min.")
    r = db.add_report(d.id, user.id, user.username, rep["reason"], rep.get("episode"), note or None)
    await svc.notify_admins(admin_text(r, d.title, _who(user)), kb.report_admin(r.id))
    await send(f"💜 Thanks! Report <code>#{r.id}</code> was sent to the admins. "
               "I'll message you when it's fixed.", parse_mode=ParseMode.HTML)


def admin_text(r, title, who):
    return (f"⚠️ <b>Report #{r.id}</b>\n"
            f"🎬 <b>{h(title)}</b> <code>#{r.drama_id}</code>\n"
            f"📺 Episode: {r.episode if r.episode else '-'}\n"
            f"❓ Reason: {kb.REPORT_REASONS.get(r.reason, r.reason)}\n"
            + (f"📝 {h(r.note)}\n" if r.note else "")
            + f"👤 From {who} (<code>{r.user_id}</code>)")


@admin_only
async def on_resolve(update: Update, context):
    db, _, _ = deps(context)
    q = update.callback_query
    kind, rid = q.data.split(":")
    r = db.get_report(int(rid))
    if not r:
        return await q.answer("Report not found.", show_alert=True)
    if r.status != "open":
        return await q.answer(f"Already {r.status}.", show_alert=True)
    status = "fixed" if kind == "rpf" else "dismissed"
    r = db.set_report_status(r.id, status)
    d = db.get_drama(r.drama_id)
    title = d.title if d else f"#{r.drama_id}"
    await q.answer(STATUS_LABEL[status])
    who = f"@{h(r.username)}" if r.username else str(r.user_id)
    await safe_call(q.edit_message_text, admin_text(r, title, who) + f"\n\n{STATUS_LABEL[status]} by {_who(q.from_user)}",
                    parse_mode=ParseMode.HTML)
    if status == "fixed":
        ep = f" EP {r.episode}" if r.episode else ""
        try:
            await safe_call(context.bot.send_message, r.user_id,
                            f"✅ Fixed! Your report <code>#{r.id}</code> for <b>{h(title)}</b>{ep} "
                            f"({kb.REPORT_REASONS.get(r.reason, r.reason)}) was resolved. Thanks for helping! 💜",
                            parse_mode=ParseMode.HTML)
        except Exception as e:
            log.info("Couldn't notify reporter %s: %s", r.user_id, e)


@admin_only
async def reports_cmd(update: Update, context):
    db, _, _ = deps(context)
    n, rows = db.open_reports()
    if not n:
        return await update.message.reply_text("✅ No open reports.")
    titles = {}
    lines = [f"⚠️ <b>Open reports</b> ({n})"]
    for r in rows:
        if r.drama_id not in titles:
            d = db.get_drama(r.drama_id)
            titles[r.drama_id] = d.title if d else f"#{r.drama_id}"
        who = f"@{h(r.username)}" if r.username else f"<code>{r.user_id}</code>"
        lines.append(f"<code>#{r.id}</code> {h(titles[r.drama_id])}"
                     f"{f' · EP {r.episode}' if r.episode else ''} · {kb.REPORT_REASONS.get(r.reason, r.reason)}"
                     f" · {who}" + (f"\n    📝 {h(r.note[:80])}" if r.note else ""))
    if n > len(rows):
        lines.append(f"…and {n - len(rows)} more")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
    for r in rows[:10]:
        await update.message.reply_text(f"#{r.id}", reply_markup=kb.report_admin(r.id))


def handlers():
    return [
        CallbackQueryHandler(on_report, pattern=r"^rep:\d+$"),
        CallbackQueryHandler(on_reason, pattern=r"^rr:\d+:[mwbo]$"),
        CallbackQueryHandler(on_skip, pattern=r"^rsk:(ep|note)$"),
        CallbackQueryHandler(on_resolve, pattern=r"^rp[fd]:\d+$"),
        CommandHandler("reports", reports_cmd),
    ]
