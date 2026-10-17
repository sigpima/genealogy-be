import pytest
from sqlalchemy import select

from app.cli import run
from app.core.tenants import (
    TenantError,
    create_tree,
    create_user,
    get_or_create_default_tree,
    get_tree_by_slug,
    rename_tree,
    set_user_role,
)
from app.models.member import Member
from app.models.user import User
from tests.test_roles_auth import PASSWORD, login

# ------------------------------------------------------------------ service


async def test_create_tree_validates_name_and_slug(session):
    tree = await create_tree(session, "  Họ Nguyễn  ", "ho-nguyen")
    assert (tree.name, tree.slug) == ("Họ Nguyễn", "ho-nguyen")
    for bad_slug in ("", "Ho-Nguyen", "ho nguyen", "-ho", "ho-", "ho--nguyen", "họ", "a" * 61):
        with pytest.raises(TenantError):
            await create_tree(session, "X", bad_slug)
    with pytest.raises(TenantError):
        await create_tree(session, "   ", "fine-slug")
    with pytest.raises(TenantError, match="already exists"):
        await create_tree(session, "Again", "ho-nguyen")


async def test_default_tree_is_created_once(session):
    first = await get_or_create_default_tree(session)
    assert first.slug == "default"
    assert (await get_or_create_default_tree(session)).id == first.id


async def test_rename_tree_changes_name_and_slug(session, tree):
    renamed = await rename_tree(session, tree.slug, name="Tên mới", new_slug="ten-moi")
    assert (renamed.name, renamed.slug) == ("Tên mới", "ten-moi")
    assert await get_tree_by_slug(session, "test-tree") is None
    with pytest.raises(TenantError):
        await rename_tree(session, "missing", name="X")
    other = await create_tree(session, "Other", "other")
    with pytest.raises(TenantError, match="already exists"):
        await rename_tree(session, other.slug, new_slug="ten-moi")


async def test_role_and_tree_rules(session, tree):
    with pytest.raises(TenantError, match="belongs to no tree"):
        await create_user(session, email="a@example.com", full_name="A", password=PASSWORD, role="superadmin", tree=tree)
    with pytest.raises(TenantError, match="must belong to a tree"):
        await create_user(session, email="a@example.com", full_name="A", password=PASSWORD, role="admin", tree=None)
    with pytest.raises(TenantError, match="role"):
        await create_user(session, email="a@example.com", full_name="A", password=PASSWORD, role="root", tree=tree)
    with pytest.raises(TenantError, match="at least 8"):
        await create_user(session, email="a@example.com", full_name="A", password="short", role="member", tree=tree)
    await create_user(session, email="a@example.com", full_name="A", password=PASSWORD, role="member", tree=tree)
    with pytest.raises(TenantError, match="already registered"):
        await create_user(session, email="a@example.com", full_name="A2", password=PASSWORD, role="member", tree=tree)


async def test_set_user_role_moves_between_tree_and_platform_level(session, tree):
    await create_user(session, email="a@example.com", full_name="A", password=PASSWORD, role="admin", tree=tree)
    promoted = await set_user_role(session, "a@example.com", "superadmin", None)
    assert (promoted.role, promoted.tree_id) == ("superadmin", None)
    demoted = await set_user_role(session, "a@example.com", "admin", tree)
    assert (demoted.role, demoted.tree_id) == ("admin", tree.id)
    with pytest.raises(TenantError, match="no user"):
        await set_user_role(session, "nobody@example.com", "member", tree)


# ---------------------------------------------------------------------- CLI


async def test_cli_creates_a_tree_and_an_admin_who_can_log_in(session, client):
    out = await run(["create-tree", "--name", "Nguyễn Tộc Phú Ốc", "--slug", "phu-oc"], session)
    assert "phu-oc" in out
    out = await run(
        ["create-user", "--email", "admin-demo@example.com", "--name", "Admin Demo",
         "--role", "admin", "--tree", "phu-oc", "--password", PASSWORD],
        session,
    )
    assert "admin-demo@example.com" in out and PASSWORD not in out  # a given password is never echoed
    assert (await login(client, "admin-demo@example.com")).status_code == 200
    me = (await client.get("/auth/me")).json()
    assert (me["role"], me["tree_name"]) == ("admin", "Nguyễn Tộc Phú Ốc")


async def test_cli_generates_a_password_when_none_is_given(session, client):
    await run(["create-tree", "--name", "T", "--slug", "t"], session)
    out = await run(["create-user", "--email", "gen@example.com", "--name", "G", "--role", "member", "--tree", "t"], session)
    line = next(line for line in out.splitlines() if line.startswith("password:"))
    generated = line.split(":", 1)[1].strip()
    assert len(generated) >= 12
    assert (await login(client, "gen@example.com", generated)).status_code == 200


async def test_cli_set_role_and_list(session):
    await run(["create-tree", "--name", "T", "--slug", "t"], session)
    await run(["create-user", "--email", "a@example.com", "--name", "A", "--role", "admin", "--tree", "t", "--password", PASSWORD], session)
    await run(["set-role", "--email", "a@example.com", "--role", "superadmin"], session)
    user = (await session.execute(select(User).where(User.email == "a@example.com"))).scalar_one()
    await session.refresh(user)
    assert (user.role, user.tree_id) == ("superadmin", None)
    listing = await run(["list"], session)
    assert "t" in listing and "a@example.com" in listing and "superadmin" in listing


async def test_cli_reports_mistakes_instead_of_crashing(session):
    assert "error" in (await run(["create-tree", "--name", "T", "--slug", "BAD SLUG"], session)).lower()
    assert "error" in (await run(["create-user", "--email", "a@example.com", "--name", "A", "--role", "admin", "--tree", "nope", "--password", PASSWORD], session)).lower()
    assert "error" in (await run(["set-role", "--email", "ghost@example.com", "--role", "member", "--tree", "nope"], session)).lower()


# ------------------------------------------------------------- seed script


async def test_seed_loads_a_tree_into_the_named_tree(session, tree):
    from scripts.seed_members import seed_tree

    count = await seed_tree(
        session,
        {"name": "Root", "title": "Tổ", "children": [{"name": "Kid 1"}, {"name": "Kid 2", "children": [{"name": "Grandkid"}]}]},
        tree,
    )
    assert count == 4
    members = (await session.execute(select(Member).order_by(Member.id))).scalars().all()
    assert [m.full_name for m in members] == ["Root", "Kid 1", "Kid 2", "Grandkid"]
    assert {m.tree_id for m in members} == {tree.id}
    assert members[0].title == "Tổ" and members[2].parent_id == members[0].id
