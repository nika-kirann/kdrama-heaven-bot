"""Inline keyboards. Callback data formats:
  eps:<drama_id>:<page>              episode page (current/only season; legacy)
  eps:<drama_id>:<season>:<page>     episode page for a specific season
  ep:<drama_id>:<ep>:<page>          quality picker (current/only season; legacy)
  ep:<drama_id>:<season>:<ep>:<page> quality picker for a season
  ql:<drama_id>:<ep>:<qidx>:<page>   parts/mirrors (legacy)
  ql:<drama_id>:<season>:<ep>:<qidx>:<page>
  sea:<drama_id>                     season picker (multi-season only)
  back:<drama_id>                    back to the card's main keyboard
  back:<drama_id>:sea                back to the season picker
  dr:<drama_id>                      open a drama card (DM)
  br:<kind>:<page>[:arg]             browse lists
  list:<page>                        admin /list pagination
  st:<Ongoing|Completed>             wizard status choice
  fol:<drama_id>[:<1|0>]             follow toggle
  my:follows                         viewer's follows list
  rep:<drama_id>                     start a report (private)
  rr:<drama_id>:<m|w|b|o>            report reason;  rsk:<ep|note|sea> skip
  rs:<drama_id>:<season>             report: pick a season
  rpf:<report_id> / rpd:<report_id>  admin: mark fixed / dismiss
  delok:<drama_id>:<season> / delno  admin: confirm season delete
"""
from math import ceil

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

PER_PAGE = 10


def _sn(drama, season=None) -> int:
    if season is not None:
        return int(season)
    cur = getattr(drama, "current", None)
    return cur.number if cur else 1


def _eps(drama, season=None):
    sea = drama.season(_sn(drama, season)) if hasattr(drama, "season") else None
    if sea is not None:
        return list(sea.episodes)
    return list(getattr(drama, "episodes", []) or [])


def card_keyboard(drama, bot_username: str | None = None) -> M:
    if getattr(drama, "is_multi", False):
        n = len(drama.seasons)
        rows = [[B(f"▶️ Browse · {n} seasons", callback_data=f"sea:{drama.id}")]]
    else:
        n = len(_eps(drama))
        rows = [[B(f"▶️ Browse & Download · {n} EP" if n else "▶️ Browse episodes",
                   callback_data=f"eps:{drama.id}:0")]]
    if bot_username:
        rows.append([B("💌 Request drama", url=f"https://t.me/{bot_username}?start=request"),
                     B("🔎 Search", url=f"https://t.me/{bot_username}?start=browse")])
    follow = [B("🔔 Follow / Unfollow", callback_data=f"fol:{drama.id}")]
    if bot_username:
        follow.append(B("⚠️ Report", url=f"https://t.me/{bot_username}?start=report_{drama.id}"))
    rows.append(follow)
    return M(rows)


def seasons_keyboard(drama) -> M:
    rows = []
    for sea in drama.seasons:
        tot = f"/{sea.total_episodes}" if sea.total_episodes else ""
        mark = "✅" if sea.status == "Completed" else "🔄"
        rows.append([B(f"{mark} Season {sea.number} · {len(sea.episodes)}{tot} eps",
                       callback_data=f"eps:{drama.id}:{sea.number}:0")])
    rows.append([B("↩️ Back", callback_data=f"back:{drama.id}")])
    return M(rows)


def episodes_keyboard(drama, page: int = 0, per_page: int = PER_PAGE, season: int | None = None) -> M:
    sn = _sn(drama, season)
    eps = _eps(drama, sn)
    multi = getattr(drama, "is_multi", False)
    pages = max(1, ceil(len(eps) / per_page))
    page = max(0, min(page, pages - 1))
    chunk = eps[page * per_page:(page + 1) * per_page]
    rows, row = [], []
    for e in chunk:
        groups = e.quality_groups()
        # include season in callbacks whenever we know it (multi or explicit)
        if multi:
            cb = f"ep:{drama.id}:{sn}:{e.number}:{page}"
        else:
            cb = f"ep:{drama.id}:{e.number}:{page}"
        if len(groups) == 1 and len(groups[0][1]) == 1:  # single link (incl. legacy): open directly
            row.append(B(f"EP {e.number}", url=groups[0][1][0].url))
        else:
            row.append(B(f"EP {e.number}", callback_data=cb))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    eps_cb = (lambda p: f"eps:{drama.id}:{sn}:{p}") if multi else (lambda p: f"eps:{drama.id}:{p}")
    if page > 0:
        nav.append(B("⬅️ Prev", callback_data=eps_cb(page - 1)))
    nav.append(B(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(B("Next ➡️", callback_data=eps_cb(page + 1)))
    rows.append(nav)
    back = f"back:{drama.id}:sea" if multi else f"back:{drama.id}"
    rows.append([B("↩️ Back", callback_data=back)])
    return M(rows)


def follow_button(drama_id: int, following: bool) -> B:
    return (B("🔕 Unfollow", callback_data=f"fol:{drama_id}:0") if following
            else B("🔔 Follow", callback_data=f"fol:{drama_id}:1"))


def with_follow(markup: M | None, drama_id: int, following: bool) -> M:
    """Private views: add (or replace) the per-viewer Follow/Unfollow button."""
    def keep(b):
        return not ((b.callback_data or "").startswith(("fol:", "rep:")) or "start=report_" in (b.url or ""))
    rows = [[b for b in r if keep(b)] for r in (markup.inline_keyboard if markup else [])]
    rows = [r for r in rows if r]
    rows.append([B("⚠️ Report", callback_data=f"rep:{drama_id}")])
    rows.append([follow_button(drama_id, following)])
    return M(rows)


REPORT_REASONS = {"m": "Episode missing", "w": "Wrong or misaligned episode", "b": "Broken link", "o": "Other"}


def report_reasons(drama_id: int) -> M:
    return M([[B(f"{'🚫🔀🔗💬'[i]} {t}", callback_data=f"rr:{drama_id}:{k}")]
              for i, (k, t) in enumerate(REPORT_REASONS.items())])


def report_seasons(drama) -> M:
    rows = [[B(f"Season {sea.number}", callback_data=f"rs:{drama.id}:{sea.number}")]
            for sea in drama.seasons]
    rows.append([B("⏭ Skip", callback_data="rsk:sea")])
    return M(rows)


def skip(step: str) -> M:
    return M([[B("⏭ Skip", callback_data=f"rsk:{step}")]])


def report_admin(rid: int) -> M:
    return M([[B("✅ Mark fixed", callback_data=f"rpf:{rid}"), B("🗑 Dismiss", callback_data=f"rpd:{rid}")]])


def confirm_delete_season(drama_id: int, season: int) -> M:
    return M([[B(f"🗑 Yes, delete Season {season}", callback_data=f"delok:{drama_id}:{season}"),
               B("Cancel", callback_data="delno")]])


def main_menu() -> M:
    return M([
        [B("🔎 Search", callback_data="br:search:0"), B("🆕 Latest", callback_data="br:latest:0")],
        [B("🔄 Ongoing", callback_data="br:ongoing:0"), B("✅ Completed", callback_data="br:completed:0")],
        [B("🏷 Top genres", callback_data="br:genres:0"), B("🙋 Request drama", callback_data="br:request:0")],
        [B("🔔 My follows", callback_data="my:follows")],
    ])


def drama_list(dramas, total: int, page: int, kind: str, arg: str = "", per_page: int = PER_PAGE) -> M:
    rows = [[B(f"{'✅' if d.status == 'Completed' else '🔄'} {d.title}" + (f" ({d.year})" if d.year else ""),
               callback_data=f"dr:{d.id}")] for d in dramas]
    pages = max(1, ceil(total / per_page))
    nav = []
    suffix = f":{arg}" if arg else ""
    if page > 0:
        nav.append(B("⬅️ Prev", callback_data=f"{kind}:{page - 1}{suffix}"))
    nav.append(B(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(B("Next ➡️", callback_data=f"{kind}:{page + 1}{suffix}"))
    rows.append(nav)
    rows.append([B("🏠 Menu", callback_data="br:menu:0")])
    return M(rows)


def genres_keyboard(genres) -> M:
    rows = [[B(f"{g} ({n})", callback_data=f"br:genre:0:{g[:40]}")] for g, n in genres]
    rows.append([B("🏠 Menu", callback_data="br:menu:0")])
    return M(rows)


def status_keyboard() -> M:
    return M([[B("🔄 Ongoing", callback_data="st:Ongoing"), B("✅ Completed", callback_data="st:Completed")]])


def _episode(drama, number, season=None):
    return next((e for e in _eps(drama, season) if e.number == number), None)


def quality_keyboard(drama, number: int, page: int = 0, season: int | None = None) -> M | None:
    sn = _sn(drama, season)
    ep = _episode(drama, number, sn)
    if not ep:
        return None
    multi = getattr(drama, "is_multi", False)
    rows, row = [], []
    for qi, (q, links) in enumerate(ep.quality_groups()):
        if len(links) == 1:
            row.append(B(f"🎞 {q}", url=links[0].url))
        else:
            what = "mirrors" if links[0].kind == "mirror" else "parts"
            cb = (f"ql:{drama.id}:{sn}:{number}:{qi}:{page}" if multi
                  else f"ql:{drama.id}:{number}:{qi}:{page}")
            row.append(B(f"🎞 {q} ({len(links)} {what})", callback_data=cb))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    back = (f"eps:{drama.id}:{sn}:{page}" if multi else f"eps:{drama.id}:{page}")
    rows.append([B(f"↩️ Back (EP {number})", callback_data=back)])
    return M(rows)


def links_keyboard(drama, number: int, qidx: int, page: int = 0, season: int | None = None) -> M | None:
    sn = _sn(drama, season)
    ep = _episode(drama, number, sn)
    groups = ep.quality_groups() if ep else []
    if qidx >= len(groups):
        return None
    multi = getattr(drama, "is_multi", False)
    q, links = groups[qidx]
    word = "Mirror" if links[0].kind == "mirror" else "Part"
    rows, row = [], []
    for i, l in enumerate(links, 1):
        row.append(B(f"{q} {word} {i}", url=l.url))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    back = (f"ep:{drama.id}:{sn}:{number}:{page}" if multi else f"ep:{drama.id}:{number}:{page}")
    rows.append([B("↩️ Qualities", callback_data=back)])
    return M(rows)
