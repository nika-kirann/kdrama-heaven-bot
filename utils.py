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


DEFAULT_QUALITIES = ("480p", "720p", "1080p")
LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 +._-]{0,11}$")
INLINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9 +._-]{0,11}?)\s*[:=]\s*(.*)$")


def norm_quality(label: str) -> str:
    label = label.strip()
    if re.fullmatch(r"\d{3,4}[pP]", label):
        return label.lower()
    if re.fullmatch(r"\d{3,4}", label):
        return label + "p"
    return label.upper() if len(label) <= 3 else label


def parse_quality_links(text: str, total: int | None = None, start: int = 1) -> dict[int, list[tuple[str, str, str]]]:
    """Parse episode links grouped by quality. Returns {ep: [(quality, url, kind), ...]}.

    Accepted (mixable):
      480p: url1, url2            one line = one episode; comma-separated URLs = parts of that episode
      720p: urlA | urlB           ' | ' separated URLs = mirrors of the same episode
      1080p                       block header; each following URL line = next episode in that quality
      1080p: https://x/{ep}.mkv 1 16   pattern per quality (start/end optional; end defaults to total)
      https://x/1.mp4             legacy, no quality -> 'HD'
      EP 9                        following links start at episode 9
    Each quality numbers its episodes independently, starting at `start`."""
    text = (text or "").strip()
    if not text or text.lower() in {"skip", "none", "-", "/skip"}:
        return {}
    out: dict[int, list] = {}
    nxt: dict[str, int] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        content = line
        m = re.fullmatch(r"(?:ep|episode|start)\s*[:#]?\s*(\d+)", line, re.I)
        if m:  # 'EP 9' line: following links (all qualities) start at episode 9
            start, nxt = int(m.group(1)), {}
            continue
        if not line.lower().startswith(("http://", "https://")):
            m = INLINE_RE.match(line)
            if m:
                current, content = norm_quality(m.group(1)), m.group(2).strip()
                if not content:
                    continue
            elif LABEL_RE.match(line) and "://" not in line:
                current = norm_quality(line)
                continue
            else:
                raise ValueError(f"Can't read this line: {line[:60]}")
        q = current or "HD"
        if "{ep}" in content:
            parts = content.split()
            pattern = parts[0]
            s = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else nxt.get(q, start)
            e = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else (total or s)
            if not URL_RE.match(pattern.replace("{ep}", "1")):
                raise ValueError("Pattern must be an http(s) URL containing {ep}")
            if e < s:
                raise ValueError(f"{q}: end episode {e} is lower than start {s}")
            for n in range(s, e + 1):
                out.setdefault(n, []).append((q, pattern.replace("{ep}", str(n)), "part"))
            nxt[q] = e + 1
            continue
        if "|" in content:
            urls, kind = [u.strip() for u in content.split("|")], "mirror"
        else:
            urls, kind = [u.strip() for u in re.split(r"[,\s]+", content)], "part"
        urls = [u for u in urls if u]
        bad = [u for u in urls if not URL_RE.match(u)]
        if bad or not urls:
            raise ValueError(f"Not a valid http(s) link: {(bad or [content])[0][:60]}")
        n = nxt.get(q, start)
        out.setdefault(n, []).extend((q, u, kind) for u in urls)
        nxt[q] = n + 1
    if not out:
        raise ValueError("No valid http(s) link found")
    return out


def describe_links(eps: dict) -> str:
    if not eps:
        return "no links"
    quals = []
    for links in eps.values():
        for q, _, _ in links:
            if q not in quals:
                quals.append(q)
    nums = sorted(eps)
    rng = f"EP {nums[0]}" if len(nums) == 1 else f"EP {nums[0]}–{nums[-1]}"
    return f"{rng} ({', '.join(quals)})"


DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def parse_airdays(text: str) -> tuple[str, str | None]:
    """'Sat,Sun 20:00' -> ("5,6", "20:00"). Raises ValueError."""
    import re as _re
    text = (text or "").strip()
    m = _re.search(r"(\d{1,2}):(\d{2})\s*$", text)
    tm = None
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if hh > 23 or mm > 59:
            raise ValueError("time must be HH:MM")
        tm, text = f"{hh:02d}:{mm:02d}", text[:m.start()]
    days = []
    for part in _re.split(r"[,\s/&]+", text.strip()):
        if not part:
            continue
        key = part[:3].title()
        if key not in DAYS:
            raise ValueError(f"unknown day '{part}' (use Mon,Tue,Wed,Thu,Fri,Sat,Sun)")
        if DAYS.index(key) not in days:
            days.append(DAYS.index(key))
    if not days:
        raise ValueError("give at least one day, e.g. Sat,Sun 20:00")
    return ",".join(str(d) for d in sorted(days)), tm


def next_air(air_days: str | None, air_time: str | None, tz, now=None):
    """Next local air datetime (aware) or None. now: aware datetime (default: now)."""
    from datetime import datetime as _dt, timedelta as _td
    if not air_days:
        return None
    days = {int(x) for x in air_days.split(",") if x.strip().isdigit()}
    if not days:
        return None
    now = (now or _dt.now(tz)).astimezone(tz)
    hh, mm = (int(x) for x in (air_time or "00:00").split(":"))
    for i in range(8):
        day = now + _td(days=i)
        cand = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand.weekday() in days and (i > 0 or not air_time or cand >= now):
            return cand
    return None


def countdown_text(when, now) -> str:
    n = (when.date() - now.astimezone(when.tzinfo).date()).days
    rel = "today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days"
    return rel
