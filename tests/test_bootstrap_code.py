"""The first account becomes the superadmin: in production that door is closed with BOOTSTRAP_CODE."""

import pytest

from app.core.config import get_settings
from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD

CODE = "ma-khoi-tao-thu-nghiem"


def use_code(monkeypatch, value=CODE):
    monkeypatch.setenv("BOOTSTRAP_CODE", value)
    get_settings.cache_clear()


async def register(c, code=None, email="chu@example.com"):
    body = {"email": email, "full_name": "Chủ", "password": PASSWORD}
    if code is not None:
        body["bootstrap_code"] = code
    return await c.post("/auth/register", json=body)


async def test_without_a_code_configured_the_first_account_still_becomes_superadmin(make_client):
    r = await register(make_client())
    assert r.status_code == 201 and r.json()["role"] == "superadmin"


async def test_with_a_code_configured_the_first_registration_needs_it(make_client, monkeypatch):
    use_code(monkeypatch)
    c = make_client()
    assert (await register(c)).status_code == 403
    assert (await register(c, "sai-ma")).status_code == 403
    assert (await register(c, "")).status_code == 403
    ok = await register(c, CODE)
    assert ok.status_code == 201 and ok.json()["role"] == "superadmin"
    assert CODE not in ok.text


async def test_a_refused_attempt_creates_nothing(make_client, monkeypatch, session):
    from sqlalchemy import text

    use_code(monkeypatch)
    await register(make_client(), "sai-ma")
    assert (await session.execute(text("SELECT count(*) FROM users"))).scalar_one() == 0
    assert (await session.execute(text("SELECT count(*) FROM trees"))).scalar_one() == 0


async def test_later_registrations_never_need_the_code(make_client, monkeypatch, session):
    tree = await create_tree(session, "Họ A", "ho-a")
    await create_user(session, email="admin@example.com", full_name="Admin", password=PASSWORD, role="admin", tree=tree)
    use_code(monkeypatch)
    r = await register(make_client(), email="hoc@example.com")
    assert r.status_code == 201 and r.json()["role"] == "member"


async def test_the_bootstrap_endpoint_says_what_the_signup_page_must_ask(make_client, monkeypatch, session):
    c = make_client()
    assert (await c.get("/auth/bootstrap")).json() == {"first_user": True, "needs_code": False}
    use_code(monkeypatch)
    assert (await c.get("/auth/bootstrap")).json() == {"first_user": True, "needs_code": True}
    await register(c, CODE)
    assert (await c.get("/auth/bootstrap")).json() == {"first_user": False, "needs_code": False}
    assert CODE not in (await c.get("/auth/bootstrap")).text
