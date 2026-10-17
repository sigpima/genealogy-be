"""Multi-family isolation: every family has its own tree, admin, users and settings."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login, register


@pytest.fixture
async def world(session):
    """Two families (each with an admin and a member) plus a superadmin."""
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    users = {}
    for key, role, tree in [
        ("root", "superadmin", None),
        ("admin_a", "admin", tree_a),
        ("member_a", "member", tree_a),
        ("admin_b", "admin", tree_b),
        ("member_b", "member", tree_b),
    ]:
        users[key] = await create_user(
            session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree
        )
    return {"tree_a": tree_a, "tree_b": tree_b, **users}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def add_member(c, name, parent_id=None, headers=None, **extra):
    response = await c.post(
        "/members", json={"full_name": name, "parent_id": parent_id, **extra}, headers=headers or {}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ------------------------------------------------------------------ isolation


async def test_a_tree_only_contains_its_own_members(world, make_client):
    admin_a, admin_b = await signed_in(make_client, "admin_a"), await signed_in(make_client, "admin_b")
    await add_member(admin_a, "Root A")
    assert (await admin_a.get("/members/tree")).json()["name"] == "Root A"
    assert (await admin_b.get("/members/tree")).json() is None
    await add_member(admin_b, "Root B")
    assert (await admin_a.get("/members/tree")).json()["name"] == "Root A"
    assert (await admin_b.get("/members/tree")).json()["name"] == "Root B"


async def test_other_trees_member_ids_answer_404_for_every_operation(world, make_client):
    admin_a, admin_b = await signed_in(make_client, "admin_a"), await signed_in(make_client, "admin_b")
    root_a = await add_member(admin_a, "Root A")
    marriage = (await admin_a.post(f"/members/{root_a}/marriages", json={"spouse_full_name": "Spouse A"})).json()

    assert (await admin_b.get(f"/members/{root_a}")).status_code == 404
    assert (await admin_b.put(f"/members/{root_a}", json={"full_name": "Hacked"})).status_code == 404
    assert (await admin_b.delete(f"/members/{root_a}")).status_code == 404
    assert (await admin_b.post("/members", json={"full_name": "Kid", "parent_id": root_a})).status_code == 404
    assert (await admin_b.post(f"/members/{root_a}/marriages", json={"spouse_full_name": "S"})).status_code == 404
    assert (await admin_b.put(f"/members/marriages/{marriage['marriage_id']}", json={"spouse_full_name": "H"})).status_code == 404
    assert (await admin_b.post(f"/members/{root_a}/avatar", files={"file": ("a.png", b"x", "image/png")})).status_code == 404
    assert (await admin_b.delete(f"/members/{root_a}/avatar")).status_code == 404
    # ... and nothing of A changed
    assert (await admin_a.get(f"/members/{root_a}")).status_code == 200
    assert (await admin_a.get("/members/tree")).json()["name"] == "Root A"


async def test_a_member_cannot_be_moved_under_a_parent_from_another_tree(world, make_client):
    admin_a, admin_b = await signed_in(make_client, "admin_a"), await signed_in(make_client, "admin_b")
    root_a = await add_member(admin_a, "Root A")
    root_b = await add_member(admin_b, "Root B")
    kid_b = await add_member(admin_b, "Kid B", root_b)
    response = await admin_b.put(f"/members/{kid_b}", json={"full_name": "Kid B", "parent_id": root_a})
    assert response.status_code == 404


async def test_members_only_read_their_own_tree(world, make_client):
    admin_a = await signed_in(make_client, "admin_a")
    root_a = await add_member(admin_a, "Root A")
    member_a, member_b = await signed_in(make_client, "member_a"), await signed_in(make_client, "member_b")
    assert (await member_a.get(f"/members/{root_a}")).status_code == 200
    assert (await member_b.get(f"/members/{root_a}")).status_code == 404
    assert (await member_b.get("/members/tree")).json() is None


async def test_a_signed_in_user_cannot_switch_tree_with_headers_or_cookies(world, make_client):
    admin_a, admin_b = await signed_in(make_client, "admin_a"), await signed_in(make_client, "admin_b")
    await add_member(admin_a, "Root A")
    await add_member(admin_b, "Root B")
    admin_a.cookies.set("tree_slug", "ho-b")
    sneaky = {"X-Tree-Id": str(world["tree_b"].id), "X-Tree-Slug": "ho-b"}
    assert (await admin_a.get("/members/tree", headers=sneaky)).json()["name"] == "Root A"
    created = await admin_a.post("/members", json={"full_name": "Wrong place"}, headers=sneaky)
    assert created.status_code == 201
    assert (await admin_b.get("/members/tree")).json()["name"] == "Root B"  # B untouched


async def test_a_new_member_lands_in_the_acting_tree(world, make_client, session):
    from sqlalchemy import text

    admin_b = await signed_in(make_client, "admin_b")
    member_id = await add_member(admin_b, "Root B")
    row = (await session.execute(text("SELECT tree_id FROM members WHERE id = :i"), {"i": member_id})).scalar_one()
    assert row == world["tree_b"].id


# ------------------------------------------------------------------ superadmin


async def test_superadmin_defaults_to_the_lowest_id_tree_and_can_pick_another(world, make_client):
    root = await signed_in(make_client, "root")
    admin_a, admin_b = await signed_in(make_client, "admin_a"), await signed_in(make_client, "admin_b")
    await add_member(admin_a, "Root A")
    await add_member(admin_b, "Root B")
    assert (await root.get("/members/tree")).json()["name"] == "Root A"
    picked = {"X-Tree-Id": str(world["tree_b"].id)}
    assert (await root.get("/members/tree", headers=picked)).json()["name"] == "Root B"
    await add_member(root, "Added by root", (await root.get("/members/tree", headers=picked)).json()["id"], headers=picked)
    assert [c["name"] for c in (await admin_b.get("/members/tree")).json()["children"]] == ["Added by root"]


async def test_superadmin_header_for_an_unknown_tree_is_404(world, make_client):
    root = await signed_in(make_client, "root")
    assert (await root.get("/members/tree", headers={"X-Tree-Id": "99999"})).status_code == 404
    assert (await root.get("/members/tree", headers={"X-Tree-Id": "not-a-number"})).status_code == 404


async def test_me_reports_the_tree(world, make_client):
    admin_a, root = await signed_in(make_client, "admin_a"), await signed_in(make_client, "root")
    me = (await admin_a.get("/auth/me")).json()
    assert (me["role"], me["tree_id"], me["tree_name"]) == ("admin", world["tree_a"].id, "Họ A")
    root_me = (await root.get("/auth/me")).json()
    assert (root_me["role"], root_me["tree_id"], root_me["tree_name"]) == ("superadmin", None, None)


# ------------------------------------------------------------ admin API scope


async def test_a_tree_admin_manages_only_their_trees_users(world, make_client):
    admin_a = await signed_in(make_client, "admin_a")
    emails = [u["email"] for u in (await admin_a.get("/admin/users")).json()]
    assert emails == ["admin_a@example.com", "member_a@example.com"]  # no B users, no superadmin

    created = await admin_a.post(
        "/admin/users", json={"email": "new@example.com", "full_name": "New", "password": PASSWORD}
    )
    assert created.status_code == 201
    assert created.json()["tree_id"] == world["tree_a"].id


async def test_a_tree_admin_cannot_touch_other_trees_users_or_the_superadmin(world, make_client):
    admin_a = await signed_in(make_client, "admin_a")
    for other in (world["member_b"], world["admin_b"], world["root"]):
        assert (await admin_a.patch(f"/admin/users/{other.id}", json={"status": "disabled"})).status_code == 404
    assert (await admin_a.patch(f"/admin/users/{world['member_a'].id}", json={"role": "superadmin"})).status_code == 422


async def test_last_admin_guard_is_per_tree(world, make_client):
    admin_a = await signed_in(make_client, "admin_a")  # the only admin of A (B has its own)
    me = (await admin_a.get("/auth/me")).json()
    assert (await admin_a.patch(f"/admin/users/{me['id']}", json={"role": "member"})).status_code == 409
    await admin_a.patch(f"/admin/users/{world['member_a'].id}", json={"role": "admin"})
    assert (await admin_a.patch(f"/admin/users/{me['id']}", json={"role": "member"})).status_code == 200


async def test_settings_are_per_tree(world, make_client):
    admin_a, admin_b = await signed_in(make_client, "admin_a"), await signed_in(make_client, "admin_b")
    await admin_a.put("/admin/settings", json={"visibility": "public", "registration": "closed"})
    assert (await admin_a.get("/admin/settings")).json() == {"visibility": "public", "registration": "closed"}
    assert (await admin_b.get("/admin/settings")).json() == {"visibility": "private", "registration": "approval"}


# ------------------------------------------------------- guests, cookie, signup


async def test_guest_resolution_uses_the_tree_slug_cookie(world, make_client):
    admin_a, admin_b = await signed_in(make_client, "admin_a"), await signed_in(make_client, "admin_b")
    await add_member(admin_a, "Root A")
    await add_member(admin_b, "Root B")
    await admin_a.put("/admin/settings", json={"visibility": "public", "registration": "approval"})

    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    assert (await guest.get("/members/tree")).json()["name"] == "Root A"
    assert (await guest.get("/site/info")).json()["visibility"] == "public"
    assert (await guest.get("/site/info")).json()["tree_name"] == "Họ A"

    guest_b = make_client()
    guest_b.cookies.set("tree_slug", "ho-b")
    assert (await guest_b.get("/members/tree")).status_code == 401  # B is private
    assert (await guest_b.get("/site/info")).json()["visibility"] == "private"


async def test_with_several_trees_a_guest_needs_to_say_which_one(world, make_client):
    guest = make_client()
    # reads answer 401 (so the web app sends the visitor to the login page); /site/info says 404
    assert (await guest.get("/members/tree")).status_code == 401
    assert (await guest.get("/site/info")).status_code == 404
    guest.cookies.set("tree_slug", "does-not-exist")
    assert (await guest.get("/members/tree")).status_code == 401
    assert (await guest.get("/site/info")).status_code == 404


async def test_a_single_tree_needs_no_cookie(client, session):
    await create_tree(session, "Only", "only")
    guest_client = client  # no cookie, one tree
    assert (await guest_client.get("/site/info")).json()["tree_slug"] == "only"


async def test_signup_joins_the_tree_from_the_cookie_with_that_trees_rules(world, make_client):
    admin_b = await signed_in(make_client, "admin_b")
    await admin_b.put("/admin/settings", json={"visibility": "private", "registration": "closed"})

    visitor_a = make_client()
    visitor_a.cookies.set("tree_slug", "ho-a")
    created = await register(visitor_a, "newcomer@example.com")
    assert created.status_code == 201
    assert (created.json()["role"], created.json()["status"], created.json()["tree_id"]) == (
        "member", "pending", world["tree_a"].id,
    )

    visitor_b = make_client()
    visitor_b.cookies.set("tree_slug", "ho-b")
    assert (await register(visitor_b, "late@example.com")).status_code == 403  # B is closed


async def test_signup_without_a_tree_is_refused_when_there_are_several(world, make_client):
    visitor = make_client()
    refused = await register(visitor, "lost@example.com")
    assert refused.status_code == 400
    assert "tree" in refused.json()["detail"]


# -------------------------------------------------------------- bootstrap


async def test_first_user_ever_is_superadmin_and_gets_a_default_tree(client):
    created = await register(client, "first@example.com")
    assert created.json()["role"] == "superadmin"
    assert created.json()["tree_id"] is None
    await login(client, "first@example.com")
    member_id = (await client.post("/members", json={"full_name": "Root"})).json()["id"]
    assert (await client.get("/members/tree")).json()["id"] == member_id
    info = (await client.get("/site/info")).json()
    assert info["tree_slug"] == "default"
