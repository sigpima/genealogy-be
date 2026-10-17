"""GĐ5: giỗ (computed from the lunar death date), events, the month/upcoming views, conversion."""

from datetime import date

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


async def add(c, name, parent_id=None, **extra):
    r = await c.post("/members", json={"full_name": name, "parent_id": parent_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
async def people(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = {"admin": admin}
    root = await add(admin, "Tổ")
    # lunar 15/8, died in lunar year 2001 -> giỗ lần thứ 23 on 2024-09-17
    ids["a"] = await add(admin, "Ông A", root, death_year=2001, death_month=8, death_day=15, death_is_lunar=True)
    # lunar 30/12, died 2020 -> in lunar year 2023 that is 2024-02-09 (month 12 of 2023 has 30 days)
    ids["b"] = await add(admin, "Bà B", root, death_year=2020, death_month=12, death_day=30, death_is_lunar=True)
    # died on the SOLAR date 1990-01-27 = lunar 1/1/1990 -> every Tết; 2024-02-10 is the 34th
    ids["c"] = await add(admin, "Cụ C", root, death_year=1990, death_month=1, death_day=27, death_is_lunar=False)
    # solar month/day without a year: cannot be converted
    ids["d"] = await add(admin, "Anh D", root, death_month=3, death_day=3, death_is_lunar=False)
    # lunar 5/5, year unknown -> every year, no number
    ids["e"] = await add(admin, "Chị E", root, death_month=5, death_day=5, death_is_lunar=True)
    # alive: no giỗ
    ids["f"] = await add(admin, "Em F", root, birth_year=2000)
    return ids


def by_title(items, fragment):
    return [i for i in items if fragment in i["title"]]


async def month(c, y, m):
    r = await c.get("/calendar/month", params={"year": y, "month": m})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ giỗ


async def test_a_lunar_death_date_gives_its_anniversary_with_the_count(people):
    body = await month(people["admin"], 2024, 9)
    [gio] = by_title(body["items"], "Ông A")
    assert gio["kind"] == "death_anniversary" and gio["date"] == "2024-09-17" and gio["years"] == 23
    assert gio["lunar"] == {"day": 15, "month": 8, "year": 2024, "leap": False}
    assert gio["member_id"] == people["a"]


async def test_day_30_and_a_solar_death_date_are_handled(people):
    body = await month(people["admin"], 2024, 2)
    assert {(i["date"], i["years"]) for i in by_title(body["items"], "Bà B")} == {("2024-02-09", 3)}
    assert {(i["date"], i["years"]) for i in by_title(body["items"], "Cụ C")} == {("2024-02-10", 34)}


async def test_no_death_year_means_every_year_without_a_number(people):
    body = await month(people["admin"], 2024, 6)
    [gio] = by_title(body["items"], "Chị E")
    assert gio["date"] == "2024-06-10" and gio["years"] is None


async def test_nothing_before_the_first_anniversary_and_the_alive_have_none(people):
    # the death year itself is not an anniversary; Ông A died in lunar 2001 so lunar 2001 has nothing
    assert by_title((await month(people["admin"], 2001, 9))["items"], "Ông A") == []
    assert by_title((await month(people["admin"], 2002, 9))["items"], "Ông A")[0]["years"] == 1
    everything = []
    for m in range(1, 13):
        everything += (await month(people["admin"], 2024, m))["items"]
    assert by_title(everything, "Em F") == []


async def test_people_without_a_usable_date_are_counted(people):
    body = await month(people["admin"], 2024, 3)
    assert body["incomplete"] == 1  # Anh D: solar month/day without a year


async def test_every_day_of_the_month_carries_its_lunar_date(people):
    body = await month(people["admin"], 2024, 9)
    assert len(body["days"]) == 30
    day = next(d for d in body["days"] if d["date"] == "2024-09-17")
    assert (day["lunar_day"], day["lunar_month"], day["lunar_year"], day["lunar_leap"]) == (15, 8, 2024, False)
    assert body["days"][0]["date"] == "2024-09-01"


async def test_month_validation(people):
    admin = people["admin"]
    assert (await admin.get("/calendar/month", params={"year": 2024, "month": 13})).status_code == 422
    assert (await admin.get("/calendar/month", params={"year": 1800, "month": 1})).status_code == 422
    assert (await admin.get("/calendar/month", params={"year": 2024})).status_code == 422


# ------------------------------------------------------------------ events


async def test_events_crud_is_admin_only(people, make_client):
    admin = people["admin"]
    made = await admin.post("/events", json={
        "title": "Giỗ Tổ họ", "kind": "memorial", "calendar": "lunar", "month": 3, "day": 10,
        "repeats_yearly": True, "location": "Nhà thờ họ", "time_text": "08:00", "description": "Cả họ về dự",
    })
    assert made.status_code == 201, made.text
    event = made.json()
    assert event["title"] == "Giỗ Tổ họ" and event["repeats_yearly"] is True and event["year"] is None
    member = await signed_in(make_client, "member_a")
    assert [e["title"] for e in (await member.get("/events")).json()] == ["Giỗ Tổ họ"]
    assert (await member.post("/events", json={"title": "x", "kind": "other", "calendar": "solar", "month": 1, "day": 1, "year": 2030})).status_code == 403
    assert (await member.put(f"/events/{event['id']}", json=event)).status_code == 403
    assert (await member.delete(f"/events/{event['id']}")).status_code == 403
    changed = await admin.put(f"/events/{event['id']}", json={**event, "title": "Giỗ Tổ (đổi)", "location": None})
    assert changed.status_code == 200 and changed.json()["title"] == "Giỗ Tổ (đổi)" and changed.json()["location"] is None
    assert (await admin.delete(f"/events/{event['id']}")).status_code == 204
    assert (await admin.get("/events")).json() == []
    assert (await admin.delete(f"/events/{event['id']}")).status_code == 404


async def test_event_validation(people):
    admin = people["admin"]
    base = {"title": "Họp họ", "kind": "gathering", "calendar": "solar", "month": 6, "day": 15, "year": 2030}
    assert (await admin.post("/events", json=base)).status_code == 201
    assert (await admin.post("/events", json={**base, "title": " "})).status_code == 422
    assert (await admin.post("/events", json={**base, "kind": "party"})).status_code == 422
    assert (await admin.post("/events", json={**base, "month": 13})).status_code == 422
    assert (await admin.post("/events", json={**base, "day": 32})).status_code == 422
    assert (await admin.post("/events", json={**base, "month": 2, "day": 30})).status_code == 422  # not a solar date
    assert (await admin.post("/events", json={**base, "year": 2023, "month": 2, "day": 29})).status_code == 422
    assert (await admin.post("/events", json={**base, "calendar": "lunar", "day": 31})).status_code == 422  # lunar months have <= 30 days
    assert (await admin.post("/events", json={**base, "year": None})).status_code == 422  # a one-off needs its year
    assert (await admin.post("/events", json={**base, "year": None, "repeats_yearly": True})).status_code == 201
    assert (await admin.post("/events", json={**base, "time_text": "25:99"})).status_code == 422
    assert (await admin.post("/events", json={**base, "time_text": "8:30"})).status_code == 422


async def test_repeating_and_one_off_events_appear_where_they_belong(people):
    admin = people["admin"]
    await admin.post("/events", json={"title": "Giỗ Tổ", "kind": "memorial", "calendar": "lunar", "month": 3, "day": 10, "repeats_yearly": True})
    await admin.post("/events", json={"title": "Tất niên", "kind": "gathering", "calendar": "solar", "month": 2, "day": 8, "year": 2024})
    await admin.post("/events", json={"title": "Họp mặt đầu năm", "kind": "gathering", "calendar": "solar", "month": 1, "day": 2, "repeats_yearly": True})
    april_2024 = by_title((await month(admin, 2024, 4))["items"], "Giỗ Tổ")
    assert [(i["date"], i["kind"]) for i in april_2024] == [("2024-04-18", "event")]
    assert by_title((await month(admin, 2025, 4))["items"], "Giỗ Tổ")[0]["date"] == "2025-04-07"
    assert by_title((await month(admin, 2024, 2))["items"], "Tất niên")[0]["date"] == "2024-02-08"
    assert by_title((await month(admin, 2025, 2))["items"], "Tất niên") == []  # a one-off does not repeat
    assert by_title((await month(admin, 2027, 1))["items"], "Họp mặt")[0]["date"] == "2027-01-02"


async def test_a_repeating_event_with_a_start_year_does_not_go_back(people):
    admin = people["admin"]
    await admin.post("/events", json={"title": "Từ 2030", "kind": "other", "calendar": "solar", "month": 5, "day": 5, "year": 2030, "repeats_yearly": True})
    assert by_title((await month(admin, 2029, 5))["items"], "Từ 2030") == []
    assert len(by_title((await month(admin, 2031, 5))["items"], "Từ 2030")) == 1


async def test_events_are_isolated_between_families(world, people, make_client):
    await people["admin"].post("/events", json={"title": "Của họ A", "kind": "other", "calendar": "solar", "month": 1, "day": 1, "year": 2030})
    other = await signed_in(make_client, "admin_b")
    assert (await other.get("/events")).json() == []
    assert (await month(other, 2030, 1))["items"] == []


# ------------------------------------------------------------------ upcoming and conversion


async def test_upcoming_lists_the_next_days_in_order(people, monkeypatch):
    monkeypatch.setattr("app.core.calendar_items.vn_today", lambda: date(2024, 9, 10))
    await people["admin"].post("/events", json={"title": "Họp họ", "kind": "gathering", "calendar": "solar", "month": 9, "day": 20, "year": 2024})
    body = (await people["admin"].get("/calendar/upcoming")).json()
    assert [(i["date"], i["title"].split(" (")[0]) for i in body["items"]][:2] == [("2024-09-17", "Giỗ Ông A"), ("2024-09-20", "Họp họ")]
    assert all("2024-09-10" <= i["date"] <= "2024-10-10" for i in body["items"])
    assert (await people["admin"].get("/calendar/upcoming", params={"days": 3})).json()["items"] == []
    assert (await people["admin"].get("/calendar/upcoming", params={"days": 0})).status_code == 422
    assert (await people["admin"].get("/calendar/upcoming", params={"days": 400})).status_code == 422


async def test_convert_both_ways(people):
    admin = people["admin"]
    lunar = (await admin.get("/calendar/convert", params={"solar": "2024-02-10"})).json()
    assert lunar["lunar"] == {"day": 1, "month": 1, "year": 2024, "leap": False} and lunar["solar"] == "2024-02-10"
    solar = (await admin.get("/calendar/convert", params={"lunar_day": 15, "lunar_month": 8, "lunar_year": 2024})).json()
    assert solar["solar"] == "2024-09-17"
    leap = (await admin.get("/calendar/convert", params={"lunar_day": 1, "lunar_month": 4, "lunar_year": 2020, "lunar_leap": True})).json()
    assert leap["solar"] == "2020-05-23"
    assert (await admin.get("/calendar/convert", params={"lunar_day": 1, "lunar_month": 3, "lunar_year": 2024, "lunar_leap": True})).status_code == 404
    assert (await admin.get("/calendar/convert", params={"solar": "not-a-date"})).status_code == 422
    assert (await admin.get("/calendar/convert")).status_code == 422


# ------------------------------------------------------------------ access


async def test_reads_follow_the_trees_visibility(people, make_client, session, world):
    member = await signed_in(make_client, "member_a")
    assert (await month(member, 2024, 9))["items"]
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    assert (await guest.get("/calendar/month", params={"year": 2024, "month": 9})).status_code == 401
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert (await guest.get("/calendar/month", params={"year": 2024, "month": 9})).status_code == 200


async def test_event_changes_are_audited(people):
    admin = people["admin"]
    made = (await admin.post("/events", json={"title": "Họp họ", "kind": "gathering", "calendar": "solar", "month": 9, "day": 20, "year": 2030})).json()
    await admin.put(f"/events/{made['id']}", json={**made, "title": "Họp họ (đổi)"})
    await admin.delete(f"/events/{made['id']}")
    actions = [e["action"] for e in (await admin.get("/audit")).json()["items"]][:3]
    assert actions == ["event.delete", "event.update", "event.create"]
