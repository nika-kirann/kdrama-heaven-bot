"""Persistence backends.

local    - SQLite file on disk only (default; current behaviour).
telegram - the SQLite file is mirrored to a private Telegram "storage channel":
           * startup: the pinned backup document is downloaded before polling starts
           * every DB commit schedules a debounced flush (default 3 s) that replaces the
             pinned document (edit_message_media; falls back to send + pin)
           * clean shutdown: a final flush
           * posters are re-sent to the storage channel; the resulting file_id + message id
             are kept in the DB, so they survive any disk loss.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone

from telegram import InputFile, InputMediaDocument
from telegram.error import BadRequest, TelegramError

log = logging.getLogger(__name__)
BACKUP_PREFIX = "kdrama-backup"
BACKUP_NAME = f"{BACKUP_PREFIX}.db"


class LocalStorage:
    backend = "local"

    async def restore(self) -> bool:
        return False

    def schedule_flush(self) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def store_poster(self, poster: str):
        return poster, None


class TelegramStorage:
    backend = "telegram"

    def __init__(self, bot, chat_id, db_path: str, delay: float = 3.0, cache_dir: str | None = None):
        self.bot, self.chat_id, self.db_path, self.delay = bot, chat_id, db_path, delay
        self.cache_dir = cache_dir          # optional local poster cache (None = off)
        self.backup_msg_id: int | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.flushes = 0
        self.enabled = False                # flushes are ignored until restore() ran

    # ---------------- database ----------------
    async def restore(self) -> bool:
        """Download the pinned backup into db_path. Returns True if a backup was restored."""
        self._loop = asyncio.get_running_loop()
        self.enabled = True
        chat = await self.bot.get_chat(self.chat_id)
        pm = chat.pinned_message
        doc = getattr(pm, "document", None) if pm else None
        if not doc or not (doc.file_name or "").startswith(BACKUP_PREFIX):
            log.info("Telegram storage: no backup found in %s, starting fresh", self.chat_id)
            return False
        self.backup_msg_id = pm.message_id
        f = await self.bot.get_file(doc.file_id)
        tmp = self.db_path + ".download"
        await f.download_to_drive(tmp)
        with open(tmp, "rb") as fh:
            if fh.read(16) != b"SQLite format 3\x00":
                os.remove(tmp)
                log.error("Telegram storage: pinned backup is not a SQLite file; ignoring it")
                return False
        os.replace(tmp, self.db_path)
        log.info("Telegram storage: restored DB from message %s (%s bytes)", pm.message_id, doc.file_size)
        return True

    def schedule_flush(self) -> None:
        """Called after every commit (may be any thread). Debounced."""
        if not self.enabled or not self._loop or self._loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._arm()
        else:
            self._loop.call_soon_threadsafe(self._arm)

    def _arm(self):
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = self._loop.create_task(self._delayed())

    async def _delayed(self):
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            return
        try:
            await self.flush()
        except Exception:
            log.exception("Telegram storage: flush failed (will retry on next write)")

    def _snapshot(self) -> bytes:
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            src, dst = sqlite3.connect(self.db_path), sqlite3.connect(tmp)
            with dst:
                src.backup(dst)
            src.close(); dst.close()
            with open(tmp, "rb") as fh:
                return fh.read()
        finally:
            os.remove(tmp)

    async def flush(self) -> None:
        if not self.enabled:
            return
        async with self._lock:
            data = self._snapshot()
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            caption = f"🗄 kdrama bot DB backup · {stamp} · {len(data)} bytes. Keep pinned, don't delete."
            if self.backup_msg_id:
                try:
                    await self.bot.edit_message_media(
                        chat_id=self.chat_id, message_id=self.backup_msg_id,
                        media=InputMediaDocument(InputFile(data, filename=BACKUP_NAME), caption=caption))
                    self.flushes += 1
                    return
                except BadRequest as e:
                    if "not modified" in str(e).lower():
                        return
                    log.warning("Telegram storage: edit failed (%s); sending a new backup", e)
            msg = await self.bot.send_document(chat_id=self.chat_id, document=InputFile(data, filename=BACKUP_NAME),
                                               caption=caption, disable_notification=True)
            old, self.backup_msg_id = self.backup_msg_id, msg.message_id
            await self.bot.pin_chat_message(chat_id=self.chat_id, message_id=msg.message_id, disable_notification=True)
            if old:
                try:
                    await self.bot.delete_message(chat_id=self.chat_id, message_id=old)
                except TelegramError:
                    pass
            self.flushes += 1

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        if self.enabled:
            try:
                await self.flush()
                log.info("Telegram storage: final flush done")
            except Exception:
                log.exception("Telegram storage: final flush failed")
        self.enabled = False

    # ---------------- posters ----------------
    async def store_poster(self, poster: str):
        """Send the poster (file_id or URL) to the storage channel; return (file_id, message_id)."""
        msg = await self.bot.send_photo(chat_id=self.chat_id, photo=poster, caption="🖼 poster",
                                        disable_notification=True)
        fid = msg.photo[-1].file_id
        if self.cache_dir:
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                f = await self.bot.get_file(fid)
                await f.download_to_drive(os.path.join(self.cache_dir, f"{msg.photo[-1].file_unique_id}.jpg"))
            except Exception:
                log.warning("Poster cache download failed", exc_info=True)
        return fid, msg.message_id

    async def poster_bytes(self, file_id: str) -> bytes:
        f = await self.bot.get_file(file_id)
        return bytes(await f.download_as_bytearray())


def make_storage(cfg, bot, db_path: str):
    if cfg.storage_backend == "telegram":
        return TelegramStorage(bot, cfg.storage_channel_id or cfg.channel_id, db_path,
                               delay=cfg.flush_delay, cache_dir=cfg.poster_cache_dir or None)
    return LocalStorage()
