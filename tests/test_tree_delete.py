"""Superadmin console: deleting a paused family for good (rows and files), with every guard."""

import io

import pytest
from PIL import Image
from sqlalchemy import text

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    await create_user(session, email="root@example.com", full_name="Root", password=PASSWORD, role="superadmin", tree=None)
    for key, role, tree in [("admin_a", "admin", tree_a), ("member_a", "member", tree_a), ("admin_b", "admin", tree_b)]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"a": tree_a, "b": tree_b, "session": session}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80), "teal").save(buffer, "PNG")
    return buffer.getvalue()


def files_under(root) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


async def fill(admin, name):
    """A family with a person (+avatar, +photo), a place, an article, an event with a card and a branch."""
    to = (await admin.post("/members", json={"full_name": f"Tổ {name}", "birth_year": 1900})).json()["id"]
    await admin.post(f"/members/{to}/avatar", files={"file": ("a.png", png(), "image/png")})
    assert (await admin.post(f"/members/{to}/media", files={"file": ("anh.png", png(), "image/png")})).status_code == 201
    child = (await admin.post("/members", json={"full_name": f"Con {name}", "parent_id": to})).json()["id"]
    await admin.post(f"/members/{to}/marriages", json={"spouse_full_name": f"Vợ {name}"})
    await admin.post("/places", json={"kind": "tomb", "name": f"Mộ {name}"})
    await admin.post("/articles", json={"title": f"Bài {name}", "kind": "other", "status": "published", "body": "nội dung"})
    await admin.post("/branches", json={"name": f"Chi {name}", "root_member_id": child})
    event = (await admin.post("/events", json={"title": "Giỗ", "kind": "memorial", "calendar": "solar", "month": 3, "day": 4, "year": 2030})).json()
    await admin.post(f"/events/{event['id']}/cards", json={"date": "2030-03-04"})
    return to


async def tree_tables(session):
    rows = await session.execute(text("SELECT DISTINCT table_name FROM information_schema.columns WHERE column_name = 'tree_id' AND table_schema = 'public'"))
    return sorted(r[0] for r in rows if r[0] != "platform_events")  # the platform log deliberately outlives the family


async def counts(session, tree_id):
    return {t: (await session.execute(text(f"SELECT count(*) FROM {t} WHERE tree_id = {tree_id}"))).scalar_one() for t in await tree_tables(session)}


async def test_deleting_a_paused_family_removes_its_rows_and_files_and_nothing_else(world, make_client, upload_dir):
    session = world["session"]
    admin_a = await signed_in(make_client, "admin_a")
    to_a = await fill(admin_a, "A")
    member = await signed_in(make_client, "member_a")
    assert (await member.post("/requests", json={"kind": "report", "member_id": to_a, "message": "báo sai năm sinh"})).status_code == 201
    files_a = files_under(upload_dir)
    assert files_a
    admin_b = await signed_in(make_client, "admin_b")
    await fill(admin_b, "B")
    files_b = files_under(upload_dir) - files_a
    assert files_b
    before_b = await counts(session, world["b"].id)

    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    r = await root.request("DELETE", f"/trees/{world['a'].id}", json={"slug": "ho-a"})
    assert r.status_code == 204, r.text

    assert [t["name"] for t in (await root.get("/trees")).json()] == ["Họ B"]
    assert (await session.execute(text(f"SELECT count(*) FROM trees WHERE id = {world['a'].id}"))).scalar_one() == 0
    assert all(v == 0 for v in (await counts(session, world["a"].id)).values())
    assert (await session.execute(text("SELECT count(*) FROM users WHERE email LIKE '%_a@example.com'"))).scalar_one() == 0
    assert files_under(upload_dir) == files_b  # A's files are gone, B's are all still there
    assert await counts(session, world["b"].id) == before_b


async def test_the_platform_event_keeps_who_it_was_and_what_went_without_secrets(world, make_client):
    admin_a = await signed_in(make_client, "admin_a")
    await fill(admin_a, "A")
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    await root.request("DELETE", f"/trees/{world['a'].id}", json={"slug": "ho-a"})
    row = (await world["session"].execute(text("SELECT tree_id, tree_name, details FROM platform_events WHERE action = 'tree.delete'"))).one()
    assert row[0] == world["a"].id and row[1] == "Họ A"
    assert row[2]["slug"] == "ho-a" and row[2]["members"] >= 3 and row[2]["users"] == 2 and row[2]["files"] >= 3
    assert "password" not in str(row[2]).lower()


async def test_an_active_family_cannot_be_deleted(world, make_client):
    root = await signed_in(make_client, "root")
    r = await root.request("DELETE", f"/trees/{world['a'].id}", json={"slug": "ho-a"})
    assert r.status_code == 409
    assert len((await root.get("/trees")).json()) == 2


async def test_the_slug_must_be_typed_exactly(world, make_client):
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    for wrong in ("ho-b", "HO-A", "", " ho-a "):
        assert (await root.request("DELETE", f"/trees/{world['a'].id}", json={"slug": wrong})).status_code in (409, 422)
    assert len((await root.get("/trees")).json()) == 2


async def test_a_missing_file_does_not_stop_the_deletion(world, make_client, upload_dir):
    admin_a = await signed_in(make_client, "admin_a")
    await fill(admin_a, "A")
    for path in upload_dir.rglob("*"):
        if path.is_file():
            path.unlink()  # the files were already lost (the very thing the data-health page reports)
    root = await signed_in(make_client, "root")
    await root.post(f"/trees/{world['a'].id}/pause")
    assert (await root.request("DELETE", f"/trees/{world['a'].id}", json={"slug": "ho-a"})).status_code == 204


async def test_the_acting_tree_cookie_may_point_at_the_deleted_tree(world, make_client):
    root = await signed_in(make_client, "root")
    root.cookies.set("acting_tree", str(world["a"].id))
    await root.post(f"/trees/{world['a'].id}/pause")
    assert (await root.request("DELETE", f"/trees/{world['a'].id}", json={"slug": "ho-a"})).status_code == 204
    r = await root.get("/trees")
    assert r.status_code == 200 and [t["is_current"] for t in r.json()] == [True]  # fell back to the lowest tree


async def test_only_the_superadmin_and_only_known_trees(world, make_client):
    root = await signed_in(make_client, "root")
    assert (await root.request("DELETE", "/trees/9999", json={"slug": "x"})).status_code == 404
    admin_b = await signed_in(make_client, "admin_b")
    assert (await admin_b.request("DELETE", f"/trees/{world['b'].id}", json={"slug": "ho-b"})).status_code == 403
    assert (await make_client().request("DELETE", f"/trees/{world['b'].id}", json={"slug": "ho-b"})).status_code == 401
