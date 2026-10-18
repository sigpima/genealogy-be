"""Admin console: the user jobs (search, bulk approve, password reset, link to a person, last login, audit)."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


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


async def users(c, **params):
    r = await c.get("/admin/users", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def entry(rows, email):
    return next(u for u in rows if u["email"] == email)


async def audit_actions(c):
    body = (await c.get("/audit", params={"limit": 200})).json()
    return body["items"]


async def test_login_sets_last_login_at(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    assert entry(await users(admin), "member_a@example.com")["last_login_at"] is None
    await signed_in(make_client, "member_a")
    assert entry(await users(admin), "member_a@example.com")["last_login_at"] is not None


async def test_list_filters_by_status_role_and_folded_query(world, make_client):
    session = world["session"]
    await create_user(session, email="hoa@example.com", full_name="Nguyễn Thị Hoa", password=PASSWORD, role="member", tree=world["tree_a"], status="pending")
    admin = await signed_in(make_client, "admin_a")
    assert [u["email"] for u in await users(admin, q="nguyen")] == ["hoa@example.com"]
    assert [u["email"] for u in await users(admin, q="HOA@")] == ["hoa@example.com"]
    assert [u["email"] for u in await users(admin, status="pending")] == ["hoa@example.com"]
    assert {u["email"] for u in await users(admin, role="admin")} == {"admin_a@example.com"}
    assert (await admin.get("/admin/users", params={"status": "bogus"})).status_code == 422


async def test_bulk_approve_only_pending_users_of_this_tree(world, make_client):
    session = world["session"]
    mine = await create_user(session, email="mine@example.com", full_name="Mine", password=PASSWORD, role="member", tree=world["tree_a"], status="pending")
    theirs = await create_user(session, email="theirs@example.com", full_name="Theirs", password=PASSWORD, role="member", tree=world["tree_b"], status="pending")
    admin = await signed_in(make_client, "admin_a")
    active_id = entry(await users(admin), "member_a@example.com")["id"]
    r = await admin.post("/admin/users/approve", json={"ids": [mine.id, active_id, theirs.id, 9999]})
    assert r.status_code == 200 and r.json() == {"approved": [mine.id]}
    assert entry(await users(admin), "mine@example.com")["status"] == "active"
    admin_b = await signed_in(make_client, "admin_b")
    assert entry(await users(admin_b), "theirs@example.com")["status"] == "pending"
    kinds = [(e["action"], e["details"] and e["details"].get("email")) for e in await audit_actions(admin)]
    assert ("user.approve", "mine@example.com") in kinds
    assert (await admin.post("/admin/users/approve", json={"ids": []})).status_code == 422


async def test_role_and_status_changes_and_creation_are_audited(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    member_id = entry(await users(admin), "member_a@example.com")["id"]
    assert (await admin.patch(f"/admin/users/{member_id}", json={"role": "admin"})).status_code == 200
    assert (await admin.patch(f"/admin/users/{member_id}", json={"status": "disabled"})).status_code == 200
    created = await admin.post("/admin/users", json={"email": "new@example.com", "full_name": "Mới", "password": PASSWORD, "role": "member"})
    assert created.status_code == 201
    rows = await audit_actions(admin)
    changes = [e["changes"] for e in rows if e["action"] == "user.update"]
    assert {"role": ["member", "admin"]} in changes and {"status": ["active", "disabled"]} in changes
    assert any(e["action"] == "user.create" and e["details"]["email"] == "new@example.com" for e in rows)


async def test_the_last_active_admin_cannot_be_demoted_or_disabled(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    me = entry(await users(admin), "admin_a@example.com")["id"]
    assert (await admin.patch(f"/admin/users/{me}", json={"role": "member"})).status_code == 409
    assert (await admin.patch(f"/admin/users/{me}", json={"status": "disabled"})).status_code == 409


async def test_password_reset_returns_the_password_once_and_it_works(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    member_id = entry(await users(admin), "member_a@example.com")["id"]
    r = await admin.post(f"/admin/users/{member_id}/password", json={})
    assert r.status_code == 200
    new = r.json()["password"]
    assert len(new) >= 8
    assert (await login(make_client(), "member_a@example.com", PASSWORD)).status_code == 401
    assert (await login(make_client(), "member_a@example.com", new)).status_code == 200
    again = (await admin.post(f"/admin/users/{member_id}/password", json={"password": "nhap-tay-123"})).json()
    assert again == {"password": "nhap-tay-123"}
    assert (await login(make_client(), "member_a@example.com", "nhap-tay-123")).status_code == 200
    assert (await admin.post(f"/admin/users/{member_id}/password", json={"password": "short"})).status_code == 422


async def test_password_reset_is_audited_without_the_password(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    member_id = entry(await users(admin), "member_a@example.com")["id"]
    new = (await admin.post(f"/admin/users/{member_id}/password", json={"password": "bi-mat-123456"})).json()["password"]
    rows = await audit_actions(admin)
    reset = [e for e in rows if e["action"] == "user.password_reset"]
    assert len(reset) == 1 and reset[0]["details"]["email"] == "member_a@example.com"
    assert new not in str(rows)


async def test_password_reset_refuses_superadmin_other_trees_and_unknown(world, make_client):
    session = world["session"]
    root = await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    admin = await signed_in(make_client, "admin_a")
    admin_b = await signed_in(make_client, "admin_b")
    b_id = entry(await users(admin_b), "admin_b@example.com")["id"]
    for target in (root.id, b_id, 9999):
        assert (await admin.post(f"/admin/users/{target}/password", json={})).status_code == 404
    assert (await login(make_client(), "root@example.com", PASSWORD)).status_code == 200  # untouched


async def test_link_a_user_to_a_person_of_the_same_tree(world, make_client):
    session = world["session"]
    admin = await signed_in(make_client, "admin_a")
    admin_b = await signed_in(make_client, "admin_b")
    person = (await admin.post("/members", json={"full_name": "Nguyễn Văn Anh", "birth_year": 1950})).json()["id"]
    foreign = (await admin_b.post("/members", json={"full_name": "Người họ B"})).json()["id"]
    member_id = entry(await users(admin), "member_a@example.com")["id"]
    other = await create_user(session, email="o@example.com", full_name="O", password=PASSWORD, role="member", tree=world["tree_a"])
    linked = await admin.patch(f"/admin/users/{member_id}", json={"member_id": person})
    assert linked.status_code == 200 and linked.json()["member"] == {"id": person, "name": "Nguyễn Văn Anh"}
    assert (await admin.patch(f"/admin/users/{member_id}", json={"role": "member"})).json()["member"]["id"] == person  # omitted = unchanged
    assert (await admin.patch(f"/admin/users/{member_id}", json={"member_id": foreign})).status_code == 404
    assert (await admin.patch(f"/admin/users/{other.id}", json={"member_id": person})).status_code == 409
    unlinked = await admin.patch(f"/admin/users/{member_id}", json={"member_id": None})
    assert unlinked.status_code == 200 and unlinked.json()["member"] is None
    assert any(e["action"] == "user.update" and "member_id" in (e["changes"] or {}) for e in await audit_actions(admin))


async def test_deleting_a_linked_person_clears_the_link_and_the_list_still_loads(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    person = (await admin.post("/members", json={"full_name": "Lẻ loi"})).json()["id"]
    member_id = entry(await users(admin), "member_a@example.com")["id"]
    assert (await admin.patch(f"/admin/users/{member_id}", json={"member_id": person})).status_code == 200
    assert (await admin.delete(f"/members/{person}")).status_code == 204
    assert entry(await users(admin), "member_a@example.com")["member"] is None


async def test_members_403_and_guests_401(world, make_client):
    member = await signed_in(make_client, "member_a")
    guest = make_client()
    for c, code in ((member, 403), (guest, 401)):
        assert (await c.get("/admin/users")).status_code == code
        assert (await c.post("/admin/users/approve", json={"ids": [1]})).status_code == code
        assert (await c.post("/admin/users/1/password", json={})).status_code == code
