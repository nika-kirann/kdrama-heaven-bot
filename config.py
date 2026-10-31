"""Configuration loaded from environment / .env."""
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _ids(raw: str) -> set[int]:
    out = set()
    for part in (raw or "").replace(" ", "").split(","):
        if part.lstrip("-").isdigit():
            out.add(int(part))
    return out


def _channel(raw: str):
    raw = (raw or "").strip()
    return int(raw) if raw.lstrip("-").isdigit() else raw


@dataclass
class Config:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", "").strip())
    channel_id: object = field(default_factory=lambda: _channel(os.getenv("CHANNEL_ID", "@kdrama_heaven")))
    admin_ids: set = field(default_factory=lambda: _ids(os.getenv("ADMIN_IDS", "")))
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Kolkata"))
    daily_digest_time: str = field(default_factory=lambda: os.getenv("DAILY_DIGEST_TIME", "10:00"))
    cleanup_days: int = field(default_factory=lambda: int(os.getenv("CLEANUP_DAYS", "7")))
    cleanup_time: str = field(default_factory=lambda: os.getenv("CLEANUP_TIME", "03:30"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///kdrama.db"))
    episodes_per_page: int = 10

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


config = Config()
