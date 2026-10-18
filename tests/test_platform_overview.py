"""Superadmin console: the platform overview, the platform log and a family's last activity."""

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
    return {"tree_a": tree_a, "tree_b": tree_b, "session": session}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def overview(c):
    r = await c.get("/platform/overview")
    assert r.status_code == 200, r.text
    return r.json()


async def events(session):
    rows = (await session.execute(text("SELECT action, tree_name, details, actor_name FROM platform_events ORDER BY id"))).all()
    return [{"action": a, "tree_name": t, "details": d, "actor_name": n} for a, t, d, n in rows]


async def test_numbers_count_everything_across_trees(world, make_client):
    admin_a = await signed_in(make_client, "admin_a")
    await admin_a.post("/members", json={"full_name": "Tổ"})
    root = await signed_in(make_client, "root")
    numbers = (await overview(root))["numbers"]
    assert numbers == {"trees": 2, "trees_paused": 0, "members": 1, "users": 3, "media_bytes": 0}


async def test_a_tree_without_an_active_admin_is_a_task(world, make_client):
    await world["session"].execute(text("UPDATE users SET status='disabled' WHERE email='admin_b@example.com'"))
    await world["session"].commit()
    items = {i["key"]: i for i in (await overview(await signed_in(make_client, "root")))["items"]}
    item = items["trees_without_admin"]
    assert item["count"] == 1 and item["kind"] == "task"
    assert item["text"] == "1 họ không có quản trị viên đang hoạt động" and item["href"] == "/he-thong/ho?loc=khong-admin"


async def test_no_task_when_every_tree_has_an_active_admin(world, make_client):
    body = await overview(await signed_in(make_client, "root"))
    assert [i for i in body["items"] if i["kind"] == "task"] == []


async def test_tree_create_and_rename_write_platform_events_without_secrets(world, make_client):
    root = await signed_in(make_client, "root")
    created = await root.post("/trees", json={"name": "Họ C", "slug": "ho-c", "admin_email": "c@example.com", "admin_name": "C"})
    assert created.status_code == 201
    password = created.json()["admin_password"]
    tree_id = created.json()["tree"]["id"]
    assert (await root.patch(f"/trees/{tree_id}", json={"name": "Họ C mới"})).status_code == 200
    rows = await events(world["session"])
    assert [r["action"] for r in rows] == ["tree.create", "tree.update"]
    assert rows[0]["tree_name"] == "Họ C" and rows[0]["details"] == {"slug": "ho-c", "admin_email": "c@example.com"}
    assert rows[1]["details"]["changes"] == {"name": ["Họ C", "Họ C mới"]} and rows[1]["actor_name"] == "Root"
    assert password not in str(rows)


async def test_last_activity_is_the_latest_of_audit_and_login(world, make_client):
    root = await signed_in(make_client, "root")
    admin_a = await signed_in(make_client, "admin_a")  # a login of tree A's admin
    await admin_a.post("/members", json={"full_name": "Tổ"})  # and an audit entry
    by_name = {t["name"]: t for t in (await root.get("/trees")).json()}
    assert by_name["Họ A"]["last_activity"] is not None and by_name["Họ B"]["last_activity"] is None
    before = by_name["Họ A"]["last_activity"]
    await admin_a.post("/members", json={"full_name": "Con", "parent_id": 1})
    after = {t["name"]: t for t in (await root.get("/trees")).json()}["Họ A"]["last_activity"]
    assert after > before  # a newer audit entry moves it forward
    await signed_in(make_client, "admin_b")  # a login alone counts for tree B
    assert {t["name"]: t for t in (await root.get("/trees")).json()}["Họ B"]["last_activity"] is not None


async def test_last_activity_is_empty_for_a_tree_nobody_has_touched(world, make_client):
    root = await signed_in(make_client, "root")  # the superadmin has no tree, so this touches neither
    by_name = {t["name"]: t for t in (await root.get("/trees")).json()}
    assert by_name["Họ A"]["last_activity"] is None and by_name["Họ B"]["last_activity"] is None


async def test_only_the_superadmin_may_read(world, make_client):
    assert (await (await signed_in(make_client, "admin_a")).get("/platform/overview")).status_code == 403
    assert (await (await signed_in(make_client, "member_a")).get("/platform/overview")).status_code == 403
    assert (await make_client().get("/platform/overview")).status_code == 401
