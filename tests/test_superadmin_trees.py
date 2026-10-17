"""Superadmin: list/create/rename families, and choose which family to act on (header or cookie)."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [
        ("root", "superadmin", None),
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


# ------------------------------------------------------------------ who may use it


async def test_only_the_superadmin_may_manage_trees(world, make_client):
    for who in ("admin_a", "member_a"):
        c = await signed_in(make_client, who)
        assert (await c.get("/trees")).status_code == 403
        assert (await c.post("/trees", json={})).status_code in (403, 422) and (
            await c.post("/trees", json={"name": "x", "slug": "x", "admin_email": "x@example.com", "admin_name": "X"})
        ).status_code == 403
        assert (await c.patch(f"/trees/{world['tree_a'].id}", json={"name": "Hack"})).status_code == 403
    assert (await make_client().get("/trees")).status_code == 401


# ------------------------------------------------------------------ list


async def test_list_shows_counts_and_admins(world, make_client):
    admin_a = await signed_in(make_client, "admin_a")
    await admin_a.post("/members", json={"full_name": "Gốc A"})
    root = await signed_in(make_client, "root")
    rows = (await root.get("/trees")).json()
    assert [r["slug"] for r in rows] == ["ho-a", "ho-b"]
    a = rows[0]
    assert a["name"] == "Họ A" and a["member_count"] == 1 and a["user_count"] == 2
    assert [u["email"] for u in a["admins"]] == ["admin_a@example.com"]
    assert rows[1]["member_count"] == 0


async def test_is_current_follows_header_then_cookie_then_lowest(world, make_client):
    root = await signed_in(make_client, "root")
    current = lambda rows: [r["slug"] for r in rows if r["is_current"]]  # noqa: E731
    assert current((await root.get("/trees")).json()) == ["ho-a"]
    root.cookies.set("acting_tree", str(world["tree_b"].id))
    assert current((await root.get("/trees")).json()) == ["ho-b"]
    header = {"X-Tree-Id": str(world["tree_a"].id)}
    assert current((await root.get("/trees", headers=header)).json()) == ["ho-a"]


# ------------------------------------------------------------------ acting tree cookie


async def test_the_cookie_moves_a_superadmin_between_trees(world, make_client):
    admin_b = await signed_in(make_client, "admin_b")
    await admin_b.post("/members", json={"full_name": "Gốc B"})
    root = await signed_in(make_client, "root")
    assert (await root.get("/members/tree")).json() is None  # lowest tree (A) is empty
    root.cookies.set("acting_tree", str(world["tree_b"].id))
    assert (await root.get("/members/tree")).json()["name"] == "Gốc B"
    # the header still wins over the cookie
    assert (await root.get("/members/tree", headers={"X-Tree-Id": str(world["tree_a"].id)})).json() is None


async def test_a_bad_cookie_is_ignored_for_the_superadmin(world, make_client):
    root = await signed_in(make_client, "root")
    for value in ("abc", "99999", ""):
        root.cookies.set("acting_tree", value)
        assert (await root.get("/members/tree")).status_code == 200, value


async def test_the_cookie_never_moves_anyone_else(world, make_client):
    admin_b = await signed_in(make_client, "admin_b")
    await admin_b.post("/members", json={"full_name": "Gốc B"})
    admin_a = await signed_in(make_client, "admin_a")
    admin_a.cookies.set("acting_tree", str(world["tree_b"].id))
    assert (await admin_a.get("/members/tree")).json() is None


# ------------------------------------------------------------------ create


NEW = {"name": "Họ Mới", "slug": "ho-moi", "admin_email": "new.admin@example.com", "admin_name": "Admin Mới"}


async def test_create_tree_with_its_admin_and_a_generated_password(world, make_client):
    root = await signed_in(make_client, "root")
    response = await root.post("/trees", json=NEW)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["tree"]["slug"] == "ho-moi" and body["tree"]["name"] == "Họ Mới"
    assert body["admin"]["email"] == "new.admin@example.com" and body["admin"]["status"] == "active"
    assert [a["email"] for a in body["tree"]["admins"]] == ["new.admin@example.com"]
    password = body["admin_password"]
    assert password and len(password) >= 8
    new_admin = make_client()
    assert (await login(new_admin, "new.admin@example.com", password)).status_code == 200
    assert (await new_admin.get("/members/tree")).json() is None  # an empty tree of its own
    me = (await new_admin.get("/auth/me")).json()
    assert me["tree_name"] == "Họ Mới" and me["role"] == "admin" and me["tree_id"] == body["tree"]["id"]


async def test_a_given_password_is_not_echoed_back(world, make_client):
    root = await signed_in(make_client, "root")
    body = (await root.post("/trees", json={**NEW, "admin_password": "my-own-password"})).json()
    assert body["admin_password"] is None
    assert (await login(make_client(), "new.admin@example.com", "my-own-password")).status_code == 200


async def test_create_validates_and_is_all_or_nothing(world, make_client):
    root = await signed_in(make_client, "root")
    assert (await root.post("/trees", json={**NEW, "slug": "Bad Slug"})).status_code == 422
    assert (await root.post("/trees", json={**NEW, "name": "  "})).status_code == 422
    assert (await root.post("/trees", json={**NEW, "admin_email": "not-an-email"})).status_code == 422
    assert (await root.post("/trees", json={**NEW, "admin_password": "short"})).status_code == 422
    assert (await root.post("/trees", json={**NEW, "slug": "ho-a"})).status_code == 409
    clash = await root.post("/trees", json={**NEW, "admin_email": "admin_a@example.com"})
    assert clash.status_code == 409
    slugs = [r["slug"] for r in (await root.get("/trees")).json()]
    assert slugs == ["ho-a", "ho-b"]  # the failed attempts left nothing behind


# ------------------------------------------------------------------ rename


async def test_rename_changes_name_and_slug(world, make_client):
    root = await signed_in(make_client, "root")
    tree_id = world["tree_b"].id
    response = await root.patch(f"/trees/{tree_id}", json={"name": "Họ B mới", "slug": "ho-b-moi"})
    assert response.status_code == 200 and response.json()["slug"] == "ho-b-moi"
    assert (await root.patch(f"/trees/{tree_id}", json={"name": "Chỉ đổi tên"})).json()["slug"] == "ho-b-moi"
    assert (await root.patch(f"/trees/{tree_id}", json={"slug": "ho-a"})).status_code == 409
    assert (await root.patch(f"/trees/{tree_id}", json={"slug": "Bad Slug"})).status_code == 422
    assert (await root.patch(f"/trees/{tree_id}", json={"name": " "})).status_code == 422
    assert (await root.patch("/trees/99999", json={"name": "x"})).status_code == 404
