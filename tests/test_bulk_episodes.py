"""Bulk add episodes on the admin website, plus silent imports."""
from __future__ import annotations

import re

import pytest

from tests.conftest import CHANNEL
from tests.fakes import msg_update
from tests.test_admin_web import web  # noqa: F401
from tests.test_features import _started
from tests.test_public_site import raw
from web import public as P
from web.forms import parse_paste_lines, plan_bulk, expand_quality_range


def _get(d, k, default=""):
    v = d.get(k, default)
    if isinstance(v, list):
        return (v[-1] if v else default) or default
    return v if v is not None else default


def _list(d, k):
    v = d.get(k)
    if v is None:
        return []
    if isinstance(v, list):
        return [x.strip() for x in v if isinstance(x, str) and x.strip()]
    return [v.strip()] if isinstance(v, str) and v.strip() else []


# ---------- parser ----------
def test_parse_paste_pipe_and_labeled_and_header():
    text = """
ep | 480p link | 720p link | 1080p link
# comment
12 | https://a/12-480 | https://a/12-720 | https://a/12-1080
EP 13 | 480p: https://a/13-480 | 720p: https://a/13-720
14, https://a/14-480, https://a/14-720, https://a/14-1080
15 https://a/15-480 https://a/15-720
16 |  | https://a/16-720 |
17 | 1080p: https://a/17-1080 | 720p mirror: https://m/17-720
"""
    eps, issues = parse_paste_lines(text)
    errors = [i for i in issues if i["kind"] == "error"]
    assert not errors
    assert sorted(eps) == [12, 13, 14, 15, 16, 17]
    assert [(q, k) for q, _, k in eps[12]] == [("480p", "part"), ("720p", "part"), ("1080p", "part")]
    assert [q for q, _, _ in eps[13]] == ["480p", "720p"]
    assert [q for q, _, _ in eps[15]] == ["480p", "720p"]
    assert [q for q, _, _ in eps[16]] == ["720p"]
    kinds = {(q, k) for q, _, k in eps[17]}
    assert kinds == {("1080p", "part"), ("720p", "mirror")}


def test_parse_paste_errors_and_merged_duplicates():
    text = """
not-an-ep | https://a/1
12 | https://a/12-480 | https://a/12-720
12 | 1080p: https://a/12-1080
13 | not-a-url
"""
    eps, issues = parse_paste_lines(text)
    kinds = {(i["kind"], "must start" in i["message"], "merged" in i["message"], "valid http" in i["message"] or "not a valid" in i["message"]) for i in issues}
    assert 12 in eps and any(q == "1080p" for q, _, _ in eps[12])
    assert 13 not in eps
    assert any(i["kind"] == "error" and "episode number" in i["message"].lower() for i in issues)
    assert any(i["kind"] == "warn" and "merged" in i["message"] for i in issues)
    assert any(i["kind"] == "error" and "not-a-url" in (i.get("message") + i.get("text", "")) for i in issues)
    assert parse_paste_lines("")[0] == {}
    assert parse_paste_lines("   \n# only comments")[0] == {}


def test_plan_bulk_skip_and_overwrite():
    eps = {1: [("720p", "https://n/1", "part")], 2: [("720p", "https://n/2", "part")], 3: [("720p", "https://n/3", "part")]}
    skip = plan_bulk(eps, {1, 2}, "skip")
    assert list(skip["add"]) == [3] and skip["skip"] == [1, 2] and skip["overwrite"] == []
    over = plan_bulk(eps, {1, 2}, "overwrite")
    assert list(over["add"]) == [1, 2, 3] and over["overwrite"] == [1, 2] and over["skip"] == []


def test_expand_quality_range_still_fills_ep():
    fields = {"ep_from": "5", "ep_to": "6", "720p": "https://x/{ep}-720", "480p_mirror": "https://m/{ep}"}
    eps, err = expand_quality_range(fields, _get, _list)
    assert err is None and list(eps) == [5, 6]
    assert set(eps[5]) == {("720p", "https://x/5-720", "part"), ("480p", "https://m/5", "mirror")}
    assert set(eps[6]) == {("720p", "https://x/6-720", "part"), ("480p", "https://m/6", "mirror")}


# ---------- web admin ----------
def _login_drama(web, title="Old Catalog", n=2):
    web.login_password()
    _, body, _ = web.open("/admin/add")
    csrf = web.csrf_from(body)
    web.open("/admin/add", {
        "csrf": csrf, "title": title, "status": "Completed", "total": str(n),
        "ep_from": "1", "ep_to": str(n), "720p": "https://old/{ep}",
    })
    d = web.db.find_drama(title)
    assert d and [e.number for e in d.episodes] == list(range(1, n + 1))
    web.bot.sent.clear()
    return d


def test_bulk_page_linked_from_drama_and_csrf(web):
    d = _login_drama(web)
    st, body, _ = web.open(f"/admin/drama/{d.id}")
    assert st == 200
    assert f'href="/admin/drama/{d.id}/bulk"' in body
    assert f'href="/admin/drama/{d.id}/bulk?season=' in body
    assert "Add silently" in body and 'name="silent"' in body
    # silent is present on single-ep form but not pre-checked
    addep = body.split('id="addep-form"')[1].split("</form>")[0]
    assert 'name="silent"' in addep and "checked" not in addep.split('name="silent"')[1].split(">")[0]
    st, body, _ = web.open(f"/admin/drama/{d.id}/bulk")
    assert st == 200 and "Bulk add episodes" in body
    assert 'id="bulk-form"' in body and "Range templates" in body and "Paste list" in body
    assert "Silent import" in body
    # default-checked silent
    silent = body.split('name="silent"')[1].split(">")[0]
    assert "checked" in silent
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/bulk", {
        "drama_id": str(d.id), "mode": "range", "ep_from": "3", "ep_to": "4",
        "720p": "https://x/{ep}", "action": "import", "silent": "1",
    })
    assert st == 403 and "CSRF" in body
    st, body, _ = web.open("/admin/drama/bulk", {
        "csrf": csrf, "drama_id": str(d.id), "mode": "range",
        "ep_from": "3", "ep_to": "4", "720p": "https://x/{ep}",
        "action": "preview", "silent": "1", "on_existing": "skip",
        "season": "1",
    })
    assert st == 200 and "Import preview" in body
    assert "EP 3" in body and "EP 4" in body and "new" in body.lower()
    assert 'id="bulk-server-preview"' in body
    assert not re.search(r'id="bulk-server-preview"[^>]*hidden', body)
    assert [e.number for e in web.db.get_drama(d.id).episodes] == [1, 2]  # preview does not write


def test_bulk_range_silent_import_skip_existing(web):
    d = _login_drama(web, "Range Show", n=2)
    _, body, _ = web.open(f"/admin/drama/{d.id}/bulk")
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/bulk", {
        "csrf": csrf, "drama_id": str(d.id), "mode": "range", "season": "1",
        "ep_from": "2", "ep_to": "4",
        "480p": "https://a/{ep}-480", "720p": "https://a/{ep}-720",
        "1080p": "https://a/{ep}-1080", "720p_mirror": "https://m/{ep}",
        "on_existing": "skip", "silent": "1", "action": "import",
    })
    assert st == 200 and "Imported" in body and "skipped" in body.lower()
    d = web.db.get_drama(d.id)
    assert [e.number for e in d.episodes] == [1, 2, 3, 4]
    # ep 2 was skipped (still the original single 720p link)
    ep2 = next(e for e in d.episodes if e.number == 2)
    assert ep2.url == "https://old/2" and ep2.link_count == 1
    ep3 = next(e for e in d.episodes if e.number == 3)
    groups = dict(ep3.quality_groups())
    assert "480p" in groups and "720p" in groups and "1080p" in groups
    assert len(groups["720p"]) == 2  # part + mirror
    # silent: no channel announce / card post
    assert not any("announce" in s or "post_card" in s for s in web.bot.sent)
    assert any(s.get("silent_import") == d.id for s in web.bot.sent)


def test_bulk_paste_overwrite_and_public_site(web):
    d = _login_drama(web, "Paste Show", n=2)
    paste = "\n".join([
        "2 | https://new/2-480 | https://new/2-720 | https://new/2-1080",
        "3 | https://new/3-480 | https://new/3-720 | https://new/3-1080",
    ])
    _, body, _ = web.open(f"/admin/drama/{d.id}/bulk")
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/bulk", {
        "csrf": csrf, "drama_id": str(d.id), "mode": "paste", "season": "1",
        "paste": paste, "on_existing": "overwrite", "silent": "1", "action": "import",
    })
    assert st == 200 and "overwritten" in body.lower()
    d = web.db.get_drama(d.id)
    assert [e.number for e in d.episodes] == [1, 2, 3]
    ep2 = next(e for e in d.episodes if e.number == 2)
    assert "https://new/2-720" in [l.url for l in ep2.links]
    assert "https://old/2" not in [l.url for l in ep2.links]
    # public drama page (catalog cache invalidated by the POST) shows the new episode
    st, _, pub = raw(web, f"/drama/{d.id}")
    assert st == 200 and re.search(r"ep=3|#episodes", pub)
    assert "EP 3" in pub or "ep=3" in pub


def test_silent_add_drama_skips_channel_post(web):
    web.login_password()
    _, body, _ = web.open("/admin/add")
    assert "Create silently" in body
    csrf = web.csrf_from(body)
    web.bot.sent.clear()
    st, body, _ = web.open("/admin/add", {
        "csrf": csrf, "title": "Quiet Drama", "status": "Completed", "total": "2",
        "ep_from": "1", "ep_to": "2", "720p": "https://q/{ep}", "silent": "1",
    })
    assert st == 200 and "not posted" in body.lower()
    d = web.db.find_drama("Quiet Drama")
    assert d and [e.number for e in d.episodes] == [1, 2]
    assert not any("post_card" in s for s in web.bot.sent)
    # still on the public site
    st, _, pub = raw(web, f"/drama/{d.id}")
    assert st == 200 and "Quiet Drama" in pub


def test_silent_single_episode_skips_announce(web):
    d = _login_drama(web, "One By One", n=1)
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    web.bot.sent.clear()
    web.open("/admin/drama/addep", {
        "csrf": csrf, "drama_id": str(d.id), "season": "1", "episode": "2",
        "720p": "https://x/2", "silent": "1",
    })
    assert [e.number for e in web.db.get_drama(d.id).episodes] == [1, 2]
    assert any(s.get("silent_import") == d.id for s in web.bot.sent)
    assert not any("announce" in s for s in web.bot.sent)
    # without silent, it announces
    _, body, _ = web.open(f"/admin/drama/{d.id}")
    csrf = web.csrf_from(body)
    web.bot.sent.clear()
    web.open("/admin/drama/addep", {
        "csrf": csrf, "drama_id": str(d.id), "season": "1", "episode": "3",
        "720p": "https://x/3",
    })
    assert any(s.get("announce") == d.id for s in web.bot.sent)


# ---------- service-level silent flag ----------
@pytest.mark.asyncio
async def test_svc_silent_add_skips_channel_followers_and_keeps_nextep(env):
    d = env.db.add_drama(title="Backfill", status="Completed", total_episodes=16,
                         episodes={1: [("720p", "https://x/1", "part")]})
    env.db.update_drama(d.id, next_ep_date="2026-11-20", air_time="20:00")
    await _started(env, 10)
    env.db.set_follow(10, d.id, True)
    n_msg = len(env.req.of("sendMessage"))
    n_photo = len(env.req.of("sendPhoto"))
    edits = env.req.of("editMessageText") + env.req.of("editMessageCaption") + env.req.of("editMessageMedia")
    n_edit = len(edits)
    await env.svc.add_episodes(d.id, {2: [("720p", "https://x/2", "part")],
                                      3: [("1080p", "https://x/3", "part")]}, silent=True)
    d = env.db.get_drama(d.id)
    assert [e.number for e in d.episodes] == [1, 2, 3]
    assert d.next_ep_date == "2026-11-20" and d.air_time == "20:00"
    assert len(env.req.of("sendMessage")) == n_msg
    assert len(env.req.of("sendPhoto")) == n_photo
    assert len(env.req.of("editMessageText") + env.req.of("editMessageCaption")
               + env.req.of("editMessageMedia")) == n_edit
    # same call without silent still announces
    await env.svc.add_episodes(d.id, {4: [("720p", "https://x/4", "part")]}, silent=False)
    assert any("New episodes" in (p.get("text") or "") and p.get("chat_id") == CHANNEL
               for p in env.req.of("sendMessage"))
    assert any("New for you" in (p.get("text") or "") and p.get("chat_id") == 10
               for p in env.req.of("sendMessage"))
    assert env.db.get_drama(d.id).next_ep_date is None
