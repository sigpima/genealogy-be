"""/auth/me names the person an account is linked to; an admin links themself without anybody's approval."""

import pytest
from sqlalchemy import text

from app.core.tenants import create_tree, create_user
from tests.test_gd2_members import add
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    a = await create_tree(session, "Họ A", "ho-a")
    b = await create_tree(session, "Họ B", "ho-b")
    await create_user(session, email="admin_a@example.com", full_name="Admin A", password=PASSWORD, role="admin", tree=a)
    await create_user(session, email="member_a@example.com", full_name="Member A", password=PASSWORD, role="member", tree=a)
    await create_user(session, email="admin_b@example.com", full_name="Admin B", password=PASSWORD, role="admin", tree=b)
    return a


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def test_me_has_no_member_when_unlinked(world, make_client):
    c = await signed_in(make_client, "member_a")
    assert (await c.get("/auth/me")).json()["member"] is None


async def test_an_admin_can_link_themself_and_it_is_audited(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    person = await add(admin, "Nguyễn Văn A")
    me = (await admin.get("/auth/me")).json()
    r = await admin.patch(f"/admin/users/{me['id']}", json={"member_id": person})
    assert r.status_code == 200, r.text
    assert (await admin.get("/auth/me")).json()["member"] == {"id": person, "name": "Nguyễn Văn A"}
    log = (await admin.get("/audit", params={"kind": "people"})).json()
    items = log["items"] if isinstance(log, dict) else log
    assert any(i["action"] == "user.update" for i in items)


async def test_linking_is_refused_for_somebody_elses_person_and_for_a_taken_one(world, make_client, session):
    admin = await signed_in(make_client, "admin_a")
    other = await signed_in(make_client, "admin_b")
    theirs = await add(other, "Người họ B")
    mine = await add(admin, "Người họ A")
    me = (await admin.get("/auth/me")).json()
    assert (await admin.patch(f"/admin/users/{me['id']}", json={"member_id": theirs})).status_code == 404
    await session.execute(text("UPDATE users SET member_id = :m WHERE email = 'member_a@example.com'"), {"m": mine})
    await session.commit()
    assert (await admin.patch(f"/admin/users/{me['id']}", json={"member_id": mine})).status_code == 409


async def test_a_member_cannot_link_themself(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    person = await add(admin, "Nguyễn Văn A")
    member = await signed_in(make_client, "member_a")
    me = (await member.get("/auth/me")).json()
    assert (await member.patch(f"/admin/users/{me['id']}", json={"member_id": person})).status_code == 403
