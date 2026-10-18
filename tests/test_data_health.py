"""Admin console: data health checks (pure checks over a tree loaded in memory, plus the media files on disk)."""

import pytest

from app.core.data_health import check_layout, check_media
from app.core.tenants import create_tree, create_user
from app.core.tree_layout import load_layout
from app.models.marriage import Marriage
from app.models.media import Media
from app.models.member import Member
from app.models.place import Place  # noqa: F401  (Member.burial_place_id needs its target table registered)
from app.models import article  # noqa: F401  (Media.article_id needs its target table registered)
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [("admin_a", "admin", tree_a), ("member_a", "member", tree_a), ("admin_b", "admin", tree_b)]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"tree_a": tree_a, "tree_b": tree_b, "session": session}


async def person(session, tree, name, parent=None, **fields):
    m = Member(tree_id=tree.id, full_name=name, parent_id=parent.id if parent else None, **fields)
    session.add(m)
    await session.flush()
    return m


async def findings(world, tree=None):
    await world["session"].commit()
    return check_layout(await load_layout(world["session"], (tree or world["tree_a"]).id))


def kinds(found):
    return sorted((f.kind, f.member_name) for f in found)


async def test_a_clean_tree_has_no_findings(world):
    s, t = world["session"], world["tree_a"]
    to = await person(s, t, "Tổ", birth_year=1900, death_year=1970)
    await person(s, t, "An", to, birth_year=1930)
    assert await findings(world) == []


async def test_child_born_before_the_parent_is_flagged_on_the_child(world):
    s, t = world["session"], world["tree_a"]
    to = await person(s, t, "Tổ", birth_year=1900)
    await person(s, t, "Con sớm", to, birth_year=1890)
    assert kinds(await findings(world)) == [("child_before_parent", "Con sớm")]


async def test_parent_gap_under_12_and_over_70_is_flagged(world):
    s, t = world["session"], world["tree_a"]
    to = await person(s, t, "Tổ", birth_year=1900)
    await person(s, t, "Con nhỏ tuổi", to, birth_year=1905)
    await person(s, t, "Con muộn", to, birth_year=1975)
    await person(s, t, "Con bình thường", to, birth_year=1930)
    assert kinds(await findings(world)) == [("parent_age_gap", "Con muộn"), ("parent_age_gap", "Con nhỏ tuổi")]


async def test_death_before_birth_is_flagged(world):
    s, t = world["session"], world["tree_a"]
    await person(s, t, "Ngược", birth_year=1950, death_year=1940)
    assert kinds(await findings(world)) == [("death_before_birth", "Ngược")]


async def test_duplicates_ignore_accents_and_case_and_need_a_birth_year(world):
    s, t = world["session"], world["tree_a"]
    to = await person(s, t, "Tổ", birth_year=1900)
    await person(s, t, "Nguyễn Văn An", to, birth_year=1930)
    await person(s, t, "NGUYEN VAN AN", to, birth_year=1930)
    await person(s, t, "Nguyễn Văn Bình", to)  # no birth year: not comparable
    await person(s, t, "Nguyễn Văn Bình", to)
    found = await findings(world)
    assert sorted(f.member_name for f in found if f.kind == "duplicate_name_year") == ["NGUYEN VAN AN", "Nguyễn Văn An"]


async def test_spouses_are_not_checked_as_children(world):
    s, t = world["session"], world["tree_a"]
    to = await person(s, t, "Tổ", birth_year=1900)
    wife = await person(s, t, "Vợ", birth_year=1850)  # older than the husband, no parent: fine
    s.add(Marriage(member_id=to.id, spouse_id=wife.id))
    assert await findings(world) == []


async def test_missing_birth_year_above_a_dated_descendant_is_only_info(world):
    s, t = world["session"], world["tree_a"]
    to = await person(s, t, "Tổ")
    an = await person(s, t, "An", to)
    await person(s, t, "Anh", an, birth_year=1950)
    found = await findings(world)
    assert {(f.kind, f.severity) for f in found} == {("ancestor_gap_undated", "info")}
    assert sorted(f.member_name for f in found) == ["An", "Tổ"]


async def test_a_tree_without_any_dates_is_not_noisy(world):
    s, t = world["session"], world["tree_a"]
    to = await person(s, t, "Tổ")
    await person(s, t, "An", to)
    assert await findings(world) == []


async def test_other_trees_are_not_checked(world):
    s = world["session"]
    await person(s, world["tree_b"], "Ngược", birth_year=1950, death_year=1940)
    assert await findings(world) == []
    assert len(await findings(world, world["tree_b"])) == 1


async def test_media_files_missing_on_disk_and_orphans(world, tmp_path):
    s, t = world["session"], world["tree_a"]
    to = await person(s, t, "Tổ")
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "present.jpg").write_bytes(b"x")
    common = dict(tree_id=t.id, kind="image", content_type="image/jpeg", size=1)
    s.add_all([
        Media(member_id=to.id, original_name="co.jpg", stored_name="present.jpg", **common),
        Media(member_id=to.id, original_name="mat.jpg", stored_name="missing.jpg", **common),
        Media(original_name="mo-coi.jpg", stored_name="orphan.jpg", **common),
    ])
    await s.commit()
    found = await check_media(s, t.id, tmp_path)
    assert sorted((f.kind, f.message.split(" ")[0]) for f in found) == [("media_file_missing", "mat.jpg"), ("media_file_missing", "mo-coi.jpg"), ("media_orphan", "mo-coi.jpg")]


async def test_the_endpoint_returns_findings_and_counts_and_feeds_the_overview(world, make_client):
    s, t = world["session"], world["tree_a"]
    to = await person(s, t, "Tổ", birth_year=1900)
    await person(s, t, "Con sớm", to, birth_year=1890)
    await s.commit()
    admin = make_client()
    assert (await login(admin, "admin_a@example.com")).status_code == 200
    body = (await admin.get("/admin/data-health")).json()
    assert body["counts"] == {"child_before_parent": 1}
    assert body["findings"][0]["member_name"] == "Con sớm" and body["findings"][0]["member_id"] is not None
    items = {i["key"]: i for i in (await admin.get("/admin/overview")).json()["items"]}
    assert items["data_issues"]["count"] == 1 and items["data_issues"]["href"] == "/admin/suc-khoe-du-lieu"


async def test_members_403_and_guests_401(world, make_client):
    member = make_client()
    assert (await login(member, "member_a@example.com")).status_code == 200
    assert (await member.get("/admin/data-health")).status_code == 403
    assert (await make_client().get("/admin/data-health")).status_code == 401
