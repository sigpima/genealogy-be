"""Invitation links, admin side: one link per person, the token is shown once, only its hash is stored."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.tenants import create_tree, create_user
from tests.test_gd2_members import add
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    a = await create_tree(session, "Họ A", "ho-a")
    b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [("admin_a", "admin", a), ("member_a", "member", a), ("admin_b", "admin", b)]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"a": a, "b": b}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


@pytest.fixture
async def admin(world, make_client):
    return await signed_in(make_client, "admin_a")


async def test_admin_creates_a_link_and_only_the_hash_is_stored(admin, session):
    person = await add(admin, "Nguyễn Văn B")
    r = await admin.post(f"/members/{person}/invitation")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["path"].startswith("/moi/")
    token = body["path"].removeprefix("/moi/")
    assert len(token) >= 32
    rows = (await session.execute(text("SELECT * FROM member_invites"))).mappings().all()
    assert len(rows) == 1
    assert token not in " ".join(str(v) for v in rows[0].values())
    assert len(rows[0]["token_hash"]) == 64
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(days=13) < expires.replace(tzinfo=None) - datetime.now(timezone.utc).replace(tzinfo=None) <= timedelta(days=14, minutes=1)


async def test_a_new_link_for_the_same_person_revokes_the_old_one(admin):
    person = await add(admin, "Nguyễn Văn B")
    first = (await admin.post(f"/members/{person}/invitation")).json()
    await admin.post(f"/members/{person}/invitation")
    rows = (await admin.get("/admin/invitations")).json()
    assert [r["status"] for r in sorted(rows, key=lambda r: r["id"])] == ["revoked", "pending"]
    assert first["id"] == min(r["id"] for r in rows)


async def test_a_person_who_already_has_an_account_cannot_be_invited(admin, session, world):
    person = await add(admin, "Nguyễn Văn B")
    await session.execute(text("UPDATE users SET member_id = :m WHERE email = 'member_a@example.com'"), {"m": person})
    await session.commit()
    assert (await admin.post(f"/members/{person}/invitation")).status_code == 409


async def test_another_trees_person_is_404(admin, world, make_client):
    other = await signed_in(make_client, "admin_b")
    theirs = await add(other, "Người họ B")
    assert (await admin.post(f"/members/{theirs}/invitation")).status_code == 404


async def test_members_and_guests_cannot_invite(world, admin, make_client):
    person = await add(admin, "Nguyễn Văn B")
    member = await signed_in(make_client, "member_a")
    assert (await member.post(f"/members/{person}/invitation")).status_code == 403
    assert (await make_client().post(f"/members/{person}/invitation")).status_code in (401, 403)
    assert (await member.get("/admin/invitations")).status_code == 403


async def test_the_list_shows_statuses_and_only_this_trees_invites(admin, session, world, make_client):
    p1, p2, p3 = await add(admin, "Một"), await add(admin, "Hai"), await add(admin, "Ba")
    await admin.post(f"/members/{p1}/invitation")
    expired = (await admin.post(f"/members/{p2}/invitation")).json()
    revoked = (await admin.post(f"/members/{p3}/invitation")).json()
    await session.execute(text("UPDATE member_invites SET expires_at = :t WHERE id = :i"), {"t": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1), "i": expired["id"]})
    await session.commit()
    assert (await admin.delete(f"/invitations/{revoked['id']}")).status_code == 204
    other = await signed_in(make_client, "admin_b")
    await other.post(f"/members/{await add(other, 'Họ B')}/invitation")
    rows = (await admin.get("/admin/invitations")).json()
    assert {r["member"]["name"]: r["status"] for r in rows} == {"Một": "pending", "Hai": "expired", "Ba": "revoked"}
    assert all(r["used_by_email"] is None for r in rows)


async def test_revoking_is_idempotent_and_tree_scoped(admin, world, make_client):
    person = await add(admin, "Một")
    inv = (await admin.post(f"/members/{person}/invitation")).json()
    assert (await admin.delete(f"/invitations/{inv['id']}")).status_code == 204
    assert (await admin.delete(f"/invitations/{inv['id']}")).status_code == 204
    other = await signed_in(make_client, "admin_b")
    assert (await other.delete(f"/invitations/{inv['id']}")).status_code == 404


async def test_creating_and_revoking_are_audited_without_the_token(admin):
    person = await add(admin, "Một")
    inv = (await admin.post(f"/members/{person}/invitation")).json()
    await admin.delete(f"/invitations/{inv['id']}")
    log = (await admin.get("/audit", params={"limit": 50})).json()
    items = log["items"] if isinstance(log, dict) else log
    actions = [i["action"] for i in items]
    assert "invite.create" in actions and "invite.revoke" in actions
    token = inv["path"].removeprefix("/moi/")
    assert token not in str(items)
    people = (await admin.get("/audit", params={"kind": "people"})).json()
    people_items = people["items"] if isinstance(people, dict) else people
    assert any(i["action"] == "invite.create" for i in people_items)


async def test_deleting_the_person_removes_their_invitations(admin, session):
    person = await add(admin, "Một")
    await admin.post(f"/members/{person}/invitation")
    assert (await admin.delete(f"/members/{person}")).status_code == 204
    assert (await session.execute(text("SELECT count(*) FROM member_invites"))).scalar_one() == 0
