"""The Google Maps link on a burial and on a place, over HTTP."""

import pytest

from app.core.tenants import create_user
from tests.test_gd2_members import add
from tests.test_gd2_tools import upload
from tests.test_roles_auth import PASSWORD, login

WITH_COORDS = "https://www.google.com/maps/place/Nghia+trang/@21.0285,105.8542,15z"
SHORT = "https://maps.app.goo.gl/AbCd123"


@pytest.fixture
async def admin(client, session, tree):
    await create_user(session, email="admin@example.com", full_name="Admin", password=PASSWORD, role="admin", tree=tree)
    await login(client, "admin@example.com")
    return client


async def test_a_link_with_coordinates_fills_the_burial_position(admin):
    member = await add(admin, "Tổ", burial_map_url=WITH_COORDS)
    body = (await admin.get(f"/members/{member}")).json()
    assert body["burial_map_url"] == WITH_COORDS
    assert (body["burial_latitude"], body["burial_longitude"]) == (21.0285, 105.8542)


async def test_a_short_link_is_stored_and_keeps_old_coordinates(admin):
    member = await add(admin, "Tổ", burial_latitude=10.0, burial_longitude=20.0)
    r = await admin.patch(f"/members/{member}", json={"burial_map_url": SHORT})
    assert r.status_code == 200, r.text
    body = (await admin.get(f"/members/{member}")).json()
    assert body["burial_map_url"] == SHORT
    assert (body["burial_latitude"], body["burial_longitude"]) == (10.0, 20.0)


async def test_a_bad_link_is_422(admin):
    r = await admin.post("/members", json={"full_name": "Tổ", "burial_map_url": "https://evil.com/maps"})
    assert r.status_code == 422


async def test_clearing_the_link_clears_the_coordinates_it_gave(admin):
    member = await add(admin, "Tổ", burial_map_url=WITH_COORDS)
    r = await admin.patch(f"/members/{member}", json={"burial_map_url": None})
    assert r.status_code == 200, r.text
    body = (await admin.get(f"/members/{member}")).json()
    assert body["burial_map_url"] is None and body["burial_latitude"] is None and body["burial_longitude"] is None


async def test_old_coordinates_without_a_link_survive_unrelated_edits(admin):
    member = await add(admin, "Tổ", burial_latitude=10.0, burial_longitude=20.0)
    await admin.patch(f"/members/{member}", json={"phone": "0912345678"})
    body = (await admin.get(f"/members/{member}")).json()
    assert (body["burial_latitude"], body["burial_longitude"]) == (10.0, 20.0)


async def test_a_member_cannot_propose_the_link(admin, session, tree, make_client):
    root = await add(admin, "Tổ")
    await create_user(session, email="m@example.com", full_name="M", password=PASSWORD, role="member", tree=tree)
    m = make_client()
    await login(m, "m@example.com")
    r = await m.post("/requests", json={"kind": "edit", "member_id": root, "changes": {"burial_map_url": SHORT}, "message": "Tôi biết chuyện này"})
    assert r.status_code == 422, r.text


async def test_csv_round_trips_the_link_and_validates_it(admin):
    member = await add(admin, "Tổ", burial_map_url=SHORT)
    exported = (await admin.get("/members/export.csv")).text
    assert "burial_map_url" in exported.splitlines()[0] and SHORT in exported
    bad = f"id,full_name,burial_map_url\n{member},Tổ,https://evil.com/x\n"
    r = await admin.post("/members/import", files=upload(bad))
    assert r.status_code == 422, r.text


async def test_a_place_takes_a_link_too(admin):
    r = await admin.post("/places", json={"kind": "tomb", "name": "Mộ tổ", "map_url": WITH_COORDS})
    assert r.status_code == 201, r.text
    place = r.json()
    assert place["map_url"] == WITH_COORDS
    assert (place["latitude"], place["longitude"]) == (21.0285, 105.8542)
    assert (await admin.post("/places", json={"kind": "tomb", "name": "X", "map_url": "http://evil.com"})).status_code == 422
    cleared = await admin.put(f"/places/{place['id']}", json={"kind": "tomb", "name": "Mộ tổ", "map_url": None})
    assert cleared.status_code == 200
    assert cleared.json()["map_url"] is None and cleared.json()["latitude"] is None
