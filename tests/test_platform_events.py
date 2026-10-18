"""Superadmin console: going in to help is logged, and the platform log can be read."""

import datetime

import pytest
from sqlalchemy import text

from app.core import calendar_items
from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    for key, role, tree in [("admin_a", "admin", tree_a), ("admin_b", "admin", tree_b)]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"a": tree_a, "b": tree_b, "session": session}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def listing(c, **params):
    r = await c.get("/platform/events", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_going_in_to_help_is_recorded_with_who_and_which_family(world, make_client):
    root = await signed_in(make_client, "root")
    assert (await root.post(f"/trees/{world['a'].id}/support")).status_code == 204
    rows = (await world["session"].execute(text("SELECT action, tree_id, tree_name, actor_name FROM platform_events"))).all()
    assert rows == [("support.enter", world["a"].id, "Họ A", "Root")]


async def test_support_rules(world, make_client):
    root = await signed_in(make_client, "root")
    assert (await root.post("/trees/9999/support")).status_code == 404
    assert (await (await signed_in(make_client, "admin_a")).post(f"/trees/{world['a'].id}/support")).status_code == 403
    assert (await make_client().post(f"/trees/{world['a'].id}/support")).status_code == 401


async def test_the_log_lists_newest_first_with_a_total(world, make_client):
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    await root.post(f"/trees/{world['a'].id}/resume")
    await root.post(f"/trees/{world['b'].id}/support")
    body = await listing(root)
    assert body["total"] == 3
    assert [i["action"] for i in body["items"]] == ["support.enter", "tree.resume", "tree.pause"]
    assert set(body["items"][0]) == {"id", "action", "actor_name", "tree_id", "tree_name", "details", "created_at"}


async def test_filters_by_action_prefix_family_and_dates(world, make_client):
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    await root.post(f"/trees/{world['b'].id}/support")
    await root.post(f"/trees/{world['a'].id}/support")
    assert {i["action"] for i in (await listing(root, action="tree."))["items"]} == {"tree.pause"}
    assert len((await listing(root, action="support"))["items"]) == 2
    assert {i["tree_name"] for i in (await listing(root, tree_id=world["b"].id))["items"]} == {"Họ B"}
    today = calendar_items.vn_today()
    assert (await listing(root, since=today.isoformat(), until=today.isoformat()))["total"] == 3
    assert (await listing(root, since=(today + datetime.timedelta(days=1)).isoformat()))["total"] == 0
    assert (await listing(root, until=(today - datetime.timedelta(days=1)).isoformat()))["total"] == 0
    assert (await root.get("/platform/events", params={"since": "not-a-date"})).status_code == 422


async def test_paging(world, make_client):
    root = await signed_in(make_client, "root")
    for _ in range(5):
        await root.post(f"/trees/{world['a'].id}/support")
    first = await listing(root, limit=2, offset=0)
    second = await listing(root, limit=2, offset=2)
    assert first["total"] == 5 and len(first["items"]) == 2 and len(second["items"]) == 2
    assert {i["id"] for i in first["items"]}.isdisjoint({i["id"] for i in second["items"]})
    assert (await root.get("/platform/events", params={"limit": 500})).status_code == 422


async def test_no_secret_ever_comes_out_of_the_log(world, make_client):
    root = await signed_in(make_client, "root")
    created = (await root.post("/trees", json={"name": "Họ C", "slug": "ho-c", "admin_email": "c@example.com", "admin_name": "C"})).json()
    password = created["admin_password"]
    assert password
    assert password not in str(await listing(root))


async def test_only_the_superadmin_reads_the_log(world, make_client):
    assert (await (await signed_in(make_client, "admin_a")).get("/platform/events")).status_code == 403
    assert (await make_client().get("/platform/events")).status_code == 401
