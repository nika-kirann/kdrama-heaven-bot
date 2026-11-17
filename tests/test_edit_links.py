"""Edit and bulk-update links on already-uploaded episodes (admin website)."""
from __future__ import annotations

import re

from tests.test_admin_web import web  # noqa: F401
from tests.test_public_site import raw
from web.forms import plan_bulk_update


def _login_drama(web, title="Old Catalog", n=3, next_ep="2026-12-01"):
    web.login_password()
    _, body, _ = web.open("/admin/add")
    csrf = web.csrf_from(body)
    web.open("/admin/add", {
        "csrf": csrf, "title": title, "status": "Completed", "total": str(n),
        "ep_from": "1", "ep_to": str(n),
        "480p": "https://old/{ep}-480",
        "720p": "https://old/{ep}-720",
        "1080p": "https://old/{ep}-1080",
        "nextep": next_ep, "air_time": "20:00",
    })
    d = web.db.find_drama(title)
    assert d and [e.number for e in d.episodes] == list(range(1, n + 1))
    if next_ep:
        web.db.update_drama(d.id, next_ep_date=next_ep, air_time="20:00")
        d = web.db.get_drama(d.id)
    web.bot.sent.clear()
    return d


# ---------- planner ----------
def test_plan_bulk_update_only_existing_and_blank_unchanged():
    existing = {
        1: [("480p", "https://old/1-480", "part"), ("720p", "https://old/1-720", "part")],
        2: [("720p", "https://old/2-720", "part")],
    }
    incoming = {
        1: [("720p", "https://new/1-720", "part")],
        2: [("720p", "https://old/2-720", "part")],
        3: [("720p", "https://new/3-720", "part")],
    }
    plan = plan_bulk_update(incoming, existing)
    assert list(plan["update"]) == [1]
    assert plan["update"][1] == [
        ("480p", "https://old/1-480", "part"),
        ("720p", "https://new/1-720", "part"),
    ]
    assert plan["unchanged"] == [2]
    assert plan["missing"] == [3]
    assert plan["diffs"][1]["changed"] == ["720p"]

    cleared = plan_bulk_update(incoming, existing, clear_empty=True)
    assert 1 in cleared["update"]
    # 480p was blank in incoming, so it is cleared; 1080p was also absent
    assert [q for q, _, _ in cleared["update"][1]] == ["720p"]
    assert "480p" in cleared["diffs"][1]["changed"]
    # ep 2's only quality is unchanged, and empty 480/1080 stay empty → unchanged
    assert 2 in cleared["unchanged"]


# ---------- db in-place ids ----------
def test_db_update_preserves_link_ids_and_clears_removed(tmp_path):
    from db import Database
    db = Database(f"sqlite:///{tmp_path}/e.db")
    d = db.add_drama(title="ID Show", status="Completed", total_episodes=1,
                     episodes={1: [("480p", "https://a/480", "part"),
                                   ("720p", "https://a/720", "part"),
                                   ("720p", "https://m/720", "mirror"),
                                   ("1080p", "https://a/1080", "part")]})
    ep = d.episodes[0]
    id_480 = next(l.id for l in ep.links if l.quality == "480p")
    id_720 = next(l.id for l in ep.links if l.quality == "720p" and l.kind == "part")
    id_m = next(l.id for l in ep.links if l.kind == "mirror")
    id_1080 = next(l.id for l in ep.links if l.quality == "1080p")

    updated = db.update_episode_links(ep.id, [
        ("480p", "https://b/480", "part"),
        ("720p", "https://b/720", "part"),
        ("720p", "https://b/720-p2", "part"),
    ], replace_qualities={"480p", "720p", "1080p"})
    assert any(l.id == id_480 and l.url == "https://b/480" for l in updated.links)
    assert any(l.id == id_720 and l.url == "https://b/720" for l in updated.links)
    # extra 720p part reuses the previous 720p row (the old mirror) so its /go id still works
    assert any(l.quality == "720p" and l.url == "https://b/720-p2" and l.id == id_m for l in updated.links)
    # 1080p was removed
    assert not any(l.id == id_1080 or l.quality == "1080p" for l in updated.links)
    assert updated.link_count == 3
    # leftover /go ids no longer resolve
    assert db.get_episode(ep.id)
    from db import EpisodeLink
    with db.session() as s:
        assert s.get(EpisodeLink, id_1080) is None
        assert s.get(EpisodeLink, id_480) is not None


def test_db_renumber_rejects_collision(tmp_path):
    from db import Database
    db = Database(f"sqlite:///{tmp_path}/e.db")
    d = db.add_drama(title="Nums", status="Completed", total_episodes=2,
                     episodes={1: [("720p", "https://a/1", "part")],
                               2: [("720p", "https://a/2", "part")]})
    ep1 = next(e for e in d.episodes if e.number == 1)
    try:
        db.update_episode_links(ep1.id, [("720p", "https://a/1", "part")],
                                new_number=2, replace_qualities={"720p"})
        raise AssertionError("should have rejected collision")
    except ValueError as e:
        assert "already exists" in str(e)
    ep1 = db.get_episode(ep1.id)
    assert ep1.number == 1
    db.update_episode_links(ep1.id, [("720p", "https://a/1b", "part")],
                            new_number=5, replace_qualities={"720p"})
    assert db.get_episode(ep1.id).number == 5
    assert [e.number for e in db.get_drama(d.id).episodes] == [2, 5]


# ---------- admin pages ----------
def test_edit_page_linked_prefilled_and_csrf(web):
    d = _login_drama(web, "Edit Page Show", n=2)
    ep1 = next(e for e in d.episodes if e.number == 1)
    st, body, _ = web.open(f"/admin/drama/{d.id}")
    assert st == 200
    assert f"/admin/drama/{d.id}/episode/{ep1.id}" in body
    assert "Edit</a>" in body
    assert f'href="/admin/drama/{d.id}/links?season=' in body
    assert "Bulk edit links" in body

    st, body, _ = web.open(f"/admin/drama/{d.id}/episode/{ep1.id}")
    assert st == 200 and "Edit episode links" in body
    assert 'id="editep-form"' in body
    assert 'value="https://old/1-720"' in body
    assert 'value="https://old/1-480"' in body
    assert 'value="https://old/1-1080"' in body
    assert 'name="episode"' in body and 'value="1"' in body
    assert "always silent" in body.lower() or "nothing is posted" in body.lower()
    # CSRF required
    st, body, _ = web.open("/admin/drama/editep", {
        "drama_id": str(d.id), "episode_id": str(ep1.id),
        "episode": "1", "qualities": "480p,720p,1080p",
        "720p": "https://new/1-720",
    })
    assert st == 403 and "CSRF" in body
    # missing episode 404
    st, body, _ = web.open(f"/admin/drama/{d.id}/episode/99999")
    assert st == 404


def test_edit_saves_in_place_preserves_go_and_clicks(web):
    d = _login_drama(web, "Go Show", n=2)
    ep1 = next(e for e in d.episodes if e.number == 1)
    link_720 = next(l for l in ep1.links if l.quality == "720p")
    old_id = link_720.id
    web.db.add_click(d.id, 1, "720p", None, season=1)
    # public /go before
    st, hdrs, _ = raw(web, f"/go/{old_id}")
    assert st in (302, 303) and hdrs.get("Location") == "https://old/1-720"

    _, body, _ = web.open(f"/admin/drama/{d.id}/episode/{ep1.id}")
    csrf = web.csrf_from(body)
    web.bot.sent.clear()
    st, body, _ = web.open("/admin/drama/editep", {
        "csrf": csrf, "drama_id": str(d.id), "episode_id": str(ep1.id),
        "episode": "1", "qualities": "480p,720p,1080p",
        "480p": "https://old/1-480",
        "720p": "https://new/1-720",
        "1080p": "https://old/1-1080",
    })
    assert st == 200 and ("links saved" in body.lower() or "Episode 1" in body)
    ep1 = web.db.get_episode(ep1.id)
    kept = next(l for l in ep1.links if l.quality == "720p")
    assert kept.id == old_id and kept.url == "https://new/1-720"
    # no Telegram activity; next-air left alone
    assert not any("announce" in s or "refresh" in s or "post_card" in s for s in web.bot.sent)
    d = web.db.get_drama(d.id)
    assert d.next_ep_date == "2026-12-01" and d.air_time == "20:00"
    # /go still uses the same id, now pointing at the new URL; clicks still recorded
    st, hdrs, _ = raw(web, f"/go/{old_id}")
    assert st in (302, 303) and hdrs.get("Location") == "https://new/1-720"
    from sqlalchemy import select, func
    from db import Click
    with web.db.session() as s:
        n = int(s.scalar(select(func.count()).select_from(Click).where(
            Click.drama_id == d.id, Click.episode == 1, Click.quality == "720p")) or 0)
    assert n >= 1


def test_edit_remove_quality_old_go_404s_and_renumber(web):
    d = _login_drama(web, "Remove Show", n=2)
    ep1 = next(e for e in d.episodes if e.number == 1)
    gone = next(l.id for l in ep1.links if l.quality == "1080p")
    keep = next(l.id for l in ep1.links if l.quality == "720p")
    _, body, _ = web.open(f"/admin/drama/{d.id}/episode/{ep1.id}")
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/editep", {
        "csrf": csrf, "drama_id": str(d.id), "episode_id": str(ep1.id),
        "episode": "8", "qualities": "480p,720p,1080p",
        "720p": "https://old/1-720",
        # 480p and 1080p cleared
    })
    assert st == 200 and "renumbered to 8" in body.lower()
    ep1 = web.db.get_episode(ep1.id)
    assert ep1.number == 8 and ep1.link_count == 1
    assert next(l.id for l in ep1.links) == keep
    st, _, _ = raw(web, f"/go/{gone}")
    assert st == 404
    st, hdrs, _ = raw(web, f"/go/{keep}")
    assert st in (302, 303) and hdrs.get("Location") == "https://old/1-720"
    # collision rejected
    ep2 = next(e for e in web.db.get_drama(d.id).episodes if e.number == 2)
    _, body, _ = web.open(f"/admin/drama/{d.id}/episode/{ep1.id}")
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/editep", {
        "csrf": csrf, "drama_id": str(d.id), "episode_id": str(ep1.id),
        "episode": "2", "qualities": "480p,720p,1080p",
        "720p": "https://old/1-720",
    })
    assert st == 200 and "already exists" in body.lower()
    assert web.db.get_episode(ep1.id).number == 8
    assert web.db.get_episode(ep2.id).number == 2


def test_edit_rejects_empty_and_bad_url(web):
    d = _login_drama(web, "Bad Edit", n=1)
    ep = d.episodes[0]
    _, body, _ = web.open(f"/admin/drama/{d.id}/episode/{ep.id}")
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/editep", {
        "csrf": csrf, "drama_id": str(d.id), "episode_id": str(ep.id),
        "episode": "1", "qualities": "480p,720p,1080p",
    })
    assert st == 200 and "at least one" in body.lower()
    assert web.db.get_episode(ep.id).link_count == 3
    st, body, _ = web.open("/admin/drama/editep", {
        "csrf": csrf, "drama_id": str(d.id), "episode_id": str(ep.id),
        "episode": "1", "qualities": "480p,720p,1080p",
        "720p": "ftp://nope",
    })
    assert st == 200 and "http" in body.lower()
    assert "ftp://nope" not in [l.url for l in web.db.get_episode(ep.id).links]


# ---------- bulk edit ----------
def test_bulk_edit_page_preview_does_not_write(web):
    d = _login_drama(web, "Preview Links", n=2)
    st, body, _ = web.open(f"/admin/drama/{d.id}/links")
    assert st == 200 and "Bulk edit links" in body and "Update existing episodes" in body
    assert 'id="bulk-links-form"' in body
    assert "Range templates" in body and "Paste list" in body
    assert "Clear empty qualities" in body
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/links", {
        "drama_id": str(d.id), "mode": "range", "ep_from": "1", "ep_to": "4",
        "720p": "https://new/{ep}-720", "action": "apply",
    })
    assert st == 403 and "CSRF" in body
    st, body, _ = web.open("/admin/drama/links", {
        "csrf": csrf, "drama_id": str(d.id), "mode": "range", "season": "1",
        "ep_from": "1", "ep_to": "4", "720p": "https://new/{ep}-720",
        "action": "preview",
    })
    assert st == 200 and "Update preview" in body
    assert "will update" in body.lower()
    assert "EP 1" in body and "EP 2" in body
    assert "https://old/1-720" in body and "https://new/1-720" in body
    assert "not in the database" in body.lower()
    # preview did not write
    d = web.db.get_drama(d.id)
    assert [l.url for e in d.episodes for l in e.links if l.quality == "720p"] == [
        "https://old/1-720", "https://old/2-720",
    ]
    assert [e.number for e in d.episodes] == [1, 2]


def test_bulk_edit_range_only_existing_blank_unchanged(web):
    d = _login_drama(web, "Range Update", n=2)
    ep1 = next(e for e in d.episodes if e.number == 1)
    id_720 = next(l.id for l in ep1.links if l.quality == "720p")
    id_480 = next(l.id for l in ep1.links if l.quality == "480p")
    _, body, _ = web.open(f"/admin/drama/{d.id}/links")
    csrf = web.csrf_from(body)
    web.bot.sent.clear()
    st, body, _ = web.open("/admin/drama/links", {
        "csrf": csrf, "drama_id": str(d.id), "mode": "range", "season": "1",
        "ep_from": "1", "ep_to": "5",
        "720p": "https://new/{ep}-720",
        "action": "apply",
    })
    assert st == 200 and "updated" in body.lower()
    assert "not in database" in body.lower() or "not in the database" in body.lower()
    d = web.db.get_drama(d.id)
    assert [e.number for e in d.episodes] == [1, 2]  # 3–5 were not created
    ep1 = next(e for e in d.episodes if e.number == 1)
    assert next(l.id for l in ep1.links if l.quality == "720p") == id_720
    assert next(l.url for l in ep1.links if l.quality == "720p") == "https://new/1-720"
    # blank 480p/1080p left alone, same ids
    assert next(l.id for l in ep1.links if l.quality == "480p") == id_480
    assert next(l.url for l in ep1.links if l.quality == "480p") == "https://old/1-480"
    assert next(l.url for l in ep1.links if l.quality == "1080p") == "https://old/1-1080"
    ep2 = next(e for e in d.episodes if e.number == 2)
    assert next(l.url for l in ep2.links if l.quality == "720p") == "https://new/2-720"
    # silent: no posts, next-air unchanged
    assert not any("announce" in s or "refresh" in s or "post_card" in s for s in web.bot.sent)
    assert d.next_ep_date == "2026-12-01"
    # public page shows new url via same /go id
    st, hdrs, _ = raw(web, f"/go/{id_720}")
    assert st in (302, 303) and hdrs.get("Location") == "https://new/1-720"


def test_bulk_edit_paste_and_clear_empty(web):
    d = _login_drama(web, "Paste Update", n=2)
    ep1 = next(e for e in d.episodes if e.number == 1)
    gone = next(l.id for l in ep1.links if l.quality == "1080p")
    paste = "\n".join([
        "1 | https://new/1-480 | https://new/1-720 |",
        "9 | https://new/9-480 | https://new/9-720 | https://new/9-1080",
    ])
    _, body, _ = web.open(f"/admin/drama/{d.id}/links")
    csrf = web.csrf_from(body)
    st, body, _ = web.open("/admin/drama/links", {
        "csrf": csrf, "drama_id": str(d.id), "mode": "paste", "season": "1",
        "paste": paste, "clear_empty": "1", "action": "apply",
    })
    assert st == 200 and "updated" in body.lower()
    d = web.db.get_drama(d.id)
    assert [e.number for e in d.episodes] == [1, 2]  # 9 not added
    ep1 = next(e for e in d.episodes if e.number == 1)
    quals = {l.quality for l in ep1.links}
    assert quals == {"480p", "720p"}  # 1080p cleared because the paste column was empty
    assert next(l.url for l in ep1.links if l.quality == "720p") == "https://new/1-720"
    # ep 2 was not in the paste, left alone
    ep2 = next(e for e in d.episodes if e.number == 2)
    assert next(l.url for l in ep2.links if l.quality == "720p") == "https://old/2-720"
    st, _, _ = raw(web, f"/go/{gone}")
    assert st == 404
    # public drama page still lists both existing episodes
    st, _, pub = raw(web, f"/drama/{d.id}")
    assert st == 200 and ("EP 1" in pub or "ep=1" in pub) and ("EP 2" in pub or "ep=2" in pub)
