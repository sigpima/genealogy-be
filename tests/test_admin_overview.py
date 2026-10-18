"""Admin console: GET /admin/overview, the "Cần làm" list."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login, set_setting


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [("admin_a", "admin", tree_a), ("member_a", "member", tree_a), ("admin_b", "admin", tree_b)]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"tree_a": tree_a, "tree_b": tree_b, "session": session}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def overview(c):
    r = await c.get("/admin/overview")
    assert r.status_code == 200, r.text
    return r.json()


def by_key(body):
    return {item["key"]: item for item in body["items"]}


async def test_pending_requests_are_counted_and_old_pending_accounts_are_not_a_task(world, make_client):
    session = world["session"]
    for i in range(2):
        await create_user(session, email=f"p{i}@example.com", full_name=f"P{i}", password=PASSWORD, role="member", tree=world["tree_a"], status="pending")
    admin = await signed_in(make_client, "admin_a")
    to = (await admin.post("/members", json={"full_name": "Tổ", "birth_year": 1900})).json()["id"]
    member = await signed_in(make_client, "member_a")
    r = await member.post("/requests", json={"kind": "edit", "member_id": to, "changes": {"birth_year": 1901}, "message": "sửa năm sinh"})
    assert r.status_code == 201
    items = by_key(await overview(admin))
    assert "pending_users" not in items  # people no longer sign themselves up
    assert items["pending_requests"]["count"] == 1 and items["pending_requests"]["href"] == "/yeu-cau"


async def test_zero_items_are_left_out(world, make_client):
    body = await overview(await signed_in(make_client, "admin_a"))
    assert [i for i in body["items"] if i["kind"] == "task"] == []
    assert body["counts"] == {"members": 0, "users": 2, "pending_requests": 0}


async def test_a_public_tree_is_a_notice(world, make_client, session):
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    items = by_key(await overview(await signed_in(make_client, "admin_a")))
    assert items["public_tree"]["kind"] == "notice" and items["public_tree"]["href"] == "/admin/cai-dat"
    assert "open_registration" not in items and "pending_users" not in items


async def test_counts_are_this_trees_only(world, make_client):
    session = world["session"]
    await create_user(session, email="pb@example.com", full_name="PB", password=PASSWORD, role="member", tree=world["tree_b"], status="pending")
    admin_b = await signed_in(make_client, "admin_b")
    await admin_b.post("/members", json={"full_name": "Người họ B"})
    body = await overview(await signed_in(make_client, "admin_a"))
    assert body["counts"]["members"] == 0 and body["counts"]["users"] == 2


async def test_members_403_guests_401(world, make_client):
    assert (await (await signed_in(make_client, "member_a")).get("/admin/overview")).status_code == 403
    assert (await make_client().get("/admin/overview")).status_code == 401
