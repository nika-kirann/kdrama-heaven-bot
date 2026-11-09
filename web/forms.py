"""HTML fragments for the structured Add-episode form."""
from __future__ import annotations

import json

from . import html as H


def next_ep(sea) -> int:
    return max((e.number for e in (sea.episodes if sea else [])), default=0) + 1


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
    q_blocks = []
    for q in ("480p", "720p", "1080p"):
        q_blocks.append(
            f'<div class="q-block" data-quality="{q}">'
            f'<div class="q-title">{q}</div>'
            f'<div class="q-parts">'
            f'<label>{q} · Part 1</label>'
            f'<input type="url" name="{q}" placeholder="https://…" inputmode="url" autocomplete="off">'
            f'</div>'
            f'<div class="q-mirrors"></div>'
            f'<div class="q-actions">'
            f'<button type="button" class="btn secondary btn-sm add-part" data-q="{q}">＋ Part</button>'
            f'<button type="button" class="btn secondary btn-sm add-mirror" data-q="{q}">＋ Mirror</button>'
            f'</div></div>'
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
        f'{"".join(q_blocks)}'
        '<div class="actions" style="margin-top:14px">'
        '<button class="btn" type="submit">Add episode</button>'
        '</div></form></div>'
    )
