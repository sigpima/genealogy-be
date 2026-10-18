"""Public sign-up is gone: accounts come from the command line (the first superadmin), the superadmin (a family and its admin) and the admin (accounts and invitation links)."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login, make_user


@pytest.fixture
async def world(session):
    tree = await create_tree(session, "Họ A", "ho-a")
    await create_user(session, email="admin_a@example.com", full_name="Admin A", password=PASSWORD, role="admin", tree=tree)
    return tree


async def test_there_is_no_register_and_no_bootstrap_endpoint(client, world):
    body = {"email": "new@example.com", "password": "longenough1", "full_name": "N"}
    assert (await client.post("/auth/register", json=body)).status_code in (404, 405)
    assert (await client.get("/auth/bootstrap")).status_code in (404, 405)
    count = (await client.get("/site/info")).status_code  # still public
    assert count == 200


async def test_the_registration_setting_is_gone(client, world, make_client):
    info = (await client.get("/site/info")).json()
    assert "registration" not in info
    admin = make_client()
    await login(admin, "admin_a@example.com")
    assert "registration" not in (await admin.get("/admin/settings")).json()
    r = await admin.put("/admin/settings", json={"visibility": "public", "registration": "open"})
    assert r.status_code == 200 and "registration" not in r.json()  # an old client's extra key is ignored, not stored


async def test_the_bulk_approve_endpoint_is_gone(client, world, make_client):
    admin = make_client()
    await login(admin, "admin_a@example.com")
    assert (await admin.post("/admin/users/approve", json={"ids": [1]})).status_code in (404, 405)


async def test_an_old_pending_account_can_still_be_approved_one_by_one(client, world, make_client):
    await make_user(client, "old@example.com", "Old", status="pending")
    assert (await login(client, "old@example.com")).status_code == 403
    admin = make_client()
    await login(admin, "admin_a@example.com")
    pending = next(u for u in (await admin.get("/admin/users")).json() if u["email"] == "old@example.com")
    assert (await admin.patch(f"/admin/users/{pending['id']}", json={"status": "active"})).status_code == 200
    assert (await login(client, "old@example.com")).status_code == 200


async def test_the_command_line_makes_the_first_superadmin_on_an_empty_database(client, session):
    """`manage.py create-user --role superadmin` is how a fresh install gets its first account (see DOCKER.md)."""
    from app.cli import run

    out = await run(["create-user", "--email", "owner@example.com", "--name", "Chủ", "--role", "superadmin", "--password", "mat-khau-dai-1"], session)
    assert out.startswith("created superadmin owner@example.com"), out
    assert (await login(client, "owner@example.com", "mat-khau-dai-1")).status_code == 200
    me = (await client.get("/auth/me")).json()
    assert (me["role"], me["status"], me["tree_id"]) == ("superadmin", "active", None)
