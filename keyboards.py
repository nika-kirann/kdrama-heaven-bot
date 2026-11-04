"""Inline keyboards. Callback data formats:
  eps:<drama_id>:<page>   episode page on a drama card
  ep:<drama_id>:<ep>:<page>          quality picker for one episode
  ql:<drama_id>:<ep>:<qidx>:<page>   parts/mirrors of one quality
  back:<drama_id>         back to the card's main keyboard
  dr:<drama_id>           open a drama card (DM)
  br:<kind>:<page>[:arg]  browse lists (ongoing|completed|latest|genre|search|genres)
  list:<page>             admin /list pagination
  st:<Ongoing|Completed>  wizard status choice
  fol:<drama_id>[:<1|0>]  follow toggle (or explicit follow/unfollow)
  my:follows              viewer's follows list
"""
from math import ceil

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

PER_PAGE = 10


def card_keyboard(drama, bot_username: str | None = None) -> M:
    n = len(drama.episodes)
    rows = [[B(f"▶️ Browse & Download · {n} EP" if n else "▶️ Browse episodes", callback_data=f"eps:{drama.id}:0")]]
    if bot_username:
        rows.append([B("💌 Request drama", url=f"https://t.me/{bot_username}?start=request"),
                     B("🔎 Search", url=f"https://t.me/{bot_username}?start=browse")])
    rows.append([B("🔔 Follow / Unfollow", callback_data=f"fol:{drama.id}")])
    return M(rows)


def episodes_keyboard(drama, page: int = 0, per_page: int = PER_PAGE) -> M:
    eps = drama.episodes
    pages = max(1, ceil(len(eps) / per_page))
    page = max(0, min(page, pages - 1))
    chunk = eps[page * per_page:(page + 1) * per_page]
    rows, row = [], []
    for e in chunk:
        groups = e.quality_groups()
        if len(groups) == 1 and len(groups[0][1]) == 1:  # single link (incl. legacy): open directly
            row.append(B(f"EP {e.number}", url=groups[0][1][0].url))
        else:
            row.append(B(f"EP {e.number}", callback_data=f"ep:{drama.id}:{e.number}:{page}"))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if page > 0:
        nav.append(B("⬅️ Prev", callback_data=f"eps:{drama.id}:{page - 1}"))
    nav.append(B(f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(B("Next ➡️", callback_data=f"eps:{drama.id}:{page + 1}"))
    rows.append(nav)
    rows.append([B("↩️ Back", callback_data=f"back:{drama.id}")])
    return M(rows)


def follow_button(drama_id: int, following: bool) -> B:
    return (B("🔕 Unfollow", callback_data=f"fol:{drama_id}:0") if following
            else B("🔔 Follow", callback_data=f"fol:{drama_id}:1"))


def with_follow(markup: M | None, drama_id: int, following: bool) -> M:
    """Private views: add (or replace) the per-viewer Follow/Unfollow button."""
    rows = [[b for b in r if not (b.callback_data or "").startswith("fol:")] for r in (markup.inline_keyboard if markup else [])]
    rows = [r for r in rows if r]
    rows.append([follow_button(drama_id, following)])
    return M(rows)


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


def _episode(drama, number):
    return next((e for e in drama.episodes if e.number == number), None)


def quality_keyboard(drama, number: int, page: int = 0) -> M | None:
    ep = _episode(drama, number)
    if not ep:
        return None
    rows, row = [], []
    for qi, (q, links) in enumerate(ep.quality_groups()):
        if len(links) == 1:
            row.append(B(f"🎞 {q}", url=links[0].url))
        else:
            what = "mirrors" if links[0].kind == "mirror" else "parts"
            row.append(B(f"🎞 {q} ({len(links)} {what})", callback_data=f"ql:{drama.id}:{number}:{qi}:{page}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([B(f"↩️ Back (EP {number})", callback_data=f"eps:{drama.id}:{page}")])
    return M(rows)


def links_keyboard(drama, number: int, qidx: int, page: int = 0) -> M | None:
    ep = _episode(drama, number)
    groups = ep.quality_groups() if ep else []
    if qidx >= len(groups):
        return None
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
    rows.append([B("↩️ Qualities", callback_data=f"ep:{drama.id}:{number}:{page}")])
    return M(rows)
