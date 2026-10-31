"""Inline keyboards. Callback data formats:
  eps:<drama_id>:<page>   episode page on a drama card
  back:<drama_id>         back to the card's main keyboard
  dr:<drama_id>           open a drama card (DM)
  br:<kind>:<page>[:arg]  browse lists (ongoing|completed|latest|genre|search|genres)
  list:<page>             admin /list pagination
  st:<Ongoing|Completed>  wizard status choice
"""
from math import ceil

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

PER_PAGE = 10


def card_keyboard(drama, bot_username: str | None = None) -> M:
    rows = [[B(f"📺 Browse episodes ({len(drama.episodes)})", callback_data=f"eps:{drama.id}:0")]]
    if bot_username:
        rows.append([B("🙋 Request a drama", url=f"https://t.me/{bot_username}?start=request"),
                     B("🔎 Search", url=f"https://t.me/{bot_username}?start=browse")])
    return M(rows)


def episodes_keyboard(drama, page: int = 0, per_page: int = PER_PAGE) -> M:
    eps = drama.episodes
    pages = max(1, ceil(len(eps) / per_page))
    page = max(0, min(page, pages - 1))
    chunk = eps[page * per_page:(page + 1) * per_page]
    rows, row = [], []
    for e in chunk:
        row.append(B(f"EP {e.number}", url=e.url))
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


def main_menu() -> M:
    return M([
        [B("🔎 Search", callback_data="br:search:0"), B("🆕 Latest", callback_data="br:latest:0")],
        [B("🔄 Ongoing", callback_data="br:ongoing:0"), B("✅ Completed", callback_data="br:completed:0")],
        [B("🏷 Top genres", callback_data="br:genres:0"), B("🙋 Request drama", callback_data="br:request:0")],
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
