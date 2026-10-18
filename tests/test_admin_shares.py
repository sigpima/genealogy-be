"""Admin console: audit kinds and date filters, the lockout to-do item, share links."""

import datetime

import pytest

from app.core import calendar_items
from app.core.audit_kinds import KINDS
from app.core.rate_limit import limiter
from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [("admin_a", "admin", tree_a), ("member_a", "member", tree_a), ("admin_b", "admin", tree_b)]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"tree_a": tree_a, "tree_b": tree_b}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def audit(c, **params):
    r = await c.get("/audit", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def test_audit_filters_by_kind(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    await admin.post("/members", json={"full_name": "Tổ"})  # member.create -> data
    await admin.post("/admin/users", json={"email": "n@example.com", "full_name": "N", "password": PASSWORD, "role": "member"})  # user.create -> people
    await admin.put("/admin/settings", json={"visibility": "public"})  # settings.update -> settings
    await admin.put("/admin/privacy", json={"phone": "admin"})  # privacy.update -> settings
    for _ in range(2):
        await make_client().post("/auth/login", json={"email": "member_a@example.com", "password": "wrong-password"})  # security.login_failed
    assert {i["action"] for i in await audit(admin, kind="data")} == {"member.create"}
    assert {i["action"] for i in await audit(admin, kind="people")} == {"user.create"}
    assert {i["action"] for i in await audit(admin, kind="settings")} == {"settings.update", "privacy.update"}
    assert {i["action"] for i in await audit(admin, kind="security")} == {"security.login_failed"}
    assert len(await audit(admin)) >= 5  # no kind = everything


async def test_every_known_prefix_belongs_to_exactly_one_kind():
    prefixes = [p for group in KINDS.values() for p in group]
    assert len(prefixes) == len(set(prefixes))
    assert set(KINDS) == {"data", "people", "security", "settings"}


async def test_audit_filters_by_dates_in_vietnam_time_and_rejects_unknown_kinds(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    await admin.post("/members", json={"full_name": "Tổ"})
    today = calendar_items.vn_today()
    tomorrow = today + datetime.timedelta(days=1)
    assert len(await audit(admin, since=today.isoformat(), until=today.isoformat())) == 1
    assert await audit(admin, since=tomorrow.isoformat()) == []
    assert await audit(admin, until=(today - datetime.timedelta(days=1)).isoformat()) == []
    assert (await admin.get("/audit", params={"kind": "bogus"})).status_code == 422
    assert (await admin.get("/audit", params={"since": "not-a-date"})).status_code == 422


async def test_audit_stays_inside_the_tree(world, make_client):
    admin_b = await signed_in(make_client, "admin_b")
    await admin_b.post("/members", json={"full_name": "Người họ B"})
    assert await audit(await signed_in(make_client, "admin_a"), kind="data") == []


async def test_the_overview_counts_recent_lockouts_only(world, make_client, session):
    limiter.enabled = True
    limiter.reset()
    try:
        for _ in range(8):
            await make_client().post("/auth/login", json={"email": "member_a@example.com", "password": "wrong-password"})
    finally:
        limiter.enabled = False
        limiter.reset()
    admin = await signed_in(make_client, "admin_a")
    items = {i["key"]: i for i in (await admin.get("/admin/overview")).json()["items"]}
    assert items["locked_accounts"]["count"] == 1 and items["locked_accounts"]["href"] == "/admin/nhat-ky?loai=security"
    await session.execute(__import__("sqlalchemy").text("UPDATE audit_log SET created_at = now() - interval '2 days' WHERE action = 'security.locked'"))
    await session.commit()
    items = {i["key"]: i for i in (await admin.get("/admin/overview")).json()["items"]}
    assert "locked_accounts" not in items


async def make_card(c, day="2030-03-04"):
    event = (await c.post("/events", json={"title": "Giỗ", "kind": "memorial", "calendar": "solar", "month": 3, "day": 4, "year": 2030})).json()
    r = await c.post(f"/events/{event['id']}/cards", json={"date": day})
    assert r.status_code == 201, r.text
    return r.json()


async def test_open_cards_lists_only_open_cards_of_this_tree(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    open_card = await make_card(admin)
    closed = await make_card(admin)
    assert (await admin.patch(f"/cards/{closed['id']}", json={"closed": True})).status_code == 200
    admin_b = await signed_in(make_client, "admin_b")
    await make_card(admin_b)
    rows = (await admin.get("/cards", params={"open": "true"})).json()
    assert [c["id"] for c in rows] == [open_card["id"]]
    assert len((await admin.get("/cards")).json()) == 2  # without the filter: all of this tree's cards


async def test_shares_reports_the_calendar_link_and_the_open_card_count(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    first = (await admin.get("/admin/shares")).json()
    assert first == {"calendar": {"enabled": False, "path": None}, "open_cards": 0}
    await admin.post("/calendar/subscription")
    await make_card(admin)
    second = (await admin.get("/admin/shares")).json()
    assert second["calendar"]["enabled"] is True and second["calendar"]["path"].startswith("/calendar/feed/")
    assert second["open_cards"] == 1


async def test_members_403_and_guests_401(world, make_client):
    member = await signed_in(make_client, "member_a")
    for c, code in ((member, 403), (make_client(), 401)):
        assert (await c.get("/admin/shares")).status_code == code
        assert (await c.get("/cards")).status_code == code


async def test_calendar_link_actions_leave_audit_lines_without_the_secret(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    first = (await admin.post("/calendar/subscription")).json()["path"]
    second = (await admin.post("/calendar/subscription")).json()["path"]
    assert (await admin.delete("/calendar/subscription")).status_code == 204
    rows = await audit(admin, kind="settings")
    assert [r["action"] for r in rows][::-1] == ["calendar.enable", "calendar.regenerate", "calendar.disable"]
    assert first.split("/")[-1].split(".")[0] not in str(rows) and second.split("/")[-1].split(".")[0] not in str(rows)
