"""SQLite storage via SQLAlchemy 2.0."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (UniqueConstraint, Boolean, DateTime, ForeignKey, Integer, String, Text,
                        create_engine, event, func, inspect, or_, select, text)
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
    poster_msg_id: Mapped[int | None] = mapped_column(Integer)  # message in the storage channel
    synopsis: Mapped[str] = mapped_column(Text, default="")
    genres: Mapped[str] = mapped_column(String(300), default="")  # comma separated
    year: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="Ongoing")
    total_episodes: Mapped[int | None] = mapped_column(Integer)
    audio: Mapped[str | None] = mapped_column(String(100))  # e.g. "Korean, Eng Sub"; None = default
    imdb: Mapped[str | None] = mapped_column(String(10))    # e.g. "8.2"
    air_days: Mapped[str | None] = mapped_column(String(20))  # weekday numbers Mon=0, e.g. "5,6"
    air_time: Mapped[str | None] = mapped_column(String(5))   # "HH:MM" local (IST)
    next_ep_date: Mapped[str | None] = mapped_column(String(10))  # "YYYY-MM-DD" override; cleared on /addep
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="drama", order_by="Episode.number", cascade="all, delete-orphan", lazy="selectin")
    seasons: Mapped[list["Season"]] = relationship(
        back_populates="drama", order_by="Season.number", cascade="all, delete-orphan", lazy="selectin")

    @property
    def genre_list(self) -> list[str]:
        return [g.strip() for g in self.genres.split(",") if g.strip()]

    @property
    def is_multi(self) -> bool:
        return len(self.seasons) > 1

    @property
    def current(self) -> "Season | None":
        if not self.seasons:
            return None
        ongoing = [x for x in self.seasons if x.status == "Ongoing"]
        return max(ongoing or self.seasons, key=lambda x: x.number)

    def season(self, number: int) -> "Season | None":
        return next((x for x in self.seasons if x.number == number), None)


class Season(Base):
    """One season of a drama. Episode numbers restart per season."""
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("drama_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    drama_id: Mapped[int] = mapped_column(ForeignKey("dramas.id"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="Ongoing")
    total_episodes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    drama: Mapped["Drama"] = relationship(back_populates="seasons")
    episodes: Mapped[list["Episode"]] = relationship(
        back_populates="season", order_by="Episode.number", lazy="selectin")


class Episode(Base):
    __tablename__ = "episodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    drama_id: Mapped[int] = mapped_column(ForeignKey("dramas.id"), index=True)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(String(1000))  # legacy single link (kept = first link)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    drama: Mapped[Drama] = relationship(back_populates="episodes")
    season: Mapped[Season | None] = relationship(back_populates="episodes")
    links: Mapped[list["EpisodeLink"]] = relationship(
        back_populates="episode", order_by="EpisodeLink.position", cascade="all, delete-orphan", lazy="selectin")

    def quality_groups(self) -> list[tuple[str, list["EpisodeLink"]]]:
        """[(quality, [links...]), ...] in entry order. Legacy rows without link rows -> HD."""
        if not self.links:
            return [("HD", [EpisodeLink(quality="HD", url=self.url, kind="part", position=0)])] if self.url else []
        groups: dict[str, list] = {}
        for l in self.links:
            groups.setdefault(l.quality, []).append(l)
        return list(groups.items())

    @property
    def link_count(self) -> int:
        return sum(len(v) for _, v in self.quality_groups())


class EpisodeLink(Base):
    """One download/watch link for an episode in a given quality. kind: part | mirror"""
    __tablename__ = "episode_links"
    id: Mapped[int] = mapped_column(primary_key=True)
    episode_id: Mapped[int] = mapped_column(ForeignKey("episodes.id"))
    quality: Mapped[str] = mapped_column(String(20), default="HD")
    url: Mapped[str] = mapped_column(String(1000))
    kind: Mapped[str] = mapped_column(String(10), default="part")
    position: Mapped[int] = mapped_column(Integer, default=0)
    episode: Mapped[Episode] = relationship(back_populates="links")


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


class User(Base):
    """Anyone who talked to the bot. started = the bot may DM them; blocked = they blocked the bot."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(100))
    started: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (UniqueConstraint("user_id", "drama_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    drama_id: Mapped[int] = mapped_column(ForeignKey("dramas.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Click(Base):
    """A viewer opened a quality's links (ql: callback)."""
    __tablename__ = "clicks"
    id: Mapped[int] = mapped_column(primary_key=True)
    drama_id: Mapped[int] = mapped_column(Integer, index=True)
    season: Mapped[int | None] = mapped_column(Integer)
    episode: Mapped[int] = mapped_column(Integer)
    quality: Mapped[str] = mapped_column(String(20))
    user_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Report(Base):
    """A viewer's problem report (missing / misaligned episode, broken link...)."""
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    drama_id: Mapped[int] = mapped_column(Integer, index=True)
    season: Mapped[int | None] = mapped_column(Integer)  # season number; None for single-season / legacy
    episode: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open|fixed|dismissed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)


class Database:
    def __init__(self, url: str = "sqlite:///kdrama.db"):
        self.url = url
        self.on_commit = None  # callback set by the storage layer
        self.engine = create_engine(url, future=True)
        self._migrate()
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        event.listen(self.Session, "after_commit", self._after_commit)

    @property
    def path(self) -> str | None:
        return self.url[len("sqlite:///"):] if self.url.startswith("sqlite:///") else None

    def _after_commit(self, _session):
        if self.on_commit:
            self.on_commit()

    def _migrate(self):
        Base.metadata.create_all(self.engine)
        cols = {c["name"] for c in inspect(self.engine).get_columns("dramas")}
        if "poster_msg_id" not in cols:
            with self.engine.begin() as c:
                c.execute(text("ALTER TABLE dramas ADD COLUMN poster_msg_id INTEGER"))
        for col, typ in (("audio", "VARCHAR(100)"), ("imdb", "VARCHAR(10)"),
                         ("air_days", "VARCHAR(20)"), ("air_time", "VARCHAR(5)"), ("next_ep_date", "VARCHAR(10)")):
            if col not in cols:
                with self.engine.begin() as c:
                    c.execute(text(f"ALTER TABLE dramas ADD COLUMN {col} {typ}"))
        # seasons: add season_id on episodes, then backfill Season 1 for every drama
        ep_cols = {c["name"] for c in inspect(self.engine).get_columns("episodes")}
        if "season_id" not in ep_cols:
            with self.engine.begin() as c:
                c.execute(text("ALTER TABLE episodes ADD COLUMN season_id INTEGER REFERENCES seasons(id)"))
        # reports.season / clicks.season (harmless if already present via create_all on fresh DB)
        for table, col, typ in (("reports", "season", "INTEGER"), ("clicks", "season", "INTEGER")):
            try:
                tcols = {c["name"] for c in inspect(self.engine).get_columns(table)}
            except Exception:
                continue
            if col not in tcols:
                with self.engine.begin() as c:
                    c.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
        self._backfill_seasons()

    def _backfill_seasons(self):
        """Non-destructive: every drama without seasons gets Season 1; orphan episodes join it."""
        with self.engine.begin() as c:
            drama_ids = [r[0] for r in c.execute(text("SELECT id FROM dramas")).fetchall()]
            for did in drama_ids:
                row = c.execute(text("SELECT id FROM seasons WHERE drama_id=:d AND number=1"),
                                {"d": did}).fetchone()
                if row:
                    sid = row[0]
                else:
                    st = c.execute(text("SELECT status, total_episodes FROM dramas WHERE id=:d"),
                                   {"d": did}).fetchone()
                    c.execute(text("INSERT INTO seasons (drama_id, number, status, total_episodes, created_at) "
                                   "VALUES (:d, 1, :st, :tot, CURRENT_TIMESTAMP)"),
                              {"d": did, "st": (st[0] if st else "Ongoing") or "Ongoing",
                               "tot": st[1] if st else None})
                    sid = c.execute(text("SELECT id FROM seasons WHERE drama_id=:d AND number=1"),
                                    {"d": did}).fetchone()[0]
                c.execute(text("UPDATE episodes SET season_id=:s WHERE drama_id=:d AND "
                               "(season_id IS NULL OR season_id=0)"), {"s": sid, "d": did})

    def reload(self):
        """Re-open the file after it was replaced (e.g. restored from Telegram)."""
        self.engine.dispose()
        self._migrate()

    def session(self) -> Session:
        return self.Session()

    # ---- dramas -------------------------------------------------------
    def add_drama(self, **kw) -> Drama:
        links = kw.pop("links", [])  # legacy: plain list -> HD
        start = kw.pop("start_episode", 1)
        episodes = kw.pop("episodes", None) or {start + i: [("HD", u, "part")] for i, u in enumerate(links)}
        total = kw.get("total_episodes")
        status = kw.get("status", "Ongoing")
        with self.session() as s:
            d = Drama(**kw)
            s.add(d)
            s.flush()
            s.add(Season(drama_id=d.id, number=1, status=status, total_episodes=total))
            s.commit()
            did = d.id
        if episodes:
            self.add_episodes(did, episodes, season=1)
        return self.get_drama(did)

    def get_drama(self, drama_id: int) -> Drama | None:
        with self.session() as s:
            d = s.get(Drama, drama_id)
            if d:
                _ = list(d.seasons)
                for sea in d.seasons:
                    _ = list(sea.episodes)
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
            # keep the current season in sync when callers still set drama-level fields
            if d.seasons and ("total_episodes" in fields or "status" in fields):
                sea = self._ensure_season(s, d, None)
                if "total_episodes" in fields:
                    sea.total_episodes = fields["total_episodes"]
                if "status" in fields and len(d.seasons) == 1:
                    sea.status = fields["status"]
            s.commit()
        return self.get_drama(drama_id)

    def _ensure_season(self, s: Session, d: Drama, number: int | None = None) -> Season:
        """Return the named season (default: current / Season 1), creating Season 1 if somehow missing."""
        if not d.seasons:
            sea = Season(drama_id=d.id, number=1, status=d.status or "Ongoing",
                         total_episodes=d.total_episodes)
            s.add(sea)
            s.flush()
            d.seasons.append(sea)
        if number is None:
            ongoing = [x for x in d.seasons if x.status == "Ongoing"]
            return max(ongoing or d.seasons, key=lambda x: x.number)
        sea = next((x for x in d.seasons if x.number == number), None)
        if not sea:
            raise ValueError(f"no season {number}")
        return sea

    def _sync_drama(self, d: Drama) -> None:
        """Mirror aggregate status / current total onto the drama row (keeps old readers happy)."""
        if not d.seasons:
            return
        d.status = "Ongoing" if any(x.status == "Ongoing" for x in d.seasons) else "Completed"
        ongoing = [x for x in d.seasons if x.status == "Ongoing"]
        cur = max(ongoing or d.seasons, key=lambda x: x.number)
        d.total_episodes = cur.total_episodes
        d.updated_at = utcnow()

    def add_episodes(self, drama_id: int, episodes, start: int | None = None,
                     season: int | None = None) -> list[int]:
        """episodes: {ep_number: [(quality, url, kind), ...]} or a legacy list of URLs.
        Adds to the given season (default: current). Episode numbers are per-season."""
        with self.session() as s:
            d = s.get(Drama, drama_id)
            sea = self._ensure_season(s, d, season)
            if isinstance(episodes, list):
                first = start or max((e.number for e in sea.episodes), default=0) + 1
                episodes = {first + i: [("HD", u, "part")] for i, u in enumerate(episodes)}
            by_num = {e.number: e for e in sea.episodes}
            had_eps = bool(by_num)
            for n in sorted(episodes):
                links = episodes[n]
                ep = by_num.get(n)
                if not ep:
                    ep = Episode(number=n, url=links[0][1], drama_id=d.id, season_id=sea.id)
                    sea.episodes.append(ep)
                    d.episodes.append(ep)
                    by_num[n] = ep
                elif not ep.links and ep.url:  # legacy row: materialise its link as HD first
                    ep.links.append(EpisodeLink(quality="HD", url=ep.url, kind="part", position=0))
                quals = {q for q, _, _ in links}
                ep.links = [l for l in ep.links if l.quality not in quals]
                pos = max((l.position for l in ep.links), default=-1) + 1
                for i, (q, u, kind) in enumerate(links):
                    ep.links.append(EpisodeLink(quality=q, url=u, kind=kind, position=pos + i))
                ep.url = ep.links[0].url
                ep.season_id = sea.id
                ep.drama_id = d.id
            nums = sorted(episodes)
            if sea.total_episodes and nums and nums[-1] > sea.total_episodes:
                sea.total_episodes = nums[-1]
            # Re-open a completed season only when it already had episodes (i.e. /addep on a finished season).
            # The /add wizard may create a Completed drama and seed its first episodes in one go.
            if sea.status == "Completed" and had_eps:
                sea.status = "Ongoing"
            self._sync_drama(d)
            s.commit()
            return nums

    def add_season(self, drama_id: int, total_episodes: int | None = None) -> Season:
        """Start the next season; drama becomes Ongoing; previous current season is left as-is."""
        with self.session() as s:
            d = s.get(Drama, drama_id)
            n = max((x.number for x in d.seasons), default=0) + 1
            sea = Season(drama_id=d.id, number=n, status="Ongoing", total_episodes=total_episodes)
            s.add(sea)
            d.seasons.append(sea)
            d.next_ep_date = None
            d.air_time = None
            self._sync_drama(d)
            s.commit()
            sid = sea.id
        return self.get_season(sid)

    def get_season(self, season_id: int) -> Season | None:
        with self.session() as s:
            sea = s.get(Season, season_id)
            if sea:
                _ = list(sea.episodes)
            return sea

    def update_season(self, drama_id: int, number: int, **fields) -> Season:
        with self.session() as s:
            d = s.get(Drama, drama_id)
            sea = self._ensure_season(s, d, number)
            for k, v in fields.items():
                setattr(sea, k, v)
            self._sync_drama(d)
            s.commit()
            sid = sea.id
        return self.get_season(sid)

    def complete_season(self, drama_id: int, number: int | None = None) -> tuple[Season, bool]:
        """Complete one season (default: current). Returns (season, drama_now_complete)."""
        with self.session() as s:
            d = s.get(Drama, drama_id)
            sea = self._ensure_season(s, d, number)
            sea.status = "Completed"
            self._sync_drama(d)
            done = d.status == "Completed"
            s.commit()
            sid = sea.id
        return self.get_season(sid), done

    def delete_season(self, drama_id: int, number: int) -> bool:
        """Remove one season and its episodes. Refuses to delete the last remaining season."""
        with self.session() as s:
            d = s.get(Drama, drama_id)
            if len(d.seasons) <= 1:
                return False
            sea = next((x for x in d.seasons if x.number == number), None)
            if not sea:
                return False
            for ep in list(sea.episodes):
                s.delete(ep)
            s.delete(sea)
            s.flush()
            self._sync_drama(d)
            s.commit()
            return True

    def rename_quality(self, drama_id: int, old: str, new: str | None) -> int:
        """Rename a quality on all episodes of a drama, or delete it when new is None."""
        n = 0
        with self.session() as s:
            d = s.get(Drama, drama_id)
            for ep in list(d.episodes):
                if not ep.links and ep.url and old.lower() == "hd":
                    ep.links.append(EpisodeLink(quality="HD", url=ep.url, kind="part", position=0))
                for l in list(ep.links):
                    if l.quality.lower() == old.lower():
                        n += 1
                        if new:
                            l.quality = new
                        else:
                            ep.links.remove(l)
                if ep.links:
                    ep.url = ep.links[0].url
                elif new is None:
                    d.episodes.remove(ep)
            s.commit()
        return n

    def links_per_quality(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for d in self.list_dramas(limit=100_000)[0]:
            for ep in d.episodes:
                for q, ls in ep.quality_groups():
                    out[q] = out.get(q, 0) + len(ls)
        return out

    def mark_deleted(self, drama_id: int) -> None:
        self.update_drama(drama_id, deleted=True)

    def list_dramas(self, status: str | None = None, genre: str | None = None,
                    offset: int = 0, limit: int = 10, order: str = "latest") -> tuple[list[Drama], int]:
        with self.session() as s:
            q = select(Drama).options(selectinload(Drama.episodes), selectinload(Drama.seasons).selectinload(Season.episodes)).where(Drama.deleted.is_(False))
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
            q = select(Drama).options(selectinload(Drama.episodes), selectinload(Drama.seasons).selectinload(Season.episodes)).where(Drama.deleted.is_(False), cond)
            total = s.scalar(select(func.count()).select_from(q.subquery()))
            return list(s.scalars(q.order_by(Drama.title).offset(offset).limit(limit))), total

    def top_genres(self, n: int = 8) -> list[tuple[str, int]]:
        counts: dict[str, int] = {}
        for d in self.list_dramas(limit=10_000)[0]:
            for g in d.genre_list:
                counts[g.title()] = counts.get(g.title(), 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]

    def episodes_since(self, since: datetime) -> dict[int, list[tuple[int, int]]]:
        """drama_id -> [(season_number, ep_number), ...] newest window, ordered."""
        with self.session() as s:
            rows = s.execute(
                select(Episode.drama_id, Season.number, Episode.number)
                .join(Drama, Drama.id == Episode.drama_id)
                .outerjoin(Season, Season.id == Episode.season_id)
                .where(Episode.created_at >= since, Drama.deleted.is_(False))
                .order_by(Season.number, Episode.number)).all()
        out: dict[int, list[tuple[int, int]]] = {}
        for did, snum, n in rows:
            out.setdefault(did, []).append((snum or 1, n))
        return out

    def stats(self, since: datetime) -> dict:
        with self.session() as s:
            alive = Drama.deleted.is_(False)
            cnt = lambda *w: s.scalar(select(func.count(Drama.id)).where(alive, *w))
            return {
                "dramas": cnt(),
                "ongoing": cnt(Drama.status == "Ongoing"),
                "completed": cnt(Drama.status == "Completed"),
                "seasons": s.scalar(select(func.count(Season.id)).join(Drama).where(alive)),
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

    # ---- users / follows / clicks ------------------------------------
    def touch_user(self, user_id: int, username: str | None = None, started: bool = False) -> bool:
        """Record a user; returns True if new. started=True when they messaged the bot in private."""
        with self.session() as s:
            u = s.get(User, user_id)
            new = u is None
            if new:
                u = User(id=user_id, username=username, started=started)
                s.add(u)
            elif (started and (not u.started or u.blocked)) or (username and u.username != username):
                u.started = u.started or started
                u.blocked = False if started else u.blocked
                u.username = username or u.username
            else:
                return False
            s.commit()
            return new

    def get_user(self, user_id: int) -> User | None:
        with self.session() as s:
            return s.get(User, user_id)

    def mark_blocked(self, user_id: int) -> None:
        with self.session() as s:
            u = s.get(User, user_id) or User(id=user_id)
            u.blocked, u.started = True, False
            s.merge(u)
            s.execute(Follow.__table__.delete().where(Follow.user_id == user_id))
            s.commit()

    def is_following(self, user_id: int, drama_id: int) -> bool:
        with self.session() as s:
            return s.scalar(select(func.count(Follow.id)).where(Follow.user_id == user_id,
                                                                 Follow.drama_id == drama_id)) > 0

    def set_follow(self, user_id: int, drama_id: int, on: bool) -> bool:
        with self.session() as s:
            f = s.scalars(select(Follow).where(Follow.user_id == user_id, Follow.drama_id == drama_id)).first()
            if on and not f:
                s.add(Follow(user_id=user_id, drama_id=drama_id))
            elif not on and f:
                s.delete(f)
            else:
                return on
            s.commit()
            return on

    def followers(self, drama_id: int) -> list[int]:
        with self.session() as s:
            return list(s.scalars(select(Follow.user_id).where(Follow.drama_id == drama_id).order_by(Follow.id)))

    def follows_of(self, user_id: int) -> list[Drama]:
        with self.session() as s:
            q = (select(Drama).join(Follow, Follow.drama_id == Drama.id)
                 .where(Follow.user_id == user_id, Drama.deleted.is_(False)).order_by(Drama.title))
            return list(s.scalars(q))

    def follower_counts(self, n: int = 5) -> tuple[int, list[tuple[str, int]]]:
        with self.session() as s:
            total = s.scalar(select(func.count(Follow.id)))
            rows = s.execute(select(Drama.title, func.count(Follow.id).label("c")).join(Follow, Follow.drama_id == Drama.id)
                             .where(Drama.deleted.is_(False)).group_by(Drama.id).order_by(text("c DESC")).limit(n)).all()
            return total, [(t, c) for t, c in rows]

    def add_click(self, drama_id: int, episode: int, quality: str, user_id: int | None = None,
                  season: int | None = None) -> None:
        with self.session() as s:
            s.add(Click(drama_id=drama_id, episode=episode, quality=quality, user_id=user_id, season=season))
            s.commit()

    def top_clicked(self, since: datetime | None = None, n: int = 5) -> list[tuple[str, int]]:
        with self.session() as s:
            q = select(Drama.title, func.count(Click.id).label("c")).join(Drama, Drama.id == Click.drama_id)
            if since:
                q = q.where(Click.created_at >= since)
            return [(t, c) for t, c in s.execute(q.group_by(Drama.id).order_by(text("c DESC")).limit(n)).all()]

    def top_qualities(self, since: datetime | None = None, n: int = 3) -> list[tuple[str, int]]:
        with self.session() as s:
            q = select(Click.quality, func.count(Click.id).label("c"))
            if since:
                q = q.where(Click.created_at >= since)
            return [(k, c) for k, c in s.execute(q.group_by(Click.quality).order_by(text("c DESC")).limit(n)).all()]

    def user_growth(self, start: datetime, days: int = 7) -> tuple[int, list[int]]:
        """(total users, new users per day for `days` days starting at UTC `start`)."""
        from datetime import timedelta
        with self.session() as s:
            total = s.scalar(select(func.count(User.id)))
            per = []
            for i in range(days):
                a, b = start + timedelta(days=i), start + timedelta(days=i + 1)
                per.append(s.scalar(select(func.count(User.id)).where(User.created_at >= a, User.created_at < b)))
            return total, per

    # ---- reports -------------------------------------------------------
    def last_report_at(self, user_id: int, drama_id: int) -> datetime | None:
        with self.session() as s:
            return s.scalar(select(func.max(Report.created_at)).where(Report.user_id == user_id,
                                                                      Report.drama_id == drama_id))

    def add_report(self, drama_id: int, user_id: int, username: str | None, reason: str,
                   episode: int | None = None, note: str | None = None,
                   season: int | None = None) -> Report:
        with self.session() as s:
            r = Report(drama_id=drama_id, user_id=user_id, username=username, reason=reason,
                       episode=episode, note=note, season=season)
            s.add(r)
            s.commit()
            return r

    def get_report(self, rid: int) -> Report | None:
        with self.session() as s:
            return s.get(Report, rid)

    def set_report_status(self, rid: int, status: str) -> Report | None:
        with self.session() as s:
            r = s.get(Report, rid)
            if r:
                r.status, r.resolved_at = status, utcnow()
                s.commit()
            return r

    def open_reports(self, limit: int = 30) -> tuple[int, list[Report]]:
        with self.session() as s:
            n = s.scalar(select(func.count(Report.id)).where(Report.status == "open"))
            rows = list(s.scalars(select(Report).where(Report.status == "open").order_by(Report.id).limit(limit)))
            return n, rows
