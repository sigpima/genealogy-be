"""The family's change log says who acted (and whether that was the platform owner), and can be narrowed to one person."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_gd2_members import add
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    a = await create_tree(session, "Họ A", "ho-a")
    b = await create_tree(session, "Họ B", "ho-b")
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    await create_user(session, email="admin_a@example.com", full_name="An Admin", password=PASSWORD, role="admin", tree=a)
    await create_user(session, email="admin_b@example.com", full_name="Bình Admin", password=PASSWORD, role="admin", tree=b)
    return {"a": a, "b": b}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def as_superadmin_in(c, tree, method, path, **kw):
    return await c.request(method, path, headers={"X-Tree-Id": str(tree.id)}, **kw)


async def test_entries_carry_the_role_of_whoever_acted(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    root = await signed_in(make_client, "root")
    await add(admin, "Tổ")
    r = await as_superadmin_in(root, world["a"], "POST", "/members", json={"full_name": "Do hệ thống thêm"})
    assert r.status_code == 201
    items = (await admin.get("/audit")).json()["items"]
    roles = {i["actor_name"]: i["actor_role"] for i in items}
    assert roles == {"An Admin": "admin", "Root": "superadmin"}


async def test_the_family_admin_sees_only_what_touched_their_own_data(world, make_client):
    admin_a = await signed_in(make_client, "admin_a")
    admin_b = await signed_in(make_client, "admin_b")
    root = await signed_in(make_client, "root")
    await add(admin_b, "Người họ B")
    await as_superadmin_in(root, world["b"], "POST", "/members", json={"full_name": "Root sửa họ B"})
    assert (await admin_a.get("/audit")).json()["total"] == 0


async def test_it_can_be_narrowed_to_one_person(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    root = await signed_in(make_client, "root")
    await add(admin, "Tổ")
    await as_superadmin_in(root, world["a"], "POST", "/members", json={"full_name": "Con"})
    ids = {a["name"]: a["id"] for a in (await admin.get("/audit/actors")).json()}
    only_root = (await admin.get("/audit", params={"actor_id": ids["Root"]})).json()
    assert only_root["total"] == 1 and {i["actor_name"] for i in only_root["items"]} == {"Root"}
    only_admin = (await admin.get("/audit", params={"actor_id": ids["An Admin"]})).json()
    assert only_admin["total"] == 1 and only_admin["items"][0]["actor_name"] == "An Admin"


async def test_the_list_of_actors_is_this_familys_and_names_the_roles(world, make_client):
    admin_a = await signed_in(make_client, "admin_a")
    admin_b = await signed_in(make_client, "admin_b")
    await add(admin_a, "Tổ A")
    await add(admin_b, "Tổ B")
    actors = (await admin_a.get("/audit/actors")).json()
    assert actors == [{"id": actors[0]["id"], "name": "An Admin", "role": "admin"}]


async def test_members_cannot_read_the_log_or_its_actors(world, make_client, session, tree):
    await create_user(session, email="m@example.com", full_name="M", password=PASSWORD, role="member", tree=world["a"])
    member = await signed_in(make_client, "m")
    assert (await member.get("/audit/actors")).status_code == 403
