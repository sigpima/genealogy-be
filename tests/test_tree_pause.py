"""Superadmin console: pausing a family stops every door into it; resuming restores them all."""

import datetime
import io

import pytest
from PIL import Image
from sqlalchemy import text

from app.core.tenants import create_tree, create_user
from app.jobs.reminders import send_due_reminders
from tests.test_roles_auth import PASSWORD, login, set_setting


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    for key, role, tree in [("admin_a", "admin", tree_a), ("member_a", "member", tree_a), ("admin_b", "admin", tree_b), ("member_b", "member", tree_b)]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    await set_setting(session, "visibility", "public", tree_id=tree_a.id)
    return {"a": tree_a, "b": tree_b, "session": session}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


@pytest.fixture
async def doors(world, make_client):
    """Everything a family exposes, created while it is active: a member with a photo, the .ics feed, an invitation, an event for tomorrow."""
    admin = await signed_in(make_client, "admin_a")
    member = await signed_in(make_client, "member_a")
    to = (await admin.post("/members", json={"full_name": "Tổ", "birth_year": 1900})).json()["id"]
    buffer = io.BytesIO()
    Image.new("RGB", (60, 60), "teal").save(buffer, "PNG")
    avatar = (await admin.post(f"/members/{to}/avatar", files={"file": ("a.png", buffer.getvalue(), "image/png")})).json()["avatar_url"]
    feed = (await admin.post("/calendar/subscription")).json()["path"]
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    event = (await admin.post("/events", json={"title": "Giỗ", "kind": "memorial", "calendar": "solar", "month": tomorrow.month, "day": tomorrow.day, "year": tomorrow.year})).json()
    card = (await admin.post(f"/events/{event['id']}/cards", json={"date": tomorrow.isoformat()})).json()
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    return {"admin": admin, "member": member, "guest": guest, "avatar": avatar, "feed": feed, "token": card["token"], "tomorrow": tomorrow, "mk": make_client}


async def probe(world, d):
    """Status of every door right now."""
    make_client = d["mk"]
    session = world["session"]
    fresh_login = (await make_client().post("/auth/login", json={"email": "admin_a@example.com", "password": PASSWORD})).status_code
    await session.execute(text("DELETE FROM notifications"))
    await session.commit()
    await send_due_reminders(session, d["tomorrow"] - datetime.timedelta(days=1))
    reminded = (await session.execute(text(f"SELECT count(*) FROM notifications WHERE tree_id = {world['a'].id}"))).scalar_one()
    return {
        "login": fresh_login,
        "existing_session": (await d["member"].get("/members/tree")).status_code,
        "guest_tree": (await d["guest"].get("/members/tree")).status_code,
        "feed": (await make_client().get(d["feed"])).status_code,
        "invitation": (await make_client().get(f"/invitations/{d['token']}")).status_code,
        "respond": (await make_client().post(f"/invitations/{d['token']}/respond", json={"name": "Khách", "response": "yes"})).status_code,
        "guest_avatar": (await d["guest"].get(d["avatar"])).status_code,
        "reminders_created": reminded,
    }


async def test_pausing_stops_every_door_and_resuming_restores_them(world, doors, make_client):
    root = await signed_in(make_client, "root")
    before = await probe(world, doors)
    assert before["login"] == 200 and before["existing_session"] == 200 and before["guest_tree"] == 200
    assert before["feed"] == 200 and before["invitation"] == 200 and before["guest_avatar"] == 200 and before["reminders_created"] > 0

    paused = await root.post(f"/trees/{world['a'].id}/pause")
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    during = await probe(world, doors)
    assert during["login"] == 403 and during["existing_session"] == 403
    assert during["guest_tree"] in (401, 404)
    assert during["feed"] == 404 and during["invitation"] == 404 and during["respond"] == 404 and during["guest_avatar"] == 404
    assert during["reminders_created"] == 0

    resumed = await root.post(f"/trees/{world['a'].id}/resume")
    assert resumed.status_code == 200 and resumed.json()["status"] == "active"
    after = await probe(world, doors)
    assert {k: v for k, v in after.items() if k != "respond"} == {k: v for k, v in before.items() if k != "respond"}
    assert after["respond"] in (200, 201)


async def test_the_login_refusal_says_why(world, make_client):
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    r = await make_client().post("/auth/login", json={"email": "member_a@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["detail"] == "tree_paused"


async def test_other_trees_are_not_affected(world, make_client):
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    assert (await login(make_client(), "admin_b@example.com")).status_code == 200


async def test_the_superadmin_can_still_look_at_and_act_on_a_paused_tree(world, doors, make_client):
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    assert (await root.get("/members/tree", headers={"X-Tree-Id": str(world["a"].id)})).status_code == 200
    listed = {t["name"]: t for t in (await root.get("/trees")).json()}
    assert listed["Họ A"]["status"] == "paused" and listed["Họ B"]["status"] == "active"


async def test_pause_and_resume_rules_and_log(world, make_client):
    root = await signed_in(make_client, "root")
    assert (await root.post(f"/trees/{world['a'].id}/resume")).status_code == 409  # not paused
    assert (await root.post(f"/trees/{world['a'].id}/pause")).status_code == 200
    assert (await root.post(f"/trees/{world['a'].id}/pause")).status_code == 409  # already paused
    assert (await root.post("/trees/9999/pause")).status_code == 404
    assert (await (await signed_in(make_client, "admin_b")).post(f"/trees/{world['b'].id}/pause")).status_code == 403
    assert (await make_client().post(f"/trees/{world['a'].id}/pause")).status_code == 401
    await root.post(f"/trees/{world['a'].id}/resume")
    rows = (await world["session"].execute(text("SELECT action, tree_name FROM platform_events WHERE action IN ('tree.pause','tree.resume') ORDER BY id"))).all()
    assert [r[0] for r in rows] == ["tree.pause", "tree.resume"] and rows[0][1] == "Họ A"


async def test_the_overview_reminds_about_paused_trees(world, make_client):
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['b'].id}/pause")
    body = (await root.get("/platform/overview")).json()
    items = {i["key"]: i for i in body["items"]}
    assert items["trees_paused"]["count"] == 1 and items["trees_paused"]["text"] == "1 họ đang tạm ngưng"
    assert body["numbers"]["trees_paused"] == 1
