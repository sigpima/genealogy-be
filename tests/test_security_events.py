"""Admin console: settings changes and failed logins/lockouts in the audit log."""

import pytest

from app.core.rate_limit import limiter
from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree = await create_tree(session, "Họ A", "ho-a")
    for key, role in [("admin_a", "admin"), ("member_a", "member")]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    await create_user(session, email="pending@example.com", full_name="Pending", password=PASSWORD, role="member", tree=tree, status="pending")
    await create_user(session, email="off@example.com", full_name="Off", password=PASSWORD, role="member", tree=tree, status="disabled")
    return tree


@pytest.fixture
def limiter_on():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.enabled = False
    limiter.reset()


async def security_rows(make_client):
    admin = make_client()
    assert (await login(admin, "admin_a@example.com")).status_code == 200
    items = (await admin.get("/audit", params={"limit": 200})).json()["items"]
    return [i for i in items if i["action"].startswith("security.")]


async def bad_login(make_client, email, password="wrong-password"):
    return (await make_client().post("/auth/login", json={"email": email, "password": password})).status_code


async def test_failed_logins_are_recorded_up_to_the_limit_then_one_lock_event(world, make_client, limiter_on):
    codes = [await bad_login(make_client, "member_a@example.com") for _ in range(10)]
    assert codes == [401] * 8 + [429] * 2
    rows = await security_rows(make_client)
    failed = [r for r in rows if r["action"] == "security.login_failed"]
    locked = [r for r in rows if r["action"] == "security.locked"]
    assert len(failed) == 8 and len(locked) == 1
    assert {r["details"]["email"] for r in rows} == {"member_a@example.com"}
    assert sorted(r["details"]["failures"] for r in failed) == list(range(1, 9))


async def test_an_unknown_email_writes_nothing(world, make_client, limiter_on):
    for _ in range(3):
        assert await bad_login(make_client, "nobody@example.com") == 401
    assert await security_rows(make_client) == []


async def test_a_wrong_password_for_a_superadmin_writes_nothing(world, make_client, limiter_on):
    assert await bad_login(make_client, "root@example.com") == 401
    assert await security_rows(make_client) == []


async def test_pending_or_disabled_logins_are_not_failure_events(world, make_client, limiter_on):
    assert await bad_login(make_client, "pending@example.com", PASSWORD) == 403
    assert await bad_login(make_client, "off@example.com", PASSWORD) == 403
    assert await security_rows(make_client) == []


async def test_failures_are_still_recorded_when_the_limiter_is_off(world, make_client):
    assert await bad_login(make_client, "member_a@example.com") == 401
    rows = await security_rows(make_client)
    assert [r["action"] for r in rows] == ["security.login_failed"]


async def test_a_settings_change_is_audited_with_old_and_new_and_a_repeat_is_not(world, make_client):
    admin = make_client()
    assert (await login(admin, "admin_a@example.com")).status_code == 200
    body = {"visibility": "public"}
    assert (await admin.put("/admin/settings", json=body)).status_code == 200
    assert (await admin.put("/admin/settings", json=body)).status_code == 200
    rows = [i for i in (await admin.get("/audit", params={"limit": 50})).json()["items"] if i["action"] == "settings.update"]
    assert len(rows) == 1 and rows[0]["changes"] == {"visibility": ["private", "public"]}
