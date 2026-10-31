"""SQLite storage via SQLAlchemy 2.0."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, Text,
                        create_engine, func, or_, select)
from sqlalchemy.orm import (DeclarativeBase, Mapped, Session, mapped_column,
                            relationship, selectinload, sessionmaker)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Drama(Base):
    __tablename__ = "dramas"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    poster: Mapped[str | None] = mapped_column(String(500))  # Telegram file_id or URL
    synopsis: Mapped[str] = mapped_column(Text, default="")
    genres: Mapped[str] = mapped_column(String(300), default="")  # comma separated
    year: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="Ongoing")
    total_episodes: Mapped[int | None] = mapped_column(Integer)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="drama", order_by="Episode.number", cascade="all, delete-orphan")

    @property
    def genre_list(self) -> list[str]:
        return [g.strip() for g in self.genres.split(",") if g.strip()]


class Episode(Base):
    __tablename__ = "episodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    drama_id: Mapped[int] = mapped_column(ForeignKey("dramas.id"))
    number: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    drama: Mapped[Drama] = relationship(back_populates="episodes")


class Post(Base):
    """A message the bot sent to the channel. kind: card | service | scheduled | digest"""
    __tablename__ = "posts"
    id: Mapped[int] = mapped_column(primary_key=True)
    drama_id: Mapped[int | None] = mapped_column(ForeignKey("dramas.id"))
    chat_id: Mapped[str] = mapped_column(String(100))
    message_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    is_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Schedule(Base):
    __tablename__ = "schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    drama_id: Mapped[int | None] = mapped_column(ForeignKey("dramas.id"))
    run_at: Mapped[datetime] = mapped_column(DateTime)  # naive UTC
    text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|sent|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Request(Base):
    __tablename__ = "requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Database:
    def __init__(self, url: str = "sqlite:///kdrama.db"):
        self.engine = create_engine(url, future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        return self.Session()

    # ---- dramas -------------------------------------------------------
    def add_drama(self, **kw) -> Drama:
        links = kw.pop("links", [])
        start = kw.pop("start_episode", 1)
        with self.session() as s:
            d = Drama(**kw)
            d.episodes = [Episode(number=start + i, url=u) for i, u in enumerate(links)]
            s.add(d)
            s.commit()
            return self.get_drama(d.id)

    def get_drama(self, drama_id: int) -> Drama | None:
        with self.session() as s:
            d = s.get(Drama, drama_id)
            if d:
                _ = list(d.episodes)
            return d

    def find_drama(self, ref: str) -> Drama | None:
        ref = (ref or "").strip().strip('"')
        if not ref:
            return None
        if ref.isdigit():
            d = self.get_drama(int(ref))
            return d if d and not d.deleted else None
        with self.session() as s:
            q = select(Drama.id).where(Drama.deleted.is_(False))
            exact = s.scalars(q.where(func.lower(Drama.title) == ref.lower())).first()
            hit = exact or s.scalars(q.where(Drama.title.ilike(f"%{ref}%")).order_by(Drama.id.desc())).first()
        return self.get_drama(hit) if hit else None

    def update_drama(self, drama_id: int, **fields) -> Drama:
        with self.session() as s:
            d = s.get(Drama, drama_id)
            for k, v in fields.items():
                setattr(d, k, v)
            s.commit()
        return self.get_drama(drama_id)

    def add_episodes(self, drama_id: int, links: list[str], start: int | None = None) -> list[int]:
        with self.session() as s:
            d = s.get(Drama, drama_id)
            last = max((e.number for e in d.episodes), default=0)
            start = start or last + 1
            nums = []
            for i, u in enumerate(links):
                n = start + i
                existing = next((e for e in d.episodes if e.number == n), None)
                if existing:
                    existing.url = u
                else:
                    d.episodes.append(Episode(number=n, url=u))
                nums.append(n)
            if d.total_episodes and max(nums, default=0) > d.total_episodes:
                d.total_episodes = max(nums)
            s.commit()
            return nums

    def mark_deleted(self, drama_id: int) -> None:
        self.update_drama(drama_id, deleted=True)

    def list_dramas(self, status: str | None = None, genre: str | None = None,
                    offset: int = 0, limit: int = 10, order: str = "latest") -> tuple[list[Drama], int]:
        with self.session() as s:
            q = select(Drama).options(selectinload(Drama.episodes)).where(Drama.deleted.is_(False))
            if status:
                q = q.where(Drama.status == status)
            if genre:
                q = q.where(Drama.genres.ilike(f"%{genre}%"))
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            q = q.order_by(Drama.updated_at.desc() if order == "latest" else Drama.title)
            return list(s.scalars(q.offset(offset).limit(limit))), total

    def search(self, text: str, offset: int = 0, limit: int = 10) -> tuple[list[Drama], int]:
        text = text.strip()
        with self.session() as s:
            cond = or_(Drama.title.ilike(f"%{text}%"), Drama.genres.ilike(f"%{text}%"))
            if text.isdigit():
                cond = or_(cond, Drama.year == int(text))
            q = select(Drama).options(selectinload(Drama.episodes)).where(Drama.deleted.is_(False), cond)
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            return list(s.scalars(q.order_by(Drama.title).offset(offset).limit(limit))), total

    def top_genres(self, n: int = 8) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for d in self.list_dramas(limit=10_000)[0]:
            for g in d.genre_list:
                counts[g.title()] = counts.get(g.title(), 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    def episodes_since(self, since: datetime) -> dict[int, list[int]]:
        with self.session() as s:
            rows = s.execute(select(Episode.drama_id, Episode.number).join(Drama)
                             .where(Episode.created_at >= since, Drama.deleted.is_(False))
                             .order_by(Episode.number)).all()
        out: dict[int, list[int]] = {}
        for did, n in rows:
            out.setdefault(did, []).append(n)
        return out

    def stats(self, since: datetime) -> dict:
        with self.session() as s:
            alive = Drama.deleted.is_(False)
            cnt = lambda *w: s.scalar(select(func.count(Drama.id)).where(alive, *w))
            return {
                "dramas": cnt(),
                "ongoing": cnt(Drama.status == "Ongoing"),
                "completed": cnt(Drama.status == "Completed"),
                "episodes": s.scalar(select(func.count(Episode.id)).join(Drama).where(alive)),
                "posts_today": s.scalar(select(func.count(Post.id)).where(Post.created_at >= since)),
                "requests": s.scalar(select(func.count(Request.id))),
                "pending_schedules": s.scalar(select(func.count(Schedule.id)).where(Schedule.status == "pending")),
            }

    # ---- posts --------------------------------------------------------
    def add_post(self, chat_id, message_id: int, kind: str, drama_id=None, is_photo=False) -> Post:
        with self.session() as s:
            p = Post(chat_id=str(chat_id), message_id=message_id, kind=kind, drama_id=drama_id, is_photo=is_photo)
            s.add(p)
            s.commit()
            return p

    def card_post(self, drama_id: int) -> Post | None:
        with self.session() as s:
            return s.scalars(select(Post).where(Post.drama_id == drama_id, Post.kind == "card",
                                                Post.removed.is_(False)).order_by(Post.id.desc())).first()

    def card_by_message(self, chat_id, message_id: int) -> Post | None:
        with self.session() as s:
            return s.scalars(select(Post).where(Post.message_id == message_id, Post.kind == "card",
                                                Post.chat_id == str(chat_id))).first()

    def cleanup_candidates(self, older_than: datetime) -> list[Post]:
        with self.session() as s:
            old_service = select(Post).where(Post.removed.is_(False), Post.kind.in_(["service", "digest"]),
                                             Post.created_at < older_than)
            dead = select(Post).join(Drama, Post.drama_id == Drama.id).where(
                Post.removed.is_(False), Drama.deleted.is_(True))
            return list({p.id: p for p in [*s.scalars(old_service), *s.scalars(dead)]}.values())

    def mark_removed(self, post_id: int) -> None:
        with self.session() as s:
            s.get(Post, post_id).removed = True
            s.commit()

    # ---- schedules / requests ----------------------------------------
    def add_schedule(self, run_at: datetime, text: str, drama_id=None) -> Schedule:
        with self.session() as s:
            sc = Schedule(run_at=run_at, text=text, drama_id=drama_id)
            s.add(sc)
            s.commit()
            return sc

    def get_schedule(self, sid: int) -> Schedule | None:
        with self.session() as s:
            return s.get(Schedule, sid)

    def pending_schedules(self) -> list[Schedule]:
        with self.session() as s:
            return list(s.scalars(select(Schedule).where(Schedule.status == "pending").order_by(Schedule.run_at)))

    def set_schedule_status(self, sid: int, status: str) -> None:
        with self.session() as s:
            s.get(Schedule, sid).status = status
            s.commit()

    def add_request(self, user_id: int, username: str | None, text: str) -> Request:
        with self.session() as s:
            r = Request(user_id=user_id, username=username, text=text)
            s.add(r)
            s.commit()
            return r
