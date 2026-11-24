"""reset_demo: the 'demo' tree behind /guest is made and replaced without ever touching another family."""

import dataclasses

import pytest
from sqlalchemy import func, select

from app.core.data_health import check_layout
from app.core.demo import DEMO_NAME, DEMO_SLUG, DemoGuardError, DemoPerson, build_demo_family, reset_demo
from app.core.roles import get_tree_settings
from app.core.tenants import create_tree, create_user, get_tree_by_slug
from app.core.tree_layout import load_layout
from app.models import article  # noqa: F401  (registers the tables Media/Member point at)
from app.models.article import Article, GenerationWord, TimelineEntry
from app.models.branch import Branch
from app.models.event import Event
from app.models.marriage import Marriage
from app.models.member import Member
from app.models.place import Place  # noqa: F401
from app.models.site_setting import SiteSetting
from app.models.tree import Tree
from app.models.user import User


async def _count(session, model, tree_id):
    return (await session.execute(select(func.count()).select_from(model).where(model.tree_id == tree_id))).scalar_one()


async def _blood_names(session, tree_id):
    rows = await session.execute(select(Member.full_name).where(Member.tree_id == tree_id).order_by(Member.id))
    return [name for (name,) in rows]


async def _snapshot(session, tree_id):
    """Everything about one family that a reset of another family must leave alone."""
    tree = (await session.execute(select(Tree.name, Tree.slug, Tree.status).where(Tree.id == tree_id))).one()
    counts = {m.__name__: await _count(session, m, tree_id) for m in (Member, Branch, Article, TimelineEntry, GenerationWord, Event, User)}
    counts["Marriage"] = (
        await session.execute(
            select(func.count()).select_from(Marriage).join(Member, Member.id == Marriage.member_id).where(Member.tree_id == tree_id)
        )
    ).scalar_one()
    emails = [e for (e,) in await session.execute(select(User.email).where(User.tree_id == tree_id).order_by(User.id))]
    avatars = [a for (a,) in await session.execute(select(Member.avatar_url).where(Member.tree_id == tree_id).order_by(Member.id))]
    return {
        "tree": tuple(tree),
        "counts": counts,
        "names": await _blood_names(session, tree_id),
        "emails": emails,
        "avatars": avatars,
        "settings": await get_tree_settings(session, tree_id),
    }


async def _real_family(session, upload_dir):
    """A family with an admin, people (one with an avatar file), a marriage, an article, an event; private."""
    real = await create_tree(session, "Họ thật", "ho-that")
    await create_user(session, email="admin@ho-that.vn", full_name="Admin", password="password123", role="admin", tree=real)
    father = Member(tree_id=real.id, full_name="Người thật Một", avatar_url="/uploads/avatars/real.jpg")
    session.add(father)
    await session.flush()
    child = Member(tree_id=real.id, full_name="Người thật Hai", parent_id=father.id)
    spouse = Member(tree_id=real.id, full_name="Người thật Ba")
    session.add_all([child, spouse])
    await session.flush()
    session.add(Marriage(member_id=father.id, spouse_id=spouse.id, marriage_year=1990))
    session.add(Article(tree_id=real.id, title="Bài thật", slug="bai-that", kind="origin", body="x", status="published"))
    session.add(Event(tree_id=real.id, title="Giỗ thật", kind="memorial", calendar="lunar", month=1, day=1, repeats_yearly=True))
    session.add(SiteSetting(tree_id=real.id, key="visibility", value="private"))
    await session.commit()
    (upload_dir / "avatars").mkdir(parents=True, exist_ok=True)
    (upload_dir / "avatars" / "real.jpg").write_bytes(b"real photo")
    return real


async def test_reset_creates_a_public_demo_tree(session):
    summary = await reset_demo(session)
    trees = (await session.execute(select(Tree).where(Tree.slug == DEMO_SLUG))).scalars().all()
    assert len(trees) == 1
    tree = trees[0]
    assert (tree.name, tree.status, summary.tree_id) == (DEMO_NAME, "active", tree.id)
    assert (await get_tree_settings(session, tree.id))["visibility"] == "public"
    family = build_demo_family()
    blood = [p for p in family.people if p.partner_key is None]
    assert summary.members == len(blood)
    assert summary.spouses == len(family.people) - len(blood)
    assert summary.articles == len(family.articles)
    assert await _count(session, Member, tree.id) == len(family.people)


async def test_reset_twice_gives_the_same_data(session):
    await reset_demo(session)
    first = await _blood_names(session, (await get_tree_by_slug(session, DEMO_SLUG)).id)
    await reset_demo(session)
    tree = await get_tree_by_slug(session, DEMO_SLUG)
    assert await _blood_names(session, tree.id) == first
    assert (await session.execute(select(func.count()).select_from(Tree).where(Tree.slug == DEMO_SLUG))).scalar_one() == 1


async def test_guest_reads_only_the_in_scope_parts(session, make_client):
    await reset_demo(session)
    guest = make_client()
    guest.cookies.set("tree_slug", DEMO_SLUG)

    info = (await guest.get("/site/info")).json()
    assert (info["visibility"], info["tree_slug"]) == ("public", DEMO_SLUG)
    tree = await guest.get("/members/tree")
    assert tree.status_code == 200 and tree.json()["name"]
    search = await guest.get("/members/search", params={"q": "Lê"})
    assert search.status_code == 200 and search.json()["total"] > 0
    assert (await guest.get("/stats/overview")).status_code == 200
    assert len((await guest.get("/branches")).json()) == 3
    assert len((await guest.get("/timeline")).json()) >= 5
    assert len((await guest.get("/generation-poem")).json()) == 6
    assert (await guest.get("/calendar/upcoming")).status_code == 200
    titles = [a["title"] for a in (await guest.get("/articles")).json()]
    assert len(titles) == 3 and "Bản nháp chưa đăng" not in titles
    assert (await guest.get("/places")).status_code == 401  # out of scope: places are for signed-in readers


async def test_other_tree_is_untouched(session, upload_dir):
    real = await _real_family(session, upload_dir)
    before = await _snapshot(session, real.id)
    await reset_demo(session)
    await reset_demo(session)
    assert await _snapshot(session, real.id) == before
    assert (upload_dir / "avatars" / "real.jpg").read_bytes() == b"real photo"


async def test_failed_reset_keeps_the_previous_demo(session):
    await reset_demo(session)
    tree = await get_tree_by_slug(session, DEMO_SLUG)
    tree_id, members = tree.id, await _count(session, Member, tree.id)

    family = build_demo_family()
    broken = DemoPerson(**{**dataclasses.asdict(family.people[0]), "key": 99999, "parent_key": 999999, "partner_key": None})
    with pytest.raises(Exception):
        await reset_demo(session, dataclasses.replace(family, people=[*family.people, broken]))

    after = await get_tree_by_slug(session, DEMO_SLUG)
    assert after.id == tree_id
    assert await _count(session, Member, tree_id) == members


async def test_refuses_a_demo_slug_that_has_accounts(session):
    tree = await create_tree(session, DEMO_NAME, DEMO_SLUG)
    await create_user(session, email="boss@x.vn", full_name="Boss", password="password123", role="admin", tree=tree)
    tree_id = tree.id  # the rollback inside reset_demo expires `tree`
    session.add(Member(tree_id=tree_id, full_name="Người thật"))
    await session.commit()
    with pytest.raises(DemoGuardError):
        await reset_demo(session)
    assert (await session.execute(select(func.count()).select_from(User).where(User.tree_id == tree_id))).scalar_one() == 1
    assert await _blood_names(session, tree_id) == ["Người thật"]


async def test_refuses_a_demo_slug_with_another_name(session):
    tree = await create_tree(session, "Họ khác", DEMO_SLUG)
    tree_id = tree.id
    session.add(Member(tree_id=tree_id, full_name="Người thật"))
    await session.commit()
    with pytest.raises(DemoGuardError):
        await reset_demo(session)
    assert (await get_tree_by_slug(session, DEMO_SLUG)).name == "Họ khác"
    assert await _blood_names(session, tree_id) == ["Người thật"]


async def test_generated_data_has_no_data_health_warnings(session):
    summary = await reset_demo(session)
    findings = check_layout(await load_layout(session, summary.tree_id))
    assert [f for f in findings if f.severity == "warning"] == []
