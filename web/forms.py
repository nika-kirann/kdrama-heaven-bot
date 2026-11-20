"""HTML fragments for structured quality link forms (add drama + add episode + bulk)."""
from __future__ import annotations

import json
import re

from . import html as H

QUALITIES = ("480p", "720p", "1080p")
_PASTE_LABEL = re.compile(
    r"(?P<q>480p|720p|1080p|hd|4k|2160p|540p)(?P<mirror>[\s_\-]*mirror)?\s*[:.\-]?\s*(?P<url>https?://\S+)",
    re.I,
)
_EP_CELL = re.compile(r"^(?:ep|episode|#)?\s*[:#]?\s*(\d+)$", re.I)
_HEADER_CELLS = {"ep", "episode", "ep#", "#", "num", "number", "480p", "720p", "1080p"}


def next_ep(sea) -> int:
    return max((e.number for e in (sea.episodes if sea else [])), default=0) + 1


def _q_remove_btn() -> str:
    return ('<button type="button" class="btn ghost btn-sm q-remove" '
            'aria-label="Remove this link" title="Remove">×</button>')


def _q_input_row(q: str, name: str, label: str, url: str, *, removable: bool) -> str:
    rm = _q_remove_btn() if removable else ""
    return (
        f'<div class="q-row"><label>{H.e(label)}</label><div class="q-input">'
        f'<input type="text" class="link" name="{H.e(name)}" value="{H.e(url)}" '
        f'placeholder="https://…/{{ep}}.mkv" '
        f'inputmode="url" autocomplete="off" spellcheck="false">'
        f'{rm}</div></div>'
    )


def quality_blocks(prefix: str = "", values: dict | None = None, *,
                   qualities: list[str] | tuple[str, ...] | None = None) -> str:
    """Quality blocks with Part 1 + ＋ Part / ＋ Mirror buttons.
    prefix unused for now (names stay 480p / 480p_mirror so parsers stay shared).
    values: optional {"480p": ["url"], "480p_mirror": ["url"], ...} to prefill."""
    values = values or {}
    blocks = []
    for q in (qualities or QUALITIES):
        parts = [u for u in (values.get(q) or []) if u] or [""]
        part_html = []
        for i, url in enumerate(parts, 1):
            part_html.append(_q_input_row(q, q, f"{q} · Part {i}", url, removable=i > 1))
        mirrors = [u for u in (values.get(f"{q}_mirror") or []) if u]
        mir_html = []
        for i, url in enumerate(mirrors, 1):
            mir_html.append(_q_input_row(q, f"{q}_mirror", f"{q} · Mirror {i}", url, removable=True))
        blocks.append(
            f'<div class="q-block" data-quality="{q}">'
            f'<div class="q-head"><div class="q-title">{H.quality_pill(q)}'
            f'<span class="q-sub">Parts &amp; mirrors</span></div>'
            f'<div class="q-actions">'
            f'<button type="button" class="btn ghost btn-sm add-part" data-q="{q}">＋ Part</button>'
            f'<button type="button" class="btn ghost btn-sm add-mirror" data-q="{q}">＋ Mirror</button>'
            f'</div></div>'
            f'<div class="q-parts">{"".join(part_html)}</div>'
            f'<div class="q-mirrors">{"".join(mir_html)}</div>'
            f'</div>'
        )
    return '<div class="q-grid">' + "".join(blocks) + '</div>'


def silent_checkbox(*, checked: bool = False, name: str = "silent",
                    title: str = "Silent import",
                    hint: str = "Don't post to the channel or group, and don't notify followers. Episodes still appear on the website and in the bot.") -> str:
    """Shared checkbox used on Bulk add, Add episode, and Add drama."""
    chk = " checked" if checked else ""
    return (
        f'<label class="opt-check silent-opt">'
        f'<input type="checkbox" name="{H.e(name)}" value="1"{chk}>'
        f'<span class="opt-ui" aria-hidden="true"></span>'
        f'<span class="opt-copy"><strong>{H.e(title)}</strong>'
        f'<span class="muted">{H.e(hint)}</span></span></label>'
    )


NEW_SEASON_VALUE = "__new__"


def season_picker(d, *, el_id: str, default=None, allow_new: bool = True,
                  counts: bool = False) -> str:
    """Season <select> of existing seasons, optionally with 'Add a new season…'.
    Always visible, including when the drama only has Season 2 (no Season 1)."""
    cur = d.current
    default_sn = str(default if default is not None else (cur.number if cur else 1))
    known = {str(sea.number) for sea in d.seasons}
    is_new = allow_new and default_sn not in known and default_sn.isdigit()
    opts = []
    for sea in d.seasons:
        sel = " selected" if (not is_new and str(sea.number) == default_sn) else ""
        cur_l = " (current)" if cur and sea.number == cur.number else ""
        extra = ""
        if counts:
            n = len(sea.episodes)
            extra = f" · {n} ep{'s' if n != 1 else ''}"
        opts.append(f'<option value="{sea.number}"{sel}>Season {sea.number}{cur_l}{extra}</option>')
    if allow_new:
        opts.append(f'<option value="{NEW_SEASON_VALUE}"{" selected" if is_new or not known else ""}>'
                    "Add a new season…</option>")
    new_val = default_sn if is_new else ""
    hidden = "" if (is_new or (allow_new and not known)) else " hidden"
    new_html = (
        f'<div class="season-new" id="{H.e(el_id)}-new-wrap"{hidden}>'
        f'<label for="{H.e(el_id)}-new">New season number</label>'
        f'<input name="new_season" id="{H.e(el_id)}-new" value="{H.e(new_val)}" '
        f'inputmode="numeric" min="1" max="99" placeholder="e.g. 2"></div>'
    ) if allow_new else ""
    return (
        f'<div class="season-picker"><label for="{H.e(el_id)}">Season</label>'
        f'<select name="season" id="{H.e(el_id)}">{"".join(opts)}</select>'
        f'{new_html}</div>'
    )


def parse_form_season(fields, field_get, d, *, allow_new: bool = False) -> tuple[int | None, str | None]:
    """Read season / new_season fields. Returns (number, error)."""
    from utils import parse_season_number
    raw = field_get(fields, "season")
    if raw == NEW_SEASON_VALUE:
        raw = field_get(fields, "new_season")
        if not raw.strip():
            return None, "Enter a season number"
        try:
            n = parse_season_number(raw)
        except ValueError as e:
            return None, str(e)
        if d.season(n) is None and not allow_new:
            return None, "Invalid season"
        return n, None
    if raw.strip():
        try:
            n = parse_season_number(raw)
        except ValueError as e:
            return None, str(e)
        if d.season(n) is None and not allow_new:
            return None, "Invalid season"
        return n, None
    return (d.current.number if d.current else 1), None


def add_episode_form(d, csrf: str, *, err: str = "") -> str:
    """Episode # + 480p/720p/1080p URL fields with Part / Mirror add buttons."""
    cur = d.current
    next_map = {str(sea.number): next_ep(sea) for sea in d.seasons}
    default_sn = cur.number if cur else 1
    default_ep = next_map.get(str(default_sn), 1)
    season_html = season_picker(d, el_id="addep-season", default=default_sn, allow_new=True)
    err_html = (
        f'<div class="flash err inline" id="addep-err">{H.e(err)}</div>'
        if err else
        '<div class="flash err inline" id="addep-err" hidden></div>'
    )
    return (
        '<div class="card" id="add-episode">'
        f'<div class="card-head"><div class="card-ic">{H.icon("plus-circle")}</div><div>'
        '<h2>Add episode</h2>'
        '<p class="muted">Fill any qualities you have — empty ones are skipped. '
        'Use ＋ Part / ＋ Mirror for extra URLs. '
        f'<a href="/admin/drama/{d.id}/bulk">Bulk add episodes</a> for a range or a pasted list.</p></div></div>'
        f'{err_html}'
        f'<form method="post" action="/admin/drama/addep" id="addep-form" '
        f"data-next='{H.e(json.dumps(next_map))}'>"
        f'{csrf}'
        f'<input type="hidden" name="drama_id" value="{d.id}">'
        '<div class="row narrow">'
        f'{season_html}'
        '<div><label>Episode number</label>'
        f'<input name="episode" id="addep-ep" value="{default_ep}" '
        'inputmode="numeric" required min="1" max="9999"></div>'
        '</div>'
        f'{quality_blocks()}'
        f'{silent_checkbox(checked=False, title="Add silently", hint="Don\'t post to the channel or group, and don\'t notify followers. The episode still appears on the website and in the bot.")}'
        '<div class="form-foot">'
        f'<a class="btn secondary" href="/admin/drama/{d.id}/bulk">{H.icon("layers")}Bulk add episodes</a>'
        f'<button class="btn" type="submit">{H.icon("plus")}Add episode</button>'
        '</div></form></div>'
    )


def add_drama_links_section(*, err: str = "") -> str:
    """From/To range + quality URL templates ({{ep}} expands) for the Add drama page."""
    err_html = (
        f'<div class="flash err inline" id="add-links-err">{H.e(err)}</div>'
        if err else
        '<div class="flash err inline" id="add-links-err" hidden></div>'
    )
    return (
        '<div class="ep-box" id="add-links">'
        '<p class="muted hint">Leave empty to create the drama with no episodes yet. '
        'Paste your links and put <code>{ep}</code> where the episode number goes. '
        'It will be replaced for every episode from → to when you create the drama.</p>'
        '<p class="ep-preview" id="ep-expand-preview" style="color:var(--gold)"></p>'
        f'{err_html}'
        '<div class="row narrow">'
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


def _split_paste_row(line: str) -> list[str]:
    if "|" in line:
        return [c.strip() for c in line.split("|")]
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    parts = [c.strip() for c in line.split(",")]
    if len(parts) >= 2:
        head = _EP_CELL.fullmatch(parts[0])
        if head and any((not p) or "://" in p or _PASTE_LABEL.match(p) for p in parts[1:]):
            return parts
    toks = line.split()
    if len(toks) >= 2 and _EP_CELL.fullmatch(toks[0]) and any(
            t.lower().startswith("http://") or t.lower().startswith("https://") or _PASTE_LABEL.match(t)
            for t in toks[1:]):
        return [toks[0]] + toks[1:]
    return [line.strip()]


def _parse_link_cell(cell: str, default_q: str | None) -> list[tuple[str, str, str]]:
    """One paste cell → list of (quality, url, kind). Empty cell → []."""
    cell = (cell or "").strip()
    if not cell:
        return []
    out: list[tuple[str, str, str]] = []

    def _norm_q(raw: str) -> str:
        ql = raw.lower()
        if ql == "hd":
            return "HD"
        if ql in {"4k", "2160p"}:
            return "4K"
        return ql if ql in QUALITIES else ql

    leftover = cell
    for m in _PASTE_LABEL.finditer(cell):
        out.append((_norm_q(m.group("q")), m.group("url"), "mirror" if m.group("mirror") else "part"))
        leftover = leftover[:m.start()] + " " * (m.end() - m.start()) + leftover[m.end():]
    for tok in re.split(r"[,\s]+", leftover):
        if not tok:
            continue
        if not default_q:
            raise ValueError("this column needs a quality (480p/720p/1080p) or a labeled link")
        if not tok.lower().startswith(("http://", "https://")):
            raise ValueError(f"not a valid http(s) link: {tok[:60]}")
        out.append((default_q, tok, "part"))
    return out


def parse_paste_lines(text: str) -> tuple[dict, list[dict]]:
    """Parse a pasted list into {ep: [(quality, url, kind), ...]} plus issue dicts.

    Accepted (one episode per line; blank lines and # comments are ignored):
      12 | https://a/480 | https://a/720 | https://a/1080
      EP 12 | 480p: https://a/480 | 720p: https://a/720
      12, https://a/480, https://a/720, https://a/1080
      12 https://a/480 https://a/720
    Bare URL columns after the episode number map to 480p, 720p, 1080p in order.
    Empty columns skip that quality. Duplicate episode numbers in the paste are merged.
    """
    episodes: dict[int, list] = {}
    issues: list[dict] = []
    if not (text or "").strip():
        return {}, [{"line": 0, "text": "", "kind": "error",
                     "message": "Paste one episode per line, or use the range tab"}]
    lines = text.splitlines()
    if len(lines) > 2000:
        return {}, [{"line": 0, "text": "", "kind": "error",
                     "message": "Paste is too long (max 2000 lines)"}]
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cells = _split_paste_row(line)
        if not cells:
            continue
        # header row: "ep | 480p | 720p | 1080p"
        head = cells[0].strip().lower().rstrip(":#")
        if head in _HEADER_CELLS and not any("://" in c for c in cells):
            continue
        ep = None
        m = _EP_CELL.fullmatch(cells[0])
        if m:
            ep = int(m.group(1))
            rest = cells[1:]
        else:
            issues.append({"line": i, "text": line, "kind": "error",
                           "message": "Line must start with an episode number"})
            continue
        if not (1 <= ep <= 9999):
            issues.append({"line": i, "text": line, "kind": "error",
                           "message": "Episode number must be 1–9999"})
            continue
        links: list[tuple[str, str, str]] = []
        try:
            if not rest:
                raise ValueError("no links on this line")
            for idx, cell in enumerate(rest):
                default_q = QUALITIES[idx] if idx < len(QUALITIES) else QUALITIES[-1]
                links.extend(_parse_link_cell(cell, default_q))
        except ValueError as e:
            issues.append({"line": i, "text": line, "kind": "error", "message": str(e)})
            continue
        if not links:
            issues.append({"line": i, "text": line, "kind": "error",
                           "message": "No valid http(s) links on this line"})
            continue
        if ep in episodes:
            episodes[ep].extend(links)
            issues.append({"line": i, "text": line, "kind": "warn",
                           "message": f"EP {ep} appears more than once — links were merged"})
        else:
            episodes[ep] = links
    if not episodes and not issues:
        issues.append({"line": 0, "text": "", "kind": "error",
                       "message": "No valid episodes in the paste box"})
    return episodes, issues


def plan_bulk(episodes: dict, existing: set[int], on_existing: str = "skip") -> dict:
    """Split a parsed episode map into add / skip / overwrite buckets."""
    mode = "overwrite" if on_existing == "overwrite" else "skip"
    add, skip, overwrite = {}, [], []
    for n in sorted(episodes):
        links = episodes[n]
        if n in existing:
            if mode == "overwrite":
                add[n] = links
                overwrite.append(n)
            else:
                skip.append(n)
        else:
            add[n] = links
    return {"add": add, "skip": skip, "overwrite": overwrite, "on_existing": mode}


def _link_summary(links: list) -> str:
    quals, n = [], 0
    for q, _, _ in links:
        n += 1
        if q not in quals:
            quals.append(q)
    return f"{', '.join(quals)} · {n} link{'s' if n != 1 else ''}"


def _first_url(links: list) -> str:
    return links[0][1] if links else ""


def preview_table_html(plan: dict, *, max_rows: int = 50) -> str:
    """Server-side preview table used after Preview import (and as a fallback)."""
    issues = plan.get("issues") or []
    errors = [x for x in issues if x.get("kind") == "error"]
    warns = [x for x in issues if x.get("kind") == "warn"]
    add, skip, overwrite = plan.get("add") or {}, plan.get("skip") or [], plan.get("overwrite") or []
    # Build rows: overwrites, new, then skips, in episode order within each group? Better: all by ep number.
    rows_data = []
    for n, links in add.items():
        status = "overwrite" if n in overwrite else "new"
        rows_data.append((n, links, status))
    for n in skip:
        rows_data.append((n, None, "skip"))
    rows_data.sort(key=lambda r: r[0])
    total = len(rows_data)
    if total > max_rows:
        head, tail = rows_data[: max_rows - 8], rows_data[-8:]
        shown = head + [(None, None, "ellipsis")] + tail
        hidden = total - len(head) - len(tail)
    else:
        shown, hidden = rows_data, 0

    body = []
    for n, links, status in shown:
        if status == "ellipsis":
            body.append(f'<tr class="preview-more"><td colspan="3">{hidden} more episodes not shown here — they will still be imported.</td></tr>')
            continue
        if status == "new":
            badge = '<span class="pill ok">new</span>'
        elif status == "overwrite":
            badge = '<span class="pill warn">exists — will overwrite</span>'
        else:
            badge = '<span class="pill neutral">exists — will skip</span>'
        summary = _link_summary(links) if links else "already in the database"
        sample = H.e(_first_url(links)) if links else ""
        sample_html = f'<div class="preview-url" title="{sample}">{sample}</div>' if sample else ""
        body.append(
            f'<tr class="st-{status}"><td><span class="ep-n">EP {n}</span></td>'
            f'<td>{H.e(summary)}{sample_html}</td><td>{badge}</td></tr>'
        )
    issue_html = ""
    if errors or warns:
        items = "".join(
            f'<li class="{H.e(x["kind"])}">Line {x["line"]}: {H.e(x["message"])}'
            + (f' <code>{H.e(x.get("text", "")[:80])}</code>' if x.get("text") else "")
            + "</li>"
            for x in (errors + warns)
        )
        issue_html = f'<ul class="preview-issues">{items}</ul>'
    stats = []
    stats.append(f'<span class="pill ok">{len(add) - len(overwrite)} new</span>' if (len(add) - len(overwrite)) else "")
    if overwrite:
        stats.append(f'<span class="pill warn">{len(overwrite)} overwrite</span>')
    if skip:
        stats.append(f'<span class="pill neutral">{len(skip)} skipped</span>')
    if errors:
        stats.append(f'<span class="pill err">{len(errors)} line error{"s" if len(errors) != 1 else ""}</span>')
    table = (
        '<div class="table-wrap"><table class="table compact preview-table">'
        "<thead><tr><th>Ep</th><th>Links</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(body) or '<tr><td colspan=\"3\" class=\"muted\">Nothing to import.</td></tr>'}</tbody>"
        "</table></div>"
    )
    return (
        f'<div class="bulk-preview" id="bulk-server-preview">'
        f'<div class="preview-head"><h3>Import preview</h3>'
        f'<div class="pills">{"".join(stats)}</div></div>'
        f'{issue_html}{table}</div>'
    )


def _quality_values(field_list, fields) -> dict:
    out = {}
    for q in QUALITIES:
        out[q] = field_list(fields, q)
        out[f"{q}_mirror"] = field_list(fields, f"{q}_mirror")
    return out


def bulk_add_form(d, csrf: str, *, err: str = "", values: dict | None = None,
                  plan: dict | None = None, field_list=None) -> str:
    """Full Bulk add episodes form for an existing drama."""
    values = values or {}
    cur = d.current
    default_sn = str(values.get("season") or (cur.number if cur else 1))
    existing_map = {str(sea.number): [e.number for e in sea.episodes] for sea in d.seasons}
    season_html = season_picker(d, el_id="bulk-season", default=default_sn, allow_new=True, counts=True)
    mode = (values.get("mode") or "range").strip().lower()
    if mode not in {"range", "paste"}:
        mode = "range"
    on_ex = (values.get("on_existing") or "skip").strip().lower()
    if on_ex not in {"skip", "overwrite"}:
        on_ex = "skip"
    silent_on = values.get("silent", True)
    if isinstance(silent_on, str):
        silent_on = silent_on.strip().lower() in {"1", "on", "true", "yes", ""}
    qvals = values.get("quality_values") or {}
    if field_list and not qvals:
        qvals = _quality_values(field_list, values)
    err_html = (
        f'<div class="flash err inline" id="bulk-err">{H.e(err)}</div>'
        if err else
        '<div class="flash err inline" id="bulk-err" hidden></div>'
    )
    preview_html = preview_table_html(plan) if plan else '<div class="bulk-preview live" id="bulk-live-preview" hidden></div>'
    if plan:
        preview_html += '<div class="bulk-preview live" id="bulk-live-preview" hidden></div>'
    ep_from = H.e(values.get("ep_from") or "")
    ep_to = H.e(values.get("ep_to") or "")
    paste = values.get("paste") or ""
    skip_chk = " checked" if on_ex == "skip" else ""
    over_chk = " checked" if on_ex == "overwrite" else ""
    return (
        f'<form method="post" action="/admin/drama/bulk" id="bulk-form" class="bulk-form" '
        f"data-existing='{H.e(json.dumps(existing_map))}'>"
        f'{csrf}'
        f'<input type="hidden" name="drama_id" value="{d.id}">'
        f'<input type="hidden" name="mode" id="bulk-mode" value="{H.e(mode)}">'
        f'{err_html}'
        '<div class="row narrow">'
        f'{season_html}'
        '</div>'
        '<div class="tabs mode-tabs" role="tablist">'
        f'<button type="button" class="{"active" if mode=="range" else ""}" data-bulk-tab="range" role="tab">Range templates</button>'
        f'<button type="button" class="{"active" if mode=="paste" else ""}" data-bulk-tab="paste" role="tab">Paste list</button>'
        '</div>'
        f'<div id="bulk-range" class="bulk-pane" {"hidden" if mode!="range" else ""}>'
        '<p class="muted hint">Put <code>{ep}</code> where the episode number goes. '
        'It is filled in for every episode from → to, including extra parts and mirrors.</p>'
        '<p class="ep-preview" id="bulk-range-hint" style="color:var(--gold)"></p>'
        '<div class="row narrow">'
        '<div><label>From episode</label>'
        f'<input name="ep_from" id="bulk-from" value="{ep_from}" inputmode="numeric" min="1" placeholder="1"></div>'
        '<div><label>To episode</label>'
        f'<input name="ep_to" id="bulk-to" value="{ep_to}" inputmode="numeric" min="1" placeholder="16"></div>'
        '</div>'
        f'{quality_blocks(values=qvals)}'
        '</div>'
        f'<div id="bulk-paste" class="bulk-pane" {"hidden" if mode!="paste" else ""}>'
        '<p class="muted hint">One episode per line. Columns are episode, then 480p, 720p, 1080p. '
        'Empty columns are skipped. You can also label a cell, e.g. <code>720p: https://…</code>.</p>'
        f'<label for="bulk-paste-box">Episode list</label>'
        f'<textarea name="paste" id="bulk-paste-box" rows="12" spellcheck="false" '
        f'placeholder="12 | https://cdn.example/12-480.mkv | https://cdn.example/12-720.mkv | https://cdn.example/12-1080.mkv">{H.e(paste)}</textarea>'
        '<p class="muted sm format-ex">Example: <code>ep | 480p link | 720p link | 1080p link</code></p>'
        '</div>'
        '<div class="opt-grid">'
        '<div class="opt-card">'
        '<div class="fs-title">If an episode already exists</div>'
        f'<label class="opt-check"><input type="radio" name="on_existing" value="skip"{skip_chk}>'
        '<span class="opt-ui"></span><span class="opt-copy"><strong>Skip existing</strong>'
        '<span class="muted">Leave the current links as they are.</span></span></label>'
        f'<label class="opt-check"><input type="radio" name="on_existing" value="overwrite"{over_chk}>'
        '<span class="opt-ui"></span><span class="opt-copy"><strong>Overwrite</strong>'
        '<span class="muted">Replace the qualities you are importing on that episode.</span></span></label>'
        '</div>'
        '<div class="opt-card">'
        '<div class="fs-title">Channel &amp; followers</div>'
        f'{silent_checkbox(checked=bool(silent_on))}'
        '</div></div>'
        f'{preview_html}'
        '<div class="form-foot">'
        f'<button class="btn secondary" type="submit" name="action" value="preview">{H.icon("search")}Preview import</button>'
        f'<button class="btn" type="submit" name="action" value="import" id="bulk-import-btn">{H.icon("plus")}Import episodes</button>'
        '</div></form>'
    )


def link_values_from_episode(ep) -> tuple[dict, list[str]]:
    """Prefill dict for quality_blocks, plus any qualities beyond the standard 480/720/1080."""
    values: dict = {}
    extras: list[str] = []
    for q, ls in ep.quality_groups():
        parts = [l.url for l in ls if (l.kind or "part") != "mirror"]
        mirrors = [l.url for l in ls if l.kind == "mirror"]
        values[q] = parts
        values[f"{q}_mirror"] = mirrors
        if q not in QUALITIES and q not in extras:
            extras.append(q)
    return values, extras


def episode_link_tuples(ep) -> list[tuple[str, str, str]]:
    """[(quality, url, kind), ...] in display order, including a legacy HD row."""
    out: list[tuple[str, str, str]] = []
    for q, ls in ep.quality_groups():
        for l in ls:
            out.append((l.quality, l.url, l.kind or "part"))
    return out


def collect_form_links(field_list, fields, qualities) -> tuple[list, str | None]:
    """Parse 480p / 480p_mirror (etc.) fields into [(quality, url, kind), ...]."""
    links: list[tuple[str, str, str]] = []
    for q in qualities:
        for url in field_list(fields, q):
            if not url.lower().startswith(("http://", "https://")):
                return [], f"Invalid {q} URL (need http/https)"
            links.append((q, url, "part"))
        for url in field_list(fields, f"{q}_mirror"):
            if not url.lower().startswith(("http://", "https://")):
                return [], f"Invalid {q} mirror URL"
            links.append((q, url, "mirror"))
    return links, None


def edit_episode_form(d, ep, csrf: str, *, err: str = "", values: dict | None = None) -> str:
    """Prefill the same quality form as Add episode, for editing one existing episode."""
    values = dict(values or {})
    qvals = values.get("quality_values")
    extras = values.get("extra_qualities") or []
    if qvals is None:
        qvals, extras = link_values_from_episode(ep)
    quals = list(QUALITIES) + [q for q in extras if q not in QUALITIES]
    sea_n = ep.season.number if ep.season is not None else 1
    ep_n = values.get("episode") or str(ep.number)
    err_html = (
        f'<div class="flash err inline" id="editep-err">{H.e(err)}</div>'
        if err else
        '<div class="flash err inline" id="editep-err" hidden></div>'
    )
    season_label = f"Season {sea_n}" if (d.is_multi or sea_n != 1) else "Season 1"
    return (
        f'<form method="post" action="/admin/drama/editep" id="editep-form">'
        f'{csrf}'
        f'<input type="hidden" name="drama_id" value="{d.id}">'
        f'<input type="hidden" name="episode_id" value="{ep.id}">'
        f'<input type="hidden" name="qualities" value="{H.e(",".join(quals))}">'
        f'{err_html}'
        '<div class="row narrow">'
        f'<div><label>Season</label><input value="{H.e(season_label)}" disabled>'
        f'<input type="hidden" name="season" value="{sea_n}"></div>'
        '<div><label>Episode number</label>'
        f'<input name="episode" id="editep-ep" value="{H.e(str(ep_n))}" '
        'inputmode="numeric" required min="1" max="9999"></div>'
        '</div>'
        f'{quality_blocks(values=qvals, qualities=quals)}'
        '<p class="muted silent-note">Saving only updates the database. Nothing is posted to the channel or group, '
        "and followers are not notified. Public /go links keep the same id when a URL is changed.</p>"
        '<div class="form-foot">'
        f'<a class="btn secondary" href="/admin/drama/{d.id}#season-{sea_n}">{H.icon("arrow-left")}Cancel</a>'
        f'<button class="btn" type="submit">{H.icon("save")}Save links</button>'
        '</div></form>'
    )


def _group_links(links: list) -> dict[str, list]:
    out: dict[str, list] = {}
    for q, u, k in (links or []):
        out.setdefault(q, []).append((q, u, k or "part"))
    return out


def plan_bulk_update(incoming: dict, existing: dict[int, list], *,
                     clear_empty: bool = False,
                     standard: tuple[str, ...] | list[str] = QUALITIES) -> dict:
    """Plan link updates for existing episodes only.

    Blank qualities stay as they are unless clear_empty is set (then standard
    qualities missing from the incoming row are cleared). Episodes that are not
    already in the database are reported as missing and never created.
    """
    update, missing, unchanged = {}, [], []
    diffs: dict[int, dict] = {}
    for n in sorted(incoming):
        if n not in existing:
            missing.append(n)
            continue
        cur = list(existing[n] or [])
        cur_g = _group_links(cur)
        new_g = _group_links(incoming[n])
        quals: list[str] = list(standard)
        for q in list(cur_g) + list(new_g):
            if q not in quals:
                quals.append(q)
        final: list = []
        changed_qs: list[str] = []
        for q in quals:
            if q in new_g:
                nxt = new_g[q]
            elif clear_empty and q in standard:
                nxt = []
            else:
                nxt = cur_g.get(q, [])
            if nxt != cur_g.get(q, []):
                changed_qs.append(q)
            final.extend(nxt)
        if not changed_qs:
            unchanged.append(n)
        else:
            update[n] = final
            diffs[n] = {"old": cur, "new": final, "changed": changed_qs}
    return {
        "update": update, "missing": missing, "unchanged": unchanged,
        "diffs": diffs, "clear_empty": clear_empty, "incoming": incoming,
    }


def _diff_quality_html(old_links: list, new_links: list, changed: list[str]) -> str:
    """Per-quality old → new rows for qualities that actually change."""
    old_g, new_g = _group_links(old_links), _group_links(new_links)
    blocks = []
    for q in changed:
        olds = [H.e(u) for _, u, _ in old_g.get(q, [])]
        news = [H.e(u) for _, u, _ in new_g.get(q, [])]
        if not olds and not news:
            continue
        old_html = "<br>".join(f'<span class="diff-old" title="{u}">{u}</span>' for u in olds) or (
            '<span class="diff-old muted">—</span>')
        if news:
            new_html = "<br>".join(f'<span class="diff-new" title="{u}">{u}</span>' for u in news)
        else:
            new_html = '<span class="diff-removed">removed</span>'
        blocks.append(
            f'<div class="diff-q">{H.quality_pill(q)}'
            f'<div class="diff-urls">{old_html}<span class="diff-arrow">→</span>{new_html}</div></div>'
        )
    return '<div class="link-diff">' + "".join(blocks) + "</div>" if blocks else ""


def preview_update_table_html(plan: dict, *, max_rows: int = 50) -> str:
    """Server-side preview of a bulk link update (old → new per episode)."""
    issues = plan.get("issues") or []
    errors = [x for x in issues if x.get("kind") == "error"]
    warns = [x for x in issues if x.get("kind") == "warn"]
    update = plan.get("update") or {}
    missing = plan.get("missing") or []
    unchanged = plan.get("unchanged") or []
    diffs = plan.get("diffs") or {}
    incoming = plan.get("incoming") or {}
    rows_data = []
    for n, links in update.items():
        rows_data.append((n, "update", diffs.get(n) or {"old": [], "new": links, "changed": []}))
    for n in unchanged:
        rows_data.append((n, "unchanged", None))
    for n in missing:
        rows_data.append((n, "missing", incoming.get(n)))
    rows_data.sort(key=lambda r: r[0])
    total = len(rows_data)
    if total > max_rows:
        head, tail = rows_data[: max_rows - 8], rows_data[-8:]
        shown = head + [(None, "ellipsis", None)] + tail
        hidden = total - len(head) - len(tail)
    else:
        shown, hidden = rows_data, 0

    body = []
    for n, status, payload in shown:
        if status == "ellipsis":
            body.append(
                f'<tr class="preview-more"><td colspan="3">{hidden} more episodes not shown here '
                "— they will still be updated.</td></tr>"
            )
            continue
        if status == "update":
            badge = '<span class="pill ok">will update</span>'
            cell = _diff_quality_html(payload.get("old") or [], payload.get("new") or [],
                                      payload.get("changed") or [])
        elif status == "unchanged":
            badge = '<span class="pill neutral">no change</span>'
            cell = '<span class="muted">Links already match</span>'
        else:
            badge = '<span class="pill neutral">not in the database — skipped</span>'
            cell = '<span class="muted">This episode is not in the season, so it will not be added.</span>'
        body.append(
            f'<tr class="st-{status}"><td><span class="ep-n">EP {n}</span></td>'
            f'<td>{cell}</td><td>{badge}</td></tr>'
        )
    issue_html = ""
    if errors or warns:
        items = "".join(
            f'<li class="{H.e(x["kind"])}">Line {x["line"]}: {H.e(x["message"])}'
            + (f' <code>{H.e(x.get("text", "")[:80])}</code>' if x.get("text") else "")
            + "</li>"
            for x in (errors + warns)
        )
        issue_html = f'<ul class="preview-issues">{items}</ul>'
    stats = []
    if update:
        stats.append(f'<span class="pill ok">{len(update)} will update</span>')
    if unchanged:
        stats.append(f'<span class="pill neutral">{len(unchanged)} no change</span>')
    if missing:
        stats.append(f'<span class="pill warn">{len(missing)} not in database</span>')
    if errors:
        stats.append(f'<span class="pill err">{len(errors)} line error{"s" if len(errors) != 1 else ""}</span>')
    table = (
        '<div class="table-wrap"><table class="table compact preview-table">'
        "<thead><tr><th>Ep</th><th>Current → new</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(body) or '<tr><td colspan=\"3\" class=\"muted\">Nothing to update.</td></tr>'}</tbody>"
        "</table></div>"
    )
    return (
        f'<div class="bulk-preview" id="bulk-server-preview">'
        f'<div class="preview-head"><h3>Update preview</h3>'
        f'<div class="pills">{"".join(stats)}</div></div>'
        f'{issue_html}{table}</div>'
    )


def existing_links_payload(d) -> dict:
    """Season-number -> episode-number -> [(quality, url, kind), ...] for live preview JS."""
    out: dict[str, dict[str, list]] = {}
    for sea in d.seasons:
        out[str(sea.number)] = {
            str(e.number): [[q, u, k] for q, u, k in episode_link_tuples(e)]
            for e in sea.episodes
        }
    return out


def bulk_edit_form(d, csrf: str, *, err: str = "", values: dict | None = None,
                   plan: dict | None = None, field_list=None) -> str:
    """Bulk replace links on episodes that already exist."""
    values = values or {}
    cur = d.current
    default_sn = str(values.get("season") or (cur.number if cur else 1))
    season_html = season_picker(d, el_id="bulk-links-season", default=default_sn,
                               allow_new=False, counts=True)
    mode = (values.get("mode") or "range").strip().lower()
    if mode not in {"range", "paste"}:
        mode = "range"
    clear_on = values.get("clear_empty", False)
    if isinstance(clear_on, str):
        clear_on = clear_on.strip().lower() in {"1", "on", "true", "yes"}
    qvals = values.get("quality_values") or {}
    if field_list and not qvals:
        qvals = _quality_values(field_list, values)
    err_html = (
        f'<div class="flash err inline" id="bulk-links-err">{H.e(err)}</div>'
        if err else
        '<div class="flash err inline" id="bulk-links-err" hidden></div>'
    )
    preview_html = preview_update_table_html(plan) if plan else (
        '<div class="bulk-preview live" id="bulk-links-live-preview" hidden></div>'
    )
    if plan:
        preview_html += '<div class="bulk-preview live" id="bulk-links-live-preview" hidden></div>'
    ep_from = H.e(values.get("ep_from") or "")
    ep_to = H.e(values.get("ep_to") or "")
    paste = values.get("paste") or ""
    clear_chk = " checked" if clear_on else ""
    payload = json.dumps(existing_links_payload(d))
    return (
        f'<form method="post" action="/admin/drama/links" id="bulk-links-form" class="bulk-form" '
        f"data-existing-links='{H.e(payload)}'>"
        f'{csrf}'
        f'<input type="hidden" name="drama_id" value="{d.id}">'
        f'<input type="hidden" name="mode" id="bulk-links-mode" value="{H.e(mode)}">'
        f'{err_html}'
        '<div class="row narrow">'
        f'{season_html}'
        '</div>'
        '<div class="tabs mode-tabs" role="tablist">'
        f'<button type="button" class="{"active" if mode=="range" else ""}" data-bulk-tab="range" role="tab">Range templates</button>'
        f'<button type="button" class="{"active" if mode=="paste" else ""}" data-bulk-tab="paste" role="tab">Paste list</button>'
        '</div>'
        f'<div id="bulk-links-range" class="bulk-pane" {"hidden" if mode!="range" else ""}>'
        '<p class="muted hint">Put <code>{ep}</code> where the episode number goes. '
        "Only episodes that already exist in this season are updated. "
        "Leave a quality blank to keep its current links.</p>"
        '<p class="ep-preview" id="bulk-links-range-hint" style="color:var(--gold)"></p>'
        '<div class="row narrow">'
        '<div><label>From episode</label>'
        f'<input name="ep_from" id="bulk-links-from" value="{ep_from}" inputmode="numeric" min="1" placeholder="1"></div>'
        '<div><label>To episode</label>'
        f'<input name="ep_to" id="bulk-links-to" value="{ep_to}" inputmode="numeric" min="1" placeholder="16"></div>'
        '</div>'
        f'{quality_blocks(values=qvals)}'
        '</div>'
        f'<div id="bulk-links-paste" class="bulk-pane" {"hidden" if mode!="paste" else ""}>'
        '<p class="muted hint">One episode per line. Columns are episode, then 480p, 720p, 1080p. '
        "Empty columns leave that quality as it is (unless you tick Clear empty qualities). "
        "Episodes that are not already in the database are skipped.</p>"
        '<label for="bulk-links-paste-box">Episode list</label>'
        f'<textarea name="paste" id="bulk-links-paste-box" rows="12" spellcheck="false" '
        f'placeholder="12 | https://cdn.example/12-480.mkv | https://cdn.example/12-720.mkv | https://cdn.example/12-1080.mkv">{H.e(paste)}</textarea>'
        '<p class="muted sm format-ex">Example: <code>ep | 480p link | 720p link | 1080p link</code></p>'
        '</div>'
        '<div class="opt-grid">'
        '<div class="opt-card">'
        '<div class="fs-title">Empty qualities</div>'
        f'<label class="opt-check"><input type="checkbox" name="clear_empty" value="1"{clear_chk}>'
        '<span class="opt-ui" aria-hidden="true"></span>'
        '<span class="opt-copy"><strong>Clear empty qualities</strong>'
        "<span class=\"muted\">If a quality is left blank (or an empty paste column), remove that quality from the episode.</span></span></label>"
        '</div>'
        '<div class="opt-card">'
        '<div class="fs-title">Channel &amp; followers</div>'
        '<p class="muted silent-note">Updates are always silent: no channel or group post, no follower DMs, '
        "and the next-episode date is left as it is.</p>"
        '</div></div>'
        f'{preview_html}'
        '<div class="form-foot">'
        f'<button class="btn secondary" type="submit" name="action" value="preview">{H.icon("search")}Preview update</button>'
        f'<button class="btn" type="submit" name="action" value="apply" id="bulk-links-apply-btn">{H.icon("save")}Update links</button>'
        '</div></form>'
    )
