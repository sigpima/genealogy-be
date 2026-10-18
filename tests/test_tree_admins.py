"""Superadmin console: the admins of a family (list, add, promote, enable/disable, new password)."""

import pytest
from sqlalchemy import text

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    for key, role, tree in [("admin_a", "admin", tree_a), ("member_a", "member", tree_a), ("admin_b", "admin", tree_b)]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"a": tree_a, "b": tree_b, "session": session}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def user_id(session, email):
    return (await session.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})).scalar_one()


async def events(session):
    rows = (await session.execute(text("SELECT action, details FROM platform_events WHERE action LIKE 'admin.%' ORDER BY id"))).all()
    return [(a, d) for a, d in rows]


async def test_list_shows_only_the_admins_of_that_family(world, make_client):
    root = await signed_in(make_client, "root")
    rows = (await root.get(f"/trees/{world['a'].id}/admins")).json()
    assert [r["email"] for r in rows] == ["admin_a@example.com"]
    assert set(rows[0]) == {"id", "email", "full_name", "status", "last_login_at"}
    assert (await root.get("/trees/9999/admins")).status_code == 404


async def test_create_a_new_admin_with_a_generated_password_shown_once(world, make_client):
    root = await signed_in(make_client, "root")
    r = await root.post(f"/trees/{world['a'].id}/admins", json={"email": "moi@example.com", "full_name": "Admin Mới"})
    assert r.status_code == 201
    password = r.json()["password"]
    assert password and r.json()["admin"]["email"] == "moi@example.com" and r.json()["admin"]["status"] == "active"
    assert (await login(make_client(), "moi@example.com", password)).status_code == 200
    assert {a["email"] for a in (await root.get(f"/trees/{world['a'].id}/admins")).json()} == {"admin_a@example.com", "moi@example.com"}
    assert password not in str(await events(world["session"]))


async def test_create_with_a_typed_password_returns_none(world, make_client):
    root = await signed_in(make_client, "root")
    r = await root.post(f"/trees/{world['a'].id}/admins", json={"email": "go@example.com", "full_name": "Gõ", "password": "tu-dat-mat-khau"})
    assert r.status_code == 201 and r.json()["password"] is None
    assert (await login(make_client(), "go@example.com", "tu-dat-mat-khau")).status_code == 200


async def test_an_email_that_exists_anywhere_is_a_conflict(world, make_client):
    root = await signed_in(make_client, "root")
    for email in ("admin_b@example.com", "member_a@example.com", "root@example.com"):
        assert (await root.post(f"/trees/{world['a'].id}/admins", json={"email": email, "full_name": "X"})).status_code == 409


async def test_promote_one_of_the_familys_own_users_even_if_pending_or_disabled(world, make_client):
    session = world["session"]
    await create_user(session, email="cho@example.com", full_name="Chờ", password=PASSWORD, role="member", tree=world["a"], status="pending")
    root = await signed_in(make_client, "root")
    for email in ("member_a@example.com", "cho@example.com"):
        r = await root.post(f"/trees/{world['a'].id}/admins", json={"user_id": await user_id(session, email)})
        assert r.status_code in (200, 201) and r.json()["admin"]["status"] == "active" and r.json()["password"] is None
    assert (await login(make_client(), "cho@example.com", PASSWORD)).status_code == 200
    assert [a for a, _ in await events(session)] == ["admin.promote", "admin.promote"]


async def test_promote_refuses_other_trees_users_superadmins_and_unknown_ids(world, make_client):
    session = world["session"]
    root = await signed_in(make_client, "root")
    for target in (await user_id(session, "admin_b@example.com"), await user_id(session, "root@example.com"), 9999):
        assert (await root.post(f"/trees/{world['a'].id}/admins", json={"user_id": target})).status_code == 404


async def test_a_family_always_keeps_an_active_admin(world, make_client):
    session = world["session"]
    root = await signed_in(make_client, "root")
    only = await user_id(session, "admin_a@example.com")
    assert (await root.patch(f"/trees/{world['a'].id}/admins/{only}", json={"status": "disabled"})).status_code == 409
    await root.post(f"/trees/{world['a'].id}/admins", json={"email": "hai@example.com", "full_name": "Hai", "password": "mat-khau-hai-1"})
    assert (await root.patch(f"/trees/{world['a'].id}/admins/{only}", json={"status": "disabled"})).status_code == 200
    assert (await login(make_client(), "admin_a@example.com")).status_code == 403  # disabled
    second = await user_id(session, "hai@example.com")
    assert (await root.patch(f"/trees/{world['a'].id}/admins/{second}", json={"status": "disabled"})).status_code == 409  # now the last one
    assert (await root.patch(f"/trees/{world['a'].id}/admins/{only}", json={"status": "active"})).status_code == 200
    updates = [d for a, d in await events(session) if a == "admin.update"]
    assert updates[0]["changes"] == {"status": ["active", "disabled"]}


async def test_new_password_for_an_admin_is_returned_once_and_never_logged(world, make_client):
    session = world["session"]
    root = await signed_in(make_client, "root")
    target = await user_id(session, "admin_a@example.com")
    r = await root.post(f"/trees/{world['a'].id}/admins/{target}/password", json={})
    assert r.status_code == 200
    new = r.json()["password"]
    assert (await login(make_client(), "admin_a@example.com", PASSWORD)).status_code == 401
    assert (await login(make_client(), "admin_a@example.com", new)).status_code == 200
    typed = (await root.post(f"/trees/{world['a'].id}/admins/{target}/password", json={"password": "tu-dat-12345"})).json()
    assert typed == {"password": "tu-dat-12345"}
    assert new not in str(await events(session)) and "tu-dat-12345" not in str(await events(session))
    assert (await root.post(f"/trees/{world['a'].id}/admins/{target}/password", json={"password": "ngan"})).status_code == 422


async def test_only_admins_of_that_family_are_addressable(world, make_client):
    session = world["session"]
    root = await signed_in(make_client, "root")
    member = await user_id(session, "member_a@example.com")  # not an admin
    other = await user_id(session, "admin_b@example.com")  # another family's admin
    boss = await user_id(session, "root@example.com")
    for target in (member, other, boss, 9999):
        assert (await root.patch(f"/trees/{world['a'].id}/admins/{target}", json={"status": "disabled"})).status_code == 404
        assert (await root.post(f"/trees/{world['a'].id}/admins/{target}/password", json={})).status_code == 404


async def test_it_works_on_a_paused_family_and_only_for_the_superadmin(world, make_client):
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    assert (await root.post(f"/trees/{world['a'].id}/admins", json={"email": "p@example.com", "full_name": "P"})).status_code == 201
    admin_b = await signed_in(make_client, "admin_b")
    assert (await admin_b.get(f"/trees/{world['b'].id}/admins")).status_code == 403
    assert (await make_client().get(f"/trees/{world['b'].id}/admins")).status_code == 401
