"""GĐ6: places (nhà thờ, lăng mộ...), where people rest, and migrating the old free-text field."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login, set_setting


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


@pytest.fixture
async def admin(world, make_client):
    return await signed_in(make_client, "admin_a")


async def add(c, name, parent_id=None, **extra):
    r = await c.post("/members", json={"full_name": name, "parent_id": parent_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def place(c, name="Nhà thờ họ", **extra):
    r = await c.post("/places", json={"kind": "clan_house", "name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ CRUD


async def test_admin_manages_places_everybody_signed_in_reads(admin, make_client):
    made = await place(admin, address="Xã Phú Ốc", latitude=18.55, longitude=105.72, caretaker="Ông Tư", visit_notes="Mang theo hương", description="Nhà thờ chính")
    assert made["kind"] == "clan_house" and made["resting_count"] == 0 and made["latitude"] == 18.55
    member = await signed_in(make_client, "member_a")
    assert [p["name"] for p in (await member.get("/places")).json()] == ["Nhà thờ họ"]
    assert (await member.get(f"/places/{made['id']}")).json()["caretaker"] == "Ông Tư"
    assert (await member.post("/places", json={"kind": "tomb", "name": "x"})).status_code == 403
    assert (await member.put(f"/places/{made['id']}", json={"kind": "tomb", "name": "x"})).status_code == 403
    assert (await member.delete(f"/places/{made['id']}")).status_code == 403
    changed = await admin.put(f"/places/{made['id']}", json={"kind": "temple", "name": "Đền họ", "address": None})
    assert changed.status_code == 200 and changed.json()["kind"] == "temple" and changed.json()["latitude"] is None  # PUT replaces
    assert (await admin.delete(f"/places/{made['id']}")).status_code == 204
    assert (await admin.get("/places")).json() == []
    assert (await admin.delete(f"/places/{made['id']}")).status_code == 404


async def test_place_validation(admin):
    ok = {"kind": "tomb", "name": "Lăng ông"}
    assert (await admin.post("/places", json=ok)).status_code == 201
    assert (await admin.post("/places", json={**ok, "name": "  "})).status_code == 422
    assert (await admin.post("/places", json={**ok, "kind": "castle"})).status_code == 422
    assert (await admin.post("/places", json={**ok, "latitude": 18.5})).status_code == 422  # both or neither
    assert (await admin.post("/places", json={**ok, "latitude": 95, "longitude": 105})).status_code == 422
    assert (await admin.post("/places", json={**ok, "latitude": 18.5, "longitude": 190})).status_code == 422
    assert (await admin.post("/places", json={**ok, "latitude": 18.5, "longitude": 105.7})).status_code == 201


async def test_places_are_signed_in_only_and_isolated(world, admin, make_client, session):
    made = await place(admin)
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert (await guest.get("/places")).status_code == 401  # burial information is not for guests, even on a public tree
    other = await signed_in(make_client, "admin_b")
    assert (await other.get("/places")).json() == []
    assert (await other.get(f"/places/{made['id']}")).status_code == 404
    assert (await other.put(f"/places/{made['id']}", json={"kind": "tomb", "name": "x"})).status_code == 404
    assert (await other.delete(f"/places/{made['id']}")).status_code == 404


# ------------------------------------------------------------------ where people rest


async def test_a_person_can_rest_in_a_place_and_the_place_lists_them(admin):
    p = await place(admin, "Nghĩa trang Phú Ốc", latitude=18.5, longitude=105.7)
    root = await add(admin, "Tổ")
    a = await add(admin, "Ông A", root, death_year=1990, burial_place_id=p["id"], burial_plot="Khu B, hàng 3, mộ 12")
    await add(admin, "Bà B", root, death_year=1995, burial_place_id=p["id"])
    detail = (await admin.get(f"/members/{a}")).json()
    assert detail["burial_place_id"] == p["id"] and detail["burial_plot"] == "Khu B, hàng 3, mộ 12"
    assert detail["resting_place"] == {"id": p["id"], "name": "Nghĩa trang Phú Ốc", "kind": "clan_house", "latitude": 18.5, "longitude": 105.7}
    body = (await admin.get(f"/places/{p['id']}")).json()
    assert body["resting_count"] == 2
    assert [r["full_name"] for r in body["residents"]] == ["Ông A", "Bà B"]
    assert body["residents"][0]["plot"] == "Khu B, hàng 3, mộ 12" and body["residents"][0]["death_year"] == 1990
    assert (await admin.get("/places")).json()[0]["resting_count"] == 2


async def test_the_place_must_belong_to_the_same_tree(world, admin, make_client):
    other = await signed_in(make_client, "admin_b")
    foreign = await place(other, "Của họ B")
    assert (await admin.post("/members", json={"full_name": "X", "burial_place_id": foreign["id"]})).status_code == 404
    member = await add(admin, "Y")
    assert (await admin.patch(f"/members/{member}", json={"burial_place_id": foreign["id"]})).status_code == 404
    assert (await admin.patch(f"/members/{member}", json={"burial_place_id": 99999})).status_code == 404
    assert (await admin.put(f"/members/{member}", json={"full_name": "Y", "burial_place_id": foreign["id"]})).status_code == 404


async def test_patch_can_change_and_clear_the_resting_place(admin):
    p = await place(admin)
    member = await add(admin, "Z", burial_place_id=p["id"])
    assert (await admin.patch(f"/members/{member}", json={"burial_plot": "Mộ 5"})).json()["burial_place_id"] == p["id"]
    assert (await admin.patch(f"/members/{member}", json={"burial_place_id": None})).json()["burial_place_id"] is None
    assert (await admin.get(f"/members/{member}")).json()["resting_place"] is None


async def test_deleting_a_place_keeps_the_people(admin):
    p = await place(admin)
    member = await add(admin, "Z", burial_place_id=p["id"], burial_plot="Mộ 5")
    assert (await admin.delete(f"/places/{p['id']}")).status_code == 204
    detail = (await admin.get(f"/members/{member}")).json()
    assert detail["burial_place_id"] is None and detail["burial_plot"] == "Mộ 5" and detail["resting_place"] is None


async def test_guests_do_not_see_where_people_rest(world, admin, make_client, session):
    p = await place(admin)
    member = await add(admin, "Ông A", burial_place_id=p["id"], burial_plot="Mộ 1")
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    body = (await guest.get(f"/members/{member}")).json()
    assert body["burial_place_id"] is None and body["burial_plot"] is None and body["resting_place"] is None


async def test_members_cannot_propose_the_place_fields(world, admin, make_client):
    p = await place(admin)
    member_id = await add(admin, "Z")
    viewer = await signed_in(make_client, "member_a")
    for changes in ({"burial_place_id": p["id"]}, {"burial_plot": "Mộ 5"}):
        r = await viewer.post("/requests", json={"kind": "edit", "member_id": member_id, "changes": changes})
        assert r.status_code == 422, changes


async def test_place_fields_round_trip_through_csv(admin):
    p = await place(admin)
    member = await add(admin, "Ông A", burial_place_id=p["id"], burial_plot="Mộ 1")
    exported = (await admin.get("/members/export.csv")).text.lstrip("﻿")
    header = exported.splitlines()[0].split(",")
    assert "burial_place_id" in header and "burial_plot" in header
    again = await admin.post("/members/import", files={"file": ("m.csv", exported.encode(), "text/csv")})
    assert again.json()["updated"] == 0 and again.json()["unchanged"] == 1
    edit = f"id,burial_plot\n{member},Mộ 9\n".encode()
    assert (await admin.post("/members/import", files={"file": ("m.csv", edit, "text/csv")})).json()["updated"] == 1
    assert (await admin.get(f"/members/{member}")).json()["burial_plot"] == "Mộ 9"
    foreign = f"id,burial_place_id\n{member},99999\n".encode()
    assert (await admin.post("/members/import", files={"file": ("m.csv", foreign, "text/csv")})).status_code == 422


async def test_place_changes_are_audited(admin):
    p = await place(admin, "Nhà thờ")
    await admin.put(f"/places/{p['id']}", json={"kind": "clan_house", "name": "Nhà thờ họ"})
    await admin.delete(f"/places/{p['id']}")
    actions = [e["action"] for e in (await admin.get("/audit")).json()["items"]][:3]
    assert actions == ["place.delete", "place.update", "place.create"]


# ------------------------------------------------------------------ migrating the old text field


async def test_migration_groups_the_old_text_into_places(admin):
    root = await add(admin, "Tổ")
    a = await add(admin, "A", root, burial_place="Nghĩa trang Phú Ốc", burial_latitude=18.5, burial_longitude=105.7)
    b = await add(admin, "B", root, burial_place="  nghia trang PHU ỐC ")  # same place, different spelling
    c = await add(admin, "C", root, burial_place="Đồi Chè")
    d = await add(admin, "D", root)  # no old data: untouched
    preview = await admin.post("/places/migrate-burials", params={"dry_run": "true"})
    assert preview.status_code == 200 and preview.json()["dry_run"] is True
    assert sorted((g["name"], g["count"]) for g in preview.json()["groups"]) == [("Nghĩa trang Phú Ốc", 2), ("Đồi Chè", 1)]
    assert (await admin.get("/places")).json() == []  # a preview writes nothing
    done = await admin.post("/places/migrate-burials")
    assert done.json()["created"] == 2 and done.json()["linked"] == 3
    places = {p["name"]: p for p in (await admin.get("/places")).json()}
    assert places["Nghĩa trang Phú Ốc"]["latitude"] == 18.5 and places["Nghĩa trang Phú Ốc"]["resting_count"] == 2
    assert places["Nghĩa trang Phú Ốc"]["kind"] == "tomb" and places["Đồi Chè"]["latitude"] is None
    for member in (a, b):
        assert (await admin.get(f"/members/{member}")).json()["resting_place"]["name"] == "Nghĩa trang Phú Ốc"
    assert (await admin.get(f"/members/{c}")).json()["burial_place"] == "Đồi Chè"  # the old text is kept
    assert (await admin.get(f"/members/{d}")).json()["resting_place"] is None
    again = (await admin.post("/places/migrate-burials")).json()
    assert again["created"] == 0 and again["linked"] == 0  # idempotent


async def test_migration_reuses_an_existing_place_with_the_same_name(admin):
    existing = await place(admin, "Đồi Chè")
    member = await add(admin, "C", burial_place="đồi chè")
    done = (await admin.post("/places/migrate-burials")).json()
    assert done["created"] == 0 and done["linked"] == 1
    assert (await admin.get(f"/members/{member}")).json()["burial_place_id"] == existing["id"]


async def test_only_admins_migrate(world, make_client):
    viewer = await signed_in(make_client, "member_a")
    assert (await viewer.post("/places/migrate-burials")).status_code == 403


# ------------------------------------------------------------------ events at a place


async def test_an_event_can_be_held_at_a_place(world, admin, make_client):
    p = await place(admin, "Nhà thờ họ")
    made = await admin.post("/events", json={
        "title": "Giỗ Tổ", "kind": "memorial", "calendar": "lunar", "month": 3, "day": 10, "repeats_yearly": True, "place_id": p["id"],
    })
    assert made.status_code == 201 and made.json()["place_id"] == p["id"]
    body = (await admin.get("/calendar/month", params={"year": 2024, "month": 4})).json()
    [item] = [i for i in body["items"] if i["title"] == "Giỗ Tổ"]
    assert item["place_id"] == p["id"] and item["location"] == "Nhà thờ họ"
    other = await signed_in(make_client, "admin_b")
    foreign = await place(other, "Của họ B")
    refused = await admin.post("/events", json={"title": "X", "kind": "other", "calendar": "solar", "month": 1, "day": 1, "year": 2030, "place_id": foreign["id"]})
    assert refused.status_code == 404
    await admin.delete(f"/places/{p['id']}")
    assert (await admin.get("/events")).json()[0]["place_id"] is None
