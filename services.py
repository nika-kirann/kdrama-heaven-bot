"""Channel operations, independent of update handling so they're easy to test with a fake bot."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from telegram.constants import ParseMode
from telegram.error import TelegramError

import keyboards as kb
from db import Database, Drama, utcnow
from utils import h, local_midnight_utc, safe_call

log = logging.getLogger(__name__)
CAPTION_LIMIT = 1024


def badge(status: str) -> str:
    return "COMPLETED ✅" if status == "Completed" else "ONGOING 🔄"


def drama_card(d: Drama, limit: int = CAPTION_LIMIT) -> str:
    eps = len(d.episodes)
    total = f"/{d.total_episodes}" if d.total_episodes else ""
    tags = " ".join("#" + "".join(ch for ch in g.title() if ch.isalnum()) for g in d.genre_list)
    head = (f"🎬 <b>{h(d.title)}</b>" + (f" ({d.year})" if d.year else "") + "\n"
            f"<b>Status:</b> {badge(d.status)}\n"
            f"<b>Episodes:</b> {eps}{total}\n"
            + (f"<b>Genres:</b> {h(', '.join(d.genre_list))}\n" if d.genre_list else ""))
    tail = f"\n\n{h(tags)}\n🆔 <code>{d.id}</code>" if tags else f"\n\n🆔 <code>{d.id}</code>"
    room = limit - len(head) - len(tail) - 10
    syn = d.synopsis or ""
    if len(h(syn)) > room:
        syn = syn[: max(0, room - 1)]
        while len(h(syn)) > room - 1 and syn:
            syn = syn[:-1]
        syn += "…"
    return head + (f"\n📝 {h(syn)}" if syn else "") + tail


class ChannelService:
    def __init__(self, bot, db: Database, cfg):
        self.bot, self.db, self.cfg = bot, db, cfg

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

    async def post_card(self, d: Drama):
        markup = kb.card_keyboard(d, self.username)
        if d.poster:
            msg = await safe_call(self.bot.send_photo, chat_id=self.cfg.channel_id, photo=d.poster,
                                  caption=drama_card(d), parse_mode=ParseMode.HTML, reply_markup=markup)
            photo = True
        else:
            msg = await safe_call(self.bot.send_message, chat_id=self.cfg.channel_id, text=drama_card(d, 4096),
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
        if p.is_photo:
            await safe_call(self.bot.edit_message_caption, chat_id=p.chat_id, message_id=p.message_id,
                            caption=drama_card(d), parse_mode=ParseMode.HTML, reply_markup=markup)
        else:
            await safe_call(self.bot.edit_message_text, chat_id=p.chat_id, message_id=p.message_id,
                            text=drama_card(d, 4096), parse_mode=ParseMode.HTML, reply_markup=markup)
        return True

    async def add_episodes(self, drama_id: int, links: list[str], start: int | None = None) -> list[int]:
        nums = self.db.add_episodes(drama_id, links, start)
        await self.refresh_card(drama_id)
        d = self.db.get_drama(drama_id)
        rng = f"{nums[0]}" if len(nums) == 1 else f"{nums[0]}–{nums[-1]}"
        await self._send(f"🆕 <b>New episodes</b>: {h(d.title)} — EP {rng} added! 📺", "service", drama_id)
        return nums

    async def complete(self, drama_id: int):
        self.db.update_drama(drama_id, status="Completed")
        await self.refresh_card(drama_id)
        d = self.db.get_drama(drama_id)
        await self._send(f"✅ <b>{h(d.title)}</b> is now COMPLETED! Binge all {len(d.episodes)} episodes.",
                         "service", drama_id)

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

    async def notify_admins(self, text: str):
        for aid in self.cfg.admin_ids:
            try:
                await safe_call(self.bot.send_message, chat_id=aid, text=text, parse_mode=ParseMode.HTML)
            except TelegramError as e:
                log.warning("Could not DM admin %s: %s (they must /start the bot first)", aid, e)
