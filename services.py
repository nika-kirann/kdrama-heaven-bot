"""Channel operations, independent of update handling so they're easy to test with a fake bot."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from telegram.constants import ParseMode
from telegram.error import TelegramError

import keyboards as kb
from db import Database, Drama, utcnow
import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden

from utils import DAYS, countdown_text, describe_links, h, local_midnight_utc, safe_call

log = logging.getLogger(__name__)
CAPTION_LIMIT = 1024


def badge(status: str) -> str:
    return "COMPLETED ✅" if status == "Completed" else "ONGOING 🔄"



def qualities(d: Drama) -> list[str]:
    out = []
    for e in d.episodes:
        for q, _ in e.quality_groups():
            if q not in out:
                out.append(q)
    return out


LINE = "─" * 18
DEFAULT_AUDIO = "Korean, Eng Sub"


def _tag(text: str) -> str:
    return "#" + "".join(ch for ch in text.title() if ch.isalnum())


def audio_tags(d: Drama, default: str = DEFAULT_AUDIO) -> str:
    parts = [p.strip() for p in (getattr(d, "audio", None) or default or "").replace("/", ",").split(",") if p.strip()]
    return " ".join(f"[{p}]" for p in parts)


def _clip(text: str, room: int) -> str:
    """Cut text so its HTML-escaped length fits in room, on a word boundary, with an ellipsis."""
    if len(h(text)) <= room:
        return text
    cut = text[: max(0, room)]
    while cut and len(h(cut)) > room - 1:
        cut = cut[:-1]
    if " " in cut[-25:]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…" if cut else ""


def next_air_info(d: Drama, tz=None, now=None):
    """(episode number, local air datetime, has_time) for an ongoing drama, or None.
    Only shown when an admin set next_ep_date (today or later) via /edit <id> nextep."""
    if d.status == "Completed" or tz is None:
        return None
    ep = max((e.number for e in d.episodes), default=0) + 1
    if d.total_episodes and ep > d.total_episodes:
        return None
    from datetime import date as _date, datetime as _dt
    now = (now or _dt.now(tz)).astimezone(tz)
    tm = getattr(d, "air_time", None)
    hh, mm = (int(x) for x in (tm or "00:00").split(":"))
    nd = getattr(d, "next_ep_date", None)
    if nd:
        try:
            day = _date.fromisoformat(nd)
        except ValueError:
            day = None
        if day and day >= now.date():
            return ep, _dt(day.year, day.month, day.day, hh, mm, tzinfo=tz), bool(tm)
    return None


def next_line(d: Drama, tz=None, now=None) -> str | None:
    """Plain one-liner, e.g. 'Ep 7 · Sat 20:00 (in 2 days)'."""
    info = next_air_info(d, tz, now)
    if not info:
        return None
    ep, when, has_time = info
    from datetime import datetime as _dt
    t = f" {when:%H:%M}" if has_time else ""
    return f"Ep {ep} · {DAYS[when.weekday()]}{t} ({countdown_text(when, now or _dt.now(tz))})"


def next_block(d: Drama, tz=None, now=None) -> str:
    """Card block styled like a 'NEXT EPISODE' label with a yellow bar."""
    info = next_air_info(d, tz, now)
    if not info:
        return ""
    ep, when, has_time = info
    from datetime import datetime as _dt
    date = f"{when:%B} {when.day}, {when.year}"
    t = f" · {when:%I:%M %p}".replace(" 0", " ") + " IST" if has_time else ""
    rel = countdown_text(when, now or _dt.now(tz))
    return (f"\n🟨 <b>NEXT EPISODE</b>\n┃ <b>{date}</b>{t}\n"
            f"┃ <i>Ep {ep} · {DAYS[when.weekday()]} · {rel}</i>")


def drama_card(d: Drama, limit: int = CAPTION_LIMIT, brand: str = "@kdrama_heaven",
               default_audio: str = DEFAULT_AUDIO, tz=None, now=None) -> str:
    """Aesthetic HTML card (fits Telegram's 1024 caption / 4096 text limit)."""
    eps = len(d.episodes)
    total = f"/{d.total_episodes}" if d.total_episodes else ""
    q = qualities(d)
    sub = " · ".join(x for x in [str(d.year) if d.year else "", "K-Drama"] if x)
    rows = [("Status", f"<code>{badge(d.status)}</code>"),
            ("Episodes", f"<code>{eps}{total}</code>")]
    au = audio_tags(d, default_audio)
    if au:
        rows.append(("Audio", f"<code>{h(au)}</code>"))
    if q:
        rows.append(("Quality", f"<code>{h(' '.join(q))}</code>"))
    if getattr(d, "imdb", None):
        rows.append(("IMDb", f"⭐ {h(d.imdb)}/10"))
    head = (f"✦ <b>{h(d.title)}</b> ✦\n<i>{h(sub)}</i>\n\n╭{LINE}\n"
            + "".join(f"├ <b>{k}</b> · {v}\n" for k, v in rows) + f"╰{LINE}\n" + next_block(d, tz, now))
    if head.endswith("</i>") and (d.synopsis or "").strip():
        head += "\n"  # blank line between the NEXT EPISODE block and the synopsis
    tags = " ".join(_tag(g) for g in d.genre_list)
    tail = (f"\n{h(tags)}" if tags else "") + f"\n\n✦ <b>Powered by</b> {h(brand)}  ·  <code>#{d.id}</code>"
    room = limit - len(head) - len(tail) - len("\n<blockquote expandable></blockquote>") - 2
    syn = _clip((d.synopsis or "").strip(), room) if room > 20 else ""
    return head + (f"\n<blockquote expandable>{h(syn)}</blockquote>" if syn else "") + tail


class ChannelService:
    def __init__(self, bot, db: Database, cfg, storage=None):
        self.bot, self.db, self.cfg, self.storage = bot, db, cfg, storage

    async def persist_poster(self, poster: str | None) -> dict:
        """With telegram storage, copy the poster into the storage channel and keep its file_id."""
        if not poster or not self.storage or self.storage.backend != "telegram":
            return {"poster": poster}
        try:
            fid, mid = await self.storage.store_poster(poster)
            return {"poster": fid, "poster_msg_id": mid}
        except TelegramError as e:
            log.warning("Storing poster in Telegram failed (%s); keeping the original reference", e)
            return {"poster": poster}

    @property
    def username(self):
        try:
            return self.bot.username
        except Exception:
            return None

    async def _send(self, text: str, kind: str, drama_id=None, chat_id=None):
        chat = chat_id or self.cfg.channel_id
        msg = await safe_call(self.bot.send_message, chat_id=chat, text=text,
                              parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        self.db.add_post(msg.chat_id, msg.message_id, kind, drama_id)
        return msg

    def card(self, d: Drama, limit: int = CAPTION_LIMIT) -> str:
        return drama_card(d, limit, brand=self.cfg.brand_handle, default_audio=self.cfg.default_audio,
                          tz=self.cfg.tz, now=getattr(self, "now", None))

    def banner(self, d: Drama) -> bytes | None:
        if not getattr(self.cfg, "banner", False):
            return None
        try:
            from banner import render_banner
            return render_banner(d.title, d.status, d.genre_list, d.year, len(d.episodes), d.total_episodes,
                                 qualities(d), self.cfg.brand_handle)
        except Exception as e:  # Pillow missing or font issue -> plain text post
            log.warning("Banner render failed: %s", e)
            return None

    async def post_card(self, d: Drama):
        markup = kb.card_keyboard(d, self.username)
        photo = d.poster or self.banner(d)
        if photo:
            msg = await safe_call(self.bot.send_photo, chat_id=self.cfg.channel_id, photo=photo,
                                  caption=self.card(d), parse_mode=ParseMode.HTML, reply_markup=markup)
            photo = True
        else:
            msg = await safe_call(self.bot.send_message, chat_id=self.cfg.channel_id, text=self.card(d, 4096),
                                  parse_mode=ParseMode.HTML, reply_markup=markup)
            photo = False
        self.db.add_post(msg.chat_id, msg.message_id, "card", d.id, is_photo=photo)
        return msg

    async def refresh_card(self, drama_id: int, markup=None) -> bool:
        """Edit the channel card in place to reflect current DB state."""
        d = self.db.get_drama(drama_id)
        p = self.db.card_post(drama_id)
        if not d or not p:
            return False
        markup = markup or kb.card_keyboard(d, self.username)
        banner = self.banner(d) if p.is_photo and not d.poster else None
        if banner:  # generated banner shows status/episodes, so swap the image too
            from telegram import InputMediaPhoto
            await safe_call(self.bot.edit_message_media, chat_id=p.chat_id, message_id=p.message_id,
                            media=InputMediaPhoto(banner, caption=self.card(d), parse_mode=ParseMode.HTML),
                            reply_markup=markup)
        elif p.is_photo:
            await safe_call(self.bot.edit_message_caption, chat_id=p.chat_id, message_id=p.message_id,
                            caption=self.card(d), parse_mode=ParseMode.HTML, reply_markup=markup)
        else:
            await safe_call(self.bot.edit_message_text, chat_id=p.chat_id, message_id=p.message_id,
                            text=self.card(d, 4096), parse_mode=ParseMode.HTML, reply_markup=markup)
        return True

    async def set_poster(self, drama_id: int, poster: str) -> Drama:
        """Store a new poster (copied to the storage channel) and show it on the channel card."""
        changes = await self.persist_poster(poster)
        self.db.update_drama(drama_id, **changes)
        d = self.db.get_drama(drama_id)
        p = self.db.card_post(drama_id)
        if p and p.is_photo:
            from telegram import InputMediaPhoto
            try:
                await safe_call(self.bot.edit_message_media, chat_id=p.chat_id, message_id=p.message_id,
                                media=InputMediaPhoto(d.poster, caption=self.card(d), parse_mode=ParseMode.HTML),
                                reply_markup=kb.card_keyboard(d, self.username))
                return d
            except TelegramError as e:
                log.warning("Editing poster media failed (%s); reposting", e)
        if p:  # text post (or edit failed): a text post can't become a photo post
            await self._remove(p)
        await self.post_card(d)
        return d

    async def add_episodes(self, drama_id: int, episodes, start: int | None = None) -> list[int]:
        """episodes: {ep: [(quality, url, kind)]} or a legacy list of URLs."""
        if isinstance(episodes, list):
            first = start or max((e.number for e in self.db.get_drama(drama_id).episodes), default=0) + 1
            episodes = {first + i: [("HD", u, "part")] for i, u in enumerate(episodes)}
        nums = self.db.add_episodes(drama_id, episodes)
        if self.db.get_drama(drama_id).next_ep_date:  # the date was for this episode: hide the block
            self.db.update_drama(drama_id, next_ep_date=None, air_time=None)
        await self.refresh_card(drama_id)
        d = self.db.get_drama(drama_id)
        await self._send(f"🆕 <b>New episodes</b>: {h(d.title)} — {h(describe_links(episodes))} added! 📺",
                         "service", drama_id)
        await self.notify_followers(drama_id, f"🆕 {h(describe_links(episodes))} just landed!")
        return nums

    async def complete(self, drama_id: int):
        self.db.update_drama(drama_id, status="Completed")
        await self.refresh_card(drama_id)
        d = self.db.get_drama(drama_id)
        await self._send(f"✅ <b>{h(d.title)}</b> is now COMPLETED! Binge all {len(d.episodes)} episodes.",
                         "service", drama_id)
        await self.notify_followers(drama_id, f"✅ The series is complete. All {len(d.episodes)} episodes are up, binge time!")

    async def delete(self, drama_id: int) -> bool:
        self.db.mark_deleted(drama_id)
        p = self.db.card_post(drama_id)
        if p:
            return await self._remove(p)
        return True

    async def _remove(self, p) -> bool:
        try:
            await safe_call(self.bot.delete_message, chat_id=p.chat_id, message_id=p.message_id)
        except TelegramError as e:
            # Too old (>48h) or already gone: Telegram refuses. Mark it so we don't retry forever.
            log.warning("Could not delete message %s: %s", p.message_id, e)
            if "not found" not in str(e).lower() and "can't be deleted" not in str(e).lower():
                return False
        self.db.mark_removed(p.id)
        return True

    async def cleanup(self, now: datetime | None = None) -> int:
        now = now or utcnow()
        removed = 0
        for p in self.db.cleanup_candidates(now - timedelta(days=self.cfg.cleanup_days)):
            if await self._remove(p):
                removed += 1
        log.info("Cleanup removed %d messages", removed)
        return removed

    async def daily_digest(self, now: datetime | None = None):
        since = local_midnight_utc(self.cfg.tz, now) - timedelta(days=1)  # last 24h window up to today
        new = self.db.episodes_since(since)
        if not new:
            return None
        lines = ["📅 <b>New episodes today</b>\n"]
        for did, nums in new.items():
            d = self.db.get_drama(did)
            rng = f"EP {nums[0]}" if len(nums) == 1 else f"EP {nums[0]}–{nums[-1]}"
            lines.append(f"• <b>{h(d.title)}</b> — {rng} {'✅' if d.status == 'Completed' else '🔄'}")
        return await self._send("\n".join(lines), "digest")

    async def run_schedule(self, sid: int):
        sc = self.db.get_schedule(sid)
        if not sc or sc.status != "pending":
            return None
        try:
            d = self.db.get_drama(sc.drama_id) if sc.drama_id else None
            if d and not d.deleted and not self.db.card_post(d.id):
                await self.post_card(d)  # first-time scheduled card
            text = (f"🎬 <b>{h(d.title)}</b>\n" if d else "") + h(sc.text)
            msg = await self._send(text, "scheduled", d.id if d else None)
            self.db.set_schedule_status(sid, "sent")
            return msg
        except Exception:
            log.exception("Scheduled post %s failed", sid)
            self.db.set_schedule_status(sid, "failed")
            raise

    async def notify_admins(self, text: str, markup=None):
        for aid in self.cfg.admin_ids:
            try:
                await safe_call(self.bot.send_message, chat_id=aid, text=text, parse_mode=ParseMode.HTML,
                                reply_markup=markup)
            except TelegramError as e:
                log.warning("Could not DM admin %s: %s (they must /start the bot first)", aid, e)

    # ---------------- followers ----------------
    def deep_link(self, payload: str) -> str | None:
        return f"https://t.me/{self.username}?start={payload}" if self.username else None

    async def notify_followers(self, drama_id: int, headline: str) -> dict:
        """DM every follower (≈cfg.notify_rate msgs/sec). Blocked users are dropped,
        users who never started the bot are skipped (they can't be messaged)."""
        d = self.db.get_drama(drama_id)
        out = {"sent": 0, "blocked": 0, "skipped": 0}
        if not d:
            return out
        text = (f"🔔 <b>New for you</b> ✦\n\n✦ <b>{h(d.title)}</b> ✦\n{headline}\n\n"
                f"<i>{len(d.episodes)}{'/' + str(d.total_episodes) if d.total_episodes else ''} episodes · "
                f"{'COMPLETED ✅' if d.status == 'Completed' else 'ONGOING 🔄'}</i>")
        link = self.deep_link(f"drama_{d.id}")
        rows = [[InlineKeyboardButton("▶️ Watch now", url=link)]] if link else []
        rows.append([InlineKeyboardButton("🔕 Unfollow", callback_data=f"fol:{d.id}:0")])
        markup = InlineKeyboardMarkup(rows)
        delay = 1.0 / max(1.0, float(getattr(self.cfg, "notify_rate", 25)))
        for uid in self.db.followers(drama_id):
            u = self.db.get_user(uid)
            if u is not None and (u.blocked or not u.started):
                out["skipped"] += 1
                continue
            try:
                await safe_call(self.bot.send_message, chat_id=uid, text=text, parse_mode=ParseMode.HTML,
                                reply_markup=markup, disable_web_page_preview=True)
                out["sent"] += 1
            except Forbidden:
                self.db.mark_blocked(uid)
                out["blocked"] += 1
            except BadRequest as e:  # chat not found = never started the bot
                log.info("Follower %s unreachable: %s", uid, e)
                out["skipped"] += 1
            except TelegramError as e:
                log.warning("Follower DM to %s failed: %s", uid, e)
            if delay:
                await asyncio.sleep(delay)
        log.info("Follower alerts for %s: %s", drama_id, out)
        return out

    # ---------------- countdown ----------------
    async def refresh_countdowns(self) -> int:
        """Re-edit ongoing cards with a nextep date whose countdown line changed."""
        n = 0
        if not hasattr(self, "_countdown"):
            self._countdown = {}
        for d in self.db.list_dramas(status="Ongoing", limit=100_000)[0]:
            if not d.next_ep_date:
                continue
            line = next_line(d, self.cfg.tz, getattr(self, "now", None))
            if self._countdown.get(d.id) == line:
                continue
            try:
                if await self.refresh_card(d.id):
                    n += 1
                self._countdown[d.id] = line
            except TelegramError as e:
                log.warning("Countdown refresh for %s failed: %s", d.id, e)
        return n

    # ---------------- stats ----------------
    def stats_text(self) -> str:
        from datetime import timedelta as _td
        db, tz = self.db, self.cfg.tz
        today = local_midnight_utc(tz)
        week = today - _td(days=6)
        s = db.stats(today)
        top7, top_all = db.top_clicked(week), db.top_clicked()
        q7, qall = db.top_qualities(week), db.top_qualities()
        fol_total, fol_top = db.follower_counts()
        users, per = db.user_growth(week, 7)
        fmt = lambda rows: "\n".join(f"  {i}. {h(t)} · {c}" for i, (t, c) in enumerate(rows, 1)) or "  none yet"
        lpq = db.links_per_quality()
        return ("📊 <b>kdrama_heaven stats</b>\n"
                f"Dramas: {s['dramas']} (🔄 {s['ongoing']} ongoing / ✅ {s['completed']} completed)\n"
                f"Episodes: {s['episodes']} · Posts today: {s['posts_today']}\n"
                f"Requests: {s['requests']} · Pending schedules: {s['pending_schedules']}\n"
                f"⚠️ Open reports: {db.open_reports(0)[0]}\n"
                + (f"Links per quality: {', '.join(f'{h(q)} {n}' for q, n in lpq.items())}\n" if lpq else "")
                + f"\n🔥 <b>Top clicked (7d)</b>\n{fmt(top7)}\n🏆 <b>Top clicked (all-time)</b>\n{fmt(top_all)}\n"
                f"🎞 <b>Most-used quality</b>: "
                f"{h(q7[0][0]) + f' ({q7[0][1]} in 7d)' if q7 else '-'}"
                f"{' · all-time ' + h(qall[0][0]) + f' ({qall[0][1]})' if qall else ''}\n"
                f"\n🔔 <b>Followers</b>: {fol_total} follows\n{fmt(fol_top)}\n"
                f"\n👥 <b>Users</b>: {users} total, +{sum(per)} in 7d\n"
                f"  {' '.join(str(x) for x in per)}  (new/day, oldest→today)")

    async def weekly_summary(self):
        await self.notify_admins("🗓 <b>Weekly summary</b>\n\n" + self.stats_text())
