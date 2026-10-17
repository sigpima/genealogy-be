"""Branches (chi/phái): a branch is the subtree below its head; admin writes, anyone who can read reads."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login, set_setting


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [
        ("admin_a", "admin", tree_a),
        ("member_a", "member", tree_a),
        ("admin_b", "admin", tree_b),
    ]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"tree_a": tree_a, "tree_b": tree_b}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def add(c, name, parent_id=None, **extra):
    r = await c.post("/members", json={"full_name": name, "parent_id": parent_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def family(c):
    """root -> [chi1 -> [c1a -> c1a1, c1b], chi2 -> c2a]"""
    ids = {"root": await add(c, "Tổ")}
    ids["chi1"] = await add(c, "Chi Một", ids["root"])
    ids["chi2"] = await add(c, "Chi Hai", ids["root"])
    ids["c1a"] = await add(c, "C1A", ids["chi1"])
    ids["c1a1"] = await add(c, "C1A1", ids["c1a"])
    ids["c1b"] = await add(c, "C1B", ids["chi1"])
    ids["c2a"] = await add(c, "C2A", ids["chi2"])
    return ids


async def test_create_list_and_counts(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = await family(admin)
    made = await admin.post("/branches", json={"name": "Chi Cả", "root_member_id": ids["chi1"], "description": "Chi trưởng"})
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["name"] == "Chi Cả" and body["root_member_id"] == ids["chi1"] and body["description"] == "Chi trưởng"
    assert body["color"].startswith("#") and len(body["color"]) == 7
    await admin.post("/branches", json={"name": "Nhánh C1A", "root_member_id": ids["c1a"], "color": "#2E7D32"})
    rows = (await admin.get("/branches")).json()
    assert [r["name"] for r in rows] == ["Chi Cả", "Nhánh C1A"]  # by head's generation
    first = rows[0]
    assert first["root_name"] == "Chi Một" and first["root_generation"] == 2
    assert first["member_count"] == 4  # Chi Một, C1A, C1A1, C1B: the whole subtree, sub-branch included
    assert rows[1]["member_count"] == 2 and rows[1]["color"] == "#2e7d32"


async def test_default_colours_differ(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = await family(admin)
    one = (await admin.post("/branches", json={"name": "1", "root_member_id": ids["chi1"]})).json()
    two = (await admin.post("/branches", json={"name": "2", "root_member_id": ids["chi2"]})).json()
    assert one["color"] != two["color"]


async def test_validation_and_conflicts(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = await family(admin)
    ok = {"name": "Chi Cả", "root_member_id": ids["chi1"]}
    assert (await admin.post("/branches", json={**ok, "name": "  "})).status_code == 422
    assert (await admin.post("/branches", json={**ok, "color": "red"})).status_code == 422
    assert (await admin.post("/branches", json={**ok, "root_member_id": 99999})).status_code == 404
    assert (await admin.post("/branches", json=ok)).status_code == 201
    assert (await admin.post("/branches", json={**ok, "name": "Trùng đầu"})).status_code == 409  # head already used


async def test_update_and_delete(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = await family(admin)
    one = (await admin.post("/branches", json={"name": "Chi Cả", "root_member_id": ids["chi1"]})).json()
    two = (await admin.post("/branches", json={"name": "Chi Hai", "root_member_id": ids["chi2"]})).json()
    changed = await admin.put(f"/branches/{one['id']}", json={"name": "Chi Trưởng", "root_member_id": ids["chi1"], "color": "#112233"})
    assert changed.status_code == 200 and changed.json()["name"] == "Chi Trưởng" and changed.json()["description"] is None
    assert (await admin.put(f"/branches/{one['id']}", json={"name": "x", "root_member_id": ids["chi2"]})).status_code == 409
    assert (await admin.put("/branches/99999", json={"name": "x", "root_member_id": ids["chi1"]})).status_code == 404
    assert (await admin.delete(f"/branches/{two['id']}")).status_code == 204
    assert [r["name"] for r in (await admin.get("/branches")).json()] == ["Chi Trưởng"]
    assert (await admin.delete(f"/branches/{two['id']}")).status_code == 404


async def test_deleting_the_head_removes_the_branch(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = await family(admin)
    await admin.post("/branches", json={"name": "Chi lá", "root_member_id": ids["c1b"]})
    assert (await admin.delete(f"/members/{ids['c1b']}")).status_code == 204
    assert (await admin.get("/branches")).json() == []


async def test_members_can_read_but_only_admins_write(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = await family(admin)
    created = (await admin.post("/branches", json={"name": "Chi Cả", "root_member_id": ids["chi1"]})).json()
    member = await signed_in(make_client, "member_a")
    assert len((await member.get("/branches")).json()) == 1
    assert (await member.post("/branches", json={"name": "x", "root_member_id": ids["chi2"]})).status_code == 403
    assert (await member.put(f"/branches/{created['id']}", json={"name": "x", "root_member_id": ids["chi1"]})).status_code == 403
    assert (await member.delete(f"/branches/{created['id']}")).status_code == 403
    assert (await make_client().get("/branches")).status_code == 401


async def test_guests_read_branches_only_on_a_public_tree(world, make_client, session):
    admin = await signed_in(make_client, "admin_a")
    ids = await family(admin)
    await admin.post("/branches", json={"name": "Chi Cả", "root_member_id": ids["chi1"]})
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    assert (await guest.get("/branches")).status_code == 401
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert len((await guest.get("/branches")).json()) == 1


async def test_trees_are_isolated(world, make_client):
    admin_a, admin_b = await signed_in(make_client, "admin_a"), await signed_in(make_client, "admin_b")
    ids = await family(admin_a)
    branch = (await admin_a.post("/branches", json={"name": "Chi Cả", "root_member_id": ids["chi1"]})).json()
    assert (await admin_b.get("/branches")).json() == []
    assert (await admin_b.post("/branches", json={"name": "x", "root_member_id": ids["chi1"]})).status_code == 404
    assert (await admin_b.put(f"/branches/{branch['id']}", json={"name": "x", "root_member_id": ids["chi1"]})).status_code == 404
    assert (await admin_b.delete(f"/branches/{branch['id']}")).status_code == 404


async def test_member_detail_reports_the_deepest_branch(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = await family(admin)
    outer = (await admin.post("/branches", json={"name": "Chi Cả", "root_member_id": ids["chi1"], "color": "#aa0000"})).json()
    inner = (await admin.post("/branches", json={"name": "Nhánh C1A", "root_member_id": ids["c1a"], "color": "#00aa00"})).json()
    branch_of = lambda key: admin.get(f"/members/{ids[key]}")  # noqa: E731
    assert (await branch_of("root")).json()["branch"] is None
    assert (await branch_of("chi1")).json()["branch"] == {"id": outer["id"], "name": "Chi Cả", "color": "#aa0000"}
    assert (await branch_of("c1b")).json()["branch"]["id"] == outer["id"]
    assert (await branch_of("c1a")).json()["branch"]["id"] == inner["id"]
    assert (await branch_of("c1a1")).json()["branch"]["id"] == inner["id"]
    assert (await branch_of("chi2")).json()["branch"] is None
