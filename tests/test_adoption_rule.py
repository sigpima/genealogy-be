"""A person without a father cannot be adopted: refused on every write path."""

import pytest
from sqlalchemy import text

from app.core.tenants import create_user
from tests.test_gd2_members import add
from tests.test_gd2_tools import upload
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def admin(client, session, tree):
    await create_user(session, email="admin@example.com", full_name="Admin", password=PASSWORD, role="admin", tree=tree)
    await login(client, "admin@example.com")
    return client


async def test_create_root_adopted_is_422(admin):
    r = await admin.post("/members", json={"full_name": "Tổ", "is_adopted": True})
    assert r.status_code == 422
    assert "adopted" in r.text


async def test_create_child_adopted_is_ok(admin):
    root = await add(admin, "Tổ")
    child = await add(admin, "Con nuôi", root, is_adopted=True)
    assert (await admin.get(f"/members/{child}")).json()["is_adopted"] is True


async def test_put_adopted_on_root_is_422(admin):
    root = await add(admin, "Tổ")
    r = await admin.put(f"/members/{root}", json={"full_name": "Tổ", "is_adopted": True})
    assert r.status_code == 422


async def test_patch_clearing_parent_of_adopted_child_is_422(admin):
    root = await add(admin, "Tổ")
    child = await add(admin, "Con nuôi", root, is_adopted=True)
    r = await admin.patch(f"/members/{child}", json={"parent_id": None})
    assert r.status_code == 422


async def test_csv_import_adopted_without_parent_row_is_rejected_with_row_number(admin):
    root = await add(admin, "Tổ")
    text_ = f"id,full_name,parent_id,is_adopted\n{root},Tổ,,true\n"
    r = await admin.post("/members/import", files=upload(text_))
    assert r.status_code == 422, r.text
    assert "adopted" in r.text and "2" in r.text


async def test_a_member_cannot_propose_adopting_the_root(admin, session, make_client):
    root = await add(admin, "Tổ")
    from app.models.tree import Tree  # noqa: F401  (tree fixture already created)

    tree_id = (await session.execute(text("SELECT MIN(id) FROM trees"))).scalar_one()
    from app.core.tenants import create_user as mk

    await mk(session, email="m@example.com", full_name="M", password=PASSWORD, role="member", tree=await session.get(Tree, tree_id))
    m = make_client()
    await login(m, "m@example.com")
    r = await m.post("/requests", json={"kind": "edit", "member_id": root, "changes": {"is_adopted": True}, "message": "Tôi biết chuyện này"})
    assert r.status_code == 422, r.text


async def test_existing_adopted_root_can_be_saved_after_unticking(admin, session):
    root = await add(admin, "Tổ")
    await session.execute(text("UPDATE members SET is_adopted = true WHERE id = :i"), {"i": root})
    await session.commit()
    # an unrelated edit does not trip over the stale flag ...
    assert (await admin.patch(f"/members/{root}", json={"phone": "0912345678"})).status_code == 200
    # ... and unticking it works
    r = await admin.patch(f"/members/{root}", json={"is_adopted": False})
    assert r.status_code == 200 and r.json()["is_adopted"] is False
