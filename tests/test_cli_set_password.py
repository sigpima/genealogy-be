"""manage.py set-password: the way back in for a forgotten superadmin password."""

from app.cli import run
from app.core.tenants import create_user
from tests.test_roles_auth import PASSWORD, login


async def test_set_password_generates_and_prints_one(session, make_client):
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    out = await run(["set-password", "--email", "root@example.com"], session)
    assert "password:" in out
    new = out.split("password:")[1].strip()
    assert (await login(make_client(), "root@example.com", PASSWORD)).status_code == 401
    assert (await login(make_client(), "root@example.com", new)).status_code == 200


async def test_set_password_with_a_given_password_prints_nothing_secret(session, make_client):
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    out = await run(["set-password", "--email", "root@example.com", "--password", "mat-khau-moi-123"], session)
    assert "mat-khau-moi-123" not in out and out.startswith("password of root@example.com changed")
    assert (await login(make_client(), "root@example.com", "mat-khau-moi-123")).status_code == 200


async def test_set_password_reports_mistakes_instead_of_crashing(session):
    assert (await run(["set-password", "--email", "nobody@example.com"], session)).startswith("error:")
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    assert (await run(["set-password", "--email", "root@example.com", "--password", "ngan"], session)).startswith("error:")
