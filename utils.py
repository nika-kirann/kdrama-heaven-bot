"""Helpers: Telegram call retry (FloodWait/RetryAfter), parsing, formatting."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo

from telegram.error import BadRequest, RetryAfter, TimedOut, NetworkError

log = logging.getLogger(__name__)
URL_RE = re.compile(r"^https?://\S+$", re.I)
DT_RE = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})")


async def safe_call(fn, *args, retries: int = 3, **kwargs):
    """Call a Telegram API coroutine, sleeping on RetryAfter (flood wait) and retrying on timeouts.
    'message is not modified' is treated as success (returns None)."""
    for attempt in range(retries + 1):
        try:
            return await fn(*args, **kwargs)
        except RetryAfter as e:
            wait = e.retry_after.total_seconds() if hasattr(e.retry_after, "total_seconds") else float(e.retry_after)
            log.warning("Flood wait: sleeping %.1fs (attempt %d)", wait, attempt + 1)
            if attempt == retries:
                raise
            await asyncio.sleep(wait + 0.5)
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return None
            raise
        except (TimedOut, NetworkError) as e:
            if attempt == retries:
                raise
            log.warning("Network issue %s, retrying", e)
            await asyncio.sleep(2 * (attempt + 1))


def h(text) -> str:
    return escape(str(text or ""), quote=False)


def parse_links(text: str, total: int | None = None) -> tuple[list[str], int | None]:
    """Parse episode links. Either one URL per line, or a pattern containing {ep}
    optionally followed by a start episode: 'https://x/{ep}.mp4 3'.
    Returns (links, start_episode or None). Raises ValueError on bad input."""
    text = (text or "").strip()
    if not text or text.lower() in {"skip", "none", "-"}:
        return [], None
    if "{ep}" in text:
        parts = text.split()
        pattern = parts[0]
        start = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        end = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else (total or start)
        if not URL_RE.match(pattern.replace("{ep}", "1")):
            raise ValueError("Pattern must be an http(s) URL containing {ep}")
        if end < start:
            raise ValueError("Total episodes is lower than the start episode")
        return [pattern.replace("{ep}", str(n)) for n in range(start, end + 1)], start
    links = [l.strip() for l in text.splitlines() if l.strip()]
    bad = [l for l in links if not URL_RE.match(l)]
    if bad:
        raise ValueError(f"Not a valid http(s) link: {bad[0][:60]}")
    return links, None


def parse_local_dt(text: str, tz: ZoneInfo) -> tuple[datetime, int, int]:
    """Find 'YYYY-MM-DD HH:MM' in text. Returns (naive UTC datetime, span start, span end)."""
    m = DT_RE.search(text)
    if not m:
        raise ValueError("Use the format YYYY-MM-DD HH:MM")
    local = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    return local.astimezone(timezone.utc).replace(tzinfo=None), m.start(), m.end()


def local_midnight_utc(tz: ZoneInfo, now: datetime | None = None) -> datetime:
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)


def parse_hhmm(s: str) -> tuple[int, int]:
    hh, mm = s.strip().split(":")
    return int(hh), int(mm)
