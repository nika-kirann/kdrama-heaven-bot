"""Configuration loaded from environment / .env."""
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

APP_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(APP_DIR, ".env"))


def _db_url(raw: str) -> str:
    """Relative sqlite paths are resolved against the app dir (works on ephemeral disks too)."""
    raw = (raw or "sqlite:///kdrama.db").strip()
    if raw.startswith("sqlite:///") and not raw.startswith("sqlite:////"):
        rel = raw[len("sqlite:///"):]
        if rel and rel != ":memory:" and not os.path.isabs(rel):
            return "sqlite:///" + os.path.join(APP_DIR, rel)
    return raw


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
    database_url: str = field(default_factory=lambda: _db_url(os.getenv("DATABASE_URL", "sqlite:///kdrama.db")))
    storage_backend: str = field(default_factory=lambda: os.getenv("STORAGE_BACKEND", "local").strip().lower() or "local")
    storage_channel_id: object = field(default_factory=lambda: _channel(os.getenv("STORAGE_CHANNEL_ID", "")) or None)
    flush_delay: float = field(default_factory=lambda: float(os.getenv("STORAGE_FLUSH_DELAY", "3")))
    poster_cache_dir: str = field(default_factory=lambda: os.getenv("POSTER_CACHE_DIR", ""))  # e.g. /tmp/posters
    episodes_per_page: int = 10
    default_audio: str = field(default_factory=lambda: os.getenv("DEFAULT_AUDIO", "Korean, Eng Sub"))
    brand: str = field(default_factory=lambda: os.getenv("BRAND", "").strip())  # footer handle; default = channel
    banner: bool = field(default_factory=lambda: os.getenv("GENERATE_BANNER", "1").strip().lower() not in {"0", "false", "no", "off"})

    notify_rate: float = field(default_factory=lambda: float(os.getenv("NOTIFY_RATE", "25")))  # follower DMs/sec
    countdown_time: str = field(default_factory=lambda: os.getenv("COUNTDOWN_TIME", "00:05"))
    weekly_summary: bool = field(default_factory=lambda: os.getenv("WEEKLY_SUMMARY", "1").strip().lower() not in {"0", "false", "no", "off"})
    weekly_summary_time: str = field(default_factory=lambda: os.getenv("WEEKLY_SUMMARY_TIME", "10:00"))
    admin_web_password: str = field(default_factory=lambda: os.getenv("ADMIN_WEB_PASSWORD", "").strip())
    admin_web_secret: str = field(default_factory=lambda: os.getenv("ADMIN_WEB_SECRET", "").strip())

    @property
    def brand_handle(self) -> str:
        if self.brand:
            return self.brand
        return self.channel_id if isinstance(self.channel_id, str) and self.channel_id.startswith("@") else "@kdrama_heaven"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


config = Config()
