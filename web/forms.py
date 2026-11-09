"""HTML fragments for structured quality link forms (add drama + add episode)."""
from __future__ import annotations

import json

from . import html as H

QUALITIES = ("480p", "720p", "1080p")


def next_ep(sea) -> int:
    return max((e.number for e in (sea.episodes if sea else [])), default=0) + 1


def quality_blocks(prefix: str = "") -> str:
    """480p/720p/1080p blocks with Part 1 + ＋ Part / ＋ Mirror buttons.
    prefix unused for now (names stay 480p / 480p_mirror so parsers stay shared)."""
    blocks = []
    for q in QUALITIES:
        blocks.append(
            f'<div class="q-block" data-quality="{q}">'
            f'<div class="q-title">{q}</div>'
            f'<div class="q-parts">'
            f'<label>{q} · Part 1</label>'
            f'<input type="text" class="link" name="{q}" placeholder="https://…/{{ep}}.mkv" '
            f'inputmode="url" autocomplete="off" spellcheck="false">'
            f'</div>'
            f'<div class="q-mirrors"></div>'
            f'<div class="q-actions">'
            f'<button type="button" class="btn secondary btn-sm add-part" data-q="{q}">＋ Part</button>'
            f'<button type="button" class="btn secondary btn-sm add-mirror" data-q="{q}">＋ Mirror</button>'
            f'</div></div>'
        )
    return "".join(blocks)


def add_episode_form(d, csrf: str, *, err: str = "") -> str:
    """Episode # + 480p/720p/1080p URL fields with Part / Mirror add buttons."""
    cur = d.current
    next_map = {str(sea.number): next_ep(sea) for sea in d.seasons}
    default_sn = cur.number if cur else 1
    default_ep = next_map.get(str(default_sn), 1)
    if d.is_multi:
        opts = []
        for sea in d.seasons:
            sel = " selected" if sea.number == default_sn else ""
            cur_l = " (current)" if cur and sea.number == cur.number else ""
            opts.append(f'<option value="{sea.number}"{sel}>Season {sea.number}{cur_l}</option>')
        season_html = (
            '<div><label>Season</label>'
            f'<select name="season" id="addep-season">{"".join(opts)}</select></div>'
        )
    else:
        season_html = (
            f'<input type="hidden" name="season" id="addep-season" value="{default_sn}">'
        )
    err_html = (
        f'<div class="flash err" id="addep-err">{H.e(err)}</div>'
        if err else
        '<div class="flash err" id="addep-err" hidden></div>'
    )
    return (
        '<div class="card" id="add-episode">'
        '<h2>Add episode</h2>'
        '<p class="muted">Fill any qualities you have — empty ones are skipped. '
        'Use ＋ Part / ＋ Mirror for extra URLs.</p>'
        f'{err_html}'
        f'<form method="post" action="/admin/drama/addep" id="addep-form" '
        f"data-next='{H.e(json.dumps(next_map))}'>"
        f'{csrf}'
        f'<input type="hidden" name="drama_id" value="{d.id}">'
        '<div class="row">'
        f'{season_html}'
        '<div><label>Episode number</label>'
        f'<input name="episode" id="addep-ep" value="{default_ep}" '
        'inputmode="numeric" required min="1" max="9999"></div>'
        '</div>'
        f'{quality_blocks()}'
        '<div class="actions" style="margin-top:14px">'
        '<button class="btn" type="submit">Add episode</button>'
        '</div></form></div>'
    )


def add_drama_links_section(*, err: str = "") -> str:
    """From/To range + quality URL templates ({{ep}} expands) for the Add drama page."""
    err_html = (
        f'<div class="flash err" id="add-links-err">{H.e(err)}</div>'
        if err else
        '<div class="flash err" id="add-links-err" hidden></div>'
    )
    return (
        '<div class="ep-box" id="add-links">'
        '<h3 style="margin:0 0 6px">Season 1 episodes <span class="muted">(optional)</span></h3>'
        '<p class="muted" style="margin-top:0">Leave empty to create the drama with no episodes yet. '
        'Paste your links and put <code>{ep}</code> where the episode number goes. '
        'It will be replaced for every episode from → to when you create the drama.</p>'
        '<p class="muted" id="ep-expand-preview" style="color:var(--gold)"></p>'
        f'{err_html}'
        '<div class="row">'
        '<div><label>From episode</label>'
        '<input name="ep_from" id="ep-from" value="1" inputmode="numeric" min="1"></div>'
        '<div><label>To episode</label>'
        '<input name="ep_to" id="ep-to" value="" inputmode="numeric" min="1" '
        'placeholder="same as Total"></div>'
        '</div>'
        f'{quality_blocks()}'
        '</div>'
    )


def expand_quality_range(fields: dict, field_get, field_list) -> tuple[dict, str | None]:
    """Build {ep: [(quality, url, kind), ...]} from ep_from/ep_to + 480p/720p/1080p fields.
    Returns (episodes, error_message_or_None). Empty URLs → ({}, None)."""
    templates: list[tuple[str, str, str]] = []  # quality, url_template, kind
    for q in QUALITIES:
        for url in field_list(fields, q):
            templates.append((q, url, "part"))
        for url in field_list(fields, f"{q}_mirror"):
            templates.append((q, url, "mirror"))
    if not templates:
        return {}, None
    for _, url, _ in templates:
        if not url.lower().startswith(("http://", "https://")):
            return {}, "Every link must start with http:// or https://"
    fr = field_get(fields, "ep_from", "1").strip() or "1"
    to = field_get(fields, "ep_to", "").strip()
    if not to:
        total = field_get(fields, "total", "").strip()
        to = total if total.isdigit() else fr
    if not fr.isdigit() or not to.isdigit():
        return {}, "From/To episode must be numbers"
    a, b = int(fr), int(to)
    if not (1 <= a <= b <= 9999):
        return {}, "From/To range invalid (need 1 ≤ from ≤ to ≤ 9999)"
    out: dict[int, list] = {}
    for n in range(a, b + 1):
        links = []
        for q, tmpl, kind in templates:
            filled = (tmpl.replace("{episode}", str(n)).replace("{EPISODE}", str(n))
                          .replace("{ep}", str(n)).replace("{EP}", str(n)))
            links.append((q, filled, kind))
        out[n] = links
    return out, None
