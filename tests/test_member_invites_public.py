"""Invitation links, public side: look at one, accept one, and everything that must NOT work."""

import asyncio
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.invites import utcnow
from app.core.rate_limit import limiter
from app.core.tenants import create_tree, create_user
from tests.test_gd2_members import add
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    a = await create_tree(session, "Họ Nguyễn", "ho-nguyen")
    await create_user(session, email="admin_a@example.com", full_name="Admin A", password=PASSWORD, role="admin", tree=a)
    return a


@pytest.fixture
async def admin(world, make_client):
    c = make_client()
    assert (await login(c, "admin_a@example.com")).status_code == 200
    return c


async def invite(admin, name="Nguyễn Văn B"):
    person = await add(admin, name)
    token = (await admin.post(f"/members/{person}/invitation")).json()["path"].removeprefix("/moi/")
    return person, token


def accept_body(email="b@example.com", **extra):
    return {"email": email, "password": "mat-khau-moi-1", **extra}


async def test_viewing_shows_the_family_and_the_person_only(admin, make_client):
    _, token = await invite(admin)
    r = await make_client().get(f"/invite/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["family"] == "Họ Nguyễn" and body["person"] == "Nguyễn Văn B" and "expires_at" in body
    assert set(body) == {"family", "person", "expires_at"}


async def test_accepting_makes_an_active_member_linked_to_the_person_and_signs_in(admin, make_client, session):
    person, token = await invite(admin)
    c = make_client()
    r = await c.post(f"/invite/{token}/accept", json=accept_body(full_name="Văn B"))
    assert r.status_code == 201, r.text
    user = r.json()
    assert (user["role"], user["status"], user["full_name"]) == ("member", "active", "Văn B")
    me = (await c.get("/auth/me")).json()  # the cookie works at once
    assert me["email"] == "b@example.com" and me["member"] == {"id": person, "name": "Nguyễn Văn B"}
    row = (await session.execute(text("SELECT role, status, tree_id, member_id FROM users WHERE email = 'b@example.com'"))).one()
    assert row.role == "member" and row.status == "active" and row.member_id == person
    status_ = (await admin.get("/admin/invitations")).json()[0]
    assert status_["status"] == "used" and status_["used_by_email"] == "b@example.com"


async def test_the_name_defaults_to_the_persons(admin, make_client):
    _, token = await invite(admin)
    r = await make_client().post(f"/invite/{token}/accept", json=accept_body())
    assert r.json()["full_name"] == "Nguyễn Văn B"


async def test_a_used_link_cannot_be_used_again(admin, make_client):
    _, token = await invite(admin)
    assert (await make_client().post(f"/invite/{token}/accept", json=accept_body())).status_code == 201
    assert (await make_client().post(f"/invite/{token}/accept", json=accept_body("c@example.com"))).status_code == 404
    assert (await make_client().get(f"/invite/{token}")).status_code == 404


async def test_revoked_expired_and_unknown_links_all_look_the_same(admin, make_client, session):
    p1, t1 = await invite(admin, "Một")
    p2, t2 = await invite(admin, "Hai")
    inv = (await admin.get("/admin/invitations")).json()
    revoked_id = next(i["id"] for i in inv if i["member"]["name"] == "Một")
    await admin.delete(f"/invitations/{revoked_id}")
    await session.execute(text("UPDATE member_invites SET expires_at = :t WHERE member_id = :m"), {"t": utcnow() - timedelta(minutes=1), "m": p2})
    await session.commit()
    c = make_client()
    responses = [await c.get(f"/invite/{t}") for t in (t1, t2, "x" * 43)]
    assert {r.status_code for r in responses} == {404}
    assert len({r.text for r in responses}) == 1
    posts = [await c.post(f"/invite/{t}/accept", json=accept_body()) for t in (t1, t2, "x" * 43)]
    assert {r.status_code for r in posts} == {404}


async def test_an_email_already_in_use_is_409_and_the_link_stays_usable(admin, make_client):
    _, token = await invite(admin)
    c = make_client()
    assert (await c.post(f"/invite/{token}/accept", json=accept_body("admin_a@example.com"))).status_code == 409
    assert (await c.post(f"/invite/{token}/accept", json=accept_body("fresh@example.com"))).status_code == 201


async def test_a_short_password_is_422_and_nothing_is_used(admin, make_client):
    _, token = await invite(admin)
    c = make_client()
    assert (await c.post(f"/invite/{token}/accept", json={"email": "b@example.com", "password": "short"})).status_code == 422
    assert (await c.get(f"/invite/{token}")).status_code == 200


async def test_two_people_racing_for_one_link_make_one_account(admin, make_client, session):
    _, token = await invite(admin)
    from app.main import app

    async def go(email):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            return (await c.post(f"/invite/{token}/accept", json=accept_body(email))).status_code

    codes = sorted(await asyncio.gather(go("x@example.com"), go("y@example.com")))
    assert codes == [201, 404]
    assert (await session.execute(text("SELECT count(*) FROM users WHERE email IN ('x@example.com','y@example.com')"))).scalar_one() == 1


async def test_a_person_linked_meanwhile_by_an_admin_is_refused(admin, make_client, session):
    person, token = await invite(admin)
    await session.execute(text("UPDATE users SET member_id = :m WHERE email = 'admin_a@example.com'"), {"m": person})
    await session.commit()
    assert (await make_client().post(f"/invite/{token}/accept", json=accept_body())).status_code == 409


async def test_a_paused_family_closes_its_links(admin, make_client, session, world):
    _, token = await invite(admin)
    await session.execute(text("UPDATE trees SET status = 'paused' WHERE id = :i"), {"i": world.id})
    await session.commit()
    c = make_client()
    assert (await c.get(f"/invite/{token}")).status_code == 404
    assert (await c.post(f"/invite/{token}/accept", json=accept_body())).status_code == 404


async def test_the_door_is_rate_limited(admin, make_client):
    _, token = await invite(admin)
    limiter.enabled = True
    limiter.reset()
    try:
        c = make_client()
        codes = [(await c.get(f"/invite/{'z' * 43}")).status_code for _ in range(200)]
        assert 429 in codes
    finally:
        limiter.enabled = False
        limiter.reset()
