"""Completeness counts behind the five data-entry cards."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_gd2_members import add
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def admin(client, session, tree):
    await create_user(session, email="admin@example.com", full_name="Admin", password=PASSWORD, role="admin", tree=tree)
    await login(client, "admin@example.com")
    return client


async def test_counts_death_year_and_avatar(admin, session):
    root = await add(admin, "Tổ", death_year=1950, gender="male")
    await add(admin, "Con", root, death_year=1990)
    await add(admin, "Cháu", root)
    from sqlalchemy import text

    await session.execute(text("UPDATE members SET avatar_url = '/uploads/x.jpg' WHERE id = :i"), {"i": root})
    await session.commit()
    body = (await admin.get("/members/completeness")).json()
    assert body["total"] == 3
    assert body["with_death_year"] == 2
    assert body["with_avatar"] == 1
    assert body["with_gender"] == 1


async def test_other_trees_not_counted(admin, session):
    other = await create_tree(session, "Họ khác", "ho-khac")
    await create_user(session, email="b@example.com", full_name="B", password=PASSWORD, role="admin", tree=other)
    await add(admin, "Tổ", death_year=1950)
    from httpx import ASGITransport, AsyncClient
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as b:
        await login(b, "b@example.com")
        await b.post("/members", json={"full_name": "X"})
        body = (await b.get("/members/completeness")).json()
    assert body["total"] == 1 and body["with_death_year"] == 0
