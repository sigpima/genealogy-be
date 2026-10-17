"""GĐ2 B1/B3 over HTTP: new profile fields, sibling order, mother and adoption."""

import pytest

from app.core.tenants import create_user, lowest_tree
from tests.test_roles_auth import PASSWORD, login, register


@pytest.fixture
async def admin(client, session):
    """The admin of the (default) tree; the platform's first registration is the tree-less superadmin."""
    await register(client, "root@example.com", "Root")
    await create_user(
        session, email="admin@example.com", full_name="Admin", password=PASSWORD, role="admin", tree=await lowest_tree(session)
    )
    await login(client, "admin@example.com")
    return client


@pytest.fixture
def guest(make_client):
    return make_client()


async def add(c, name, parent_id=None, **extra):
    response = await c.post("/members", json={"full_name": name, "parent_id": parent_id, **extra})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def add_spouse(c, member_id, name, **extra):
    response = await c.post(f"/members/{member_id}/marriages", json={"spouse_full_name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --------------------------------------------------------------------- B1


async def test_new_fields_round_trip_through_create_read_update(admin):
    fields = {
        "birth_year": 1945, "birth_month": 8, "birth_day": 15,
        "death_year": 2020, "death_month": 3, "death_day": 12, "death_is_lunar": True, "death_leap_month": True,
        "hometown": "Tiên Điền", "phone": "+84 912 345 678", "email": "a@example.com", "birth_order": 2,
    }
    member_id = await add(admin, "Root", **fields)
    created = (await admin.get(f"/members/{member_id}")).json()
    for key, value in fields.items():
        assert created[key] == value, key

    update = {"full_name": "Root", **{**fields, "hometown": "Hà Nội", "death_leap_month": False}}
    response = await admin.put(f"/members/{member_id}", json=update)
    assert response.status_code == 200
    assert response.json()["hometown"] == "Hà Nội" and response.json()["death_leap_month"] is False


async def test_put_is_a_full_replacement_for_the_new_fields_too(admin):
    member_id = await add(admin, "Root", hometown="X", phone="123", birth_order=2, birth_month=5, birth_day=5)
    response = await admin.put(f"/members/{member_id}", json={"full_name": "Root"})
    body = response.json()
    assert (body["hometown"], body["phone"], body["birth_order"], body["birth_month"], body["birth_day"]) == (None, None, None, None, None)
    assert (body["death_is_lunar"], body["birth_is_lunar"]) == (True, False)


async def test_invalid_dates_are_rejected_by_the_api(admin):
    for bad in ({"birth_month": 13}, {"death_day": 5}, {"birth_year": 2001, "birth_month": 2, "birth_day": 29}):
        assert (await admin.post("/members", json={"full_name": "X", **bad})).status_code == 422


async def test_guests_do_not_see_phone_and_email_but_see_the_hometown(admin, guest, session):
    member_id = await add(admin, "Root", hometown="Hà Tĩnh", phone="0912345678", email="a@example.com", notes="n")
    await admin.put("/admin/settings", json={"visibility": "public", "registration": "approval"})
    seen = (await guest.get(f"/members/{member_id}")).json()
    assert seen["hometown"] == "Hà Tĩnh"
    assert seen["phone"] is None and seen["email"] is None and seen["notes"] is None
    full = (await admin.get(f"/members/{member_id}")).json()
    assert (full["phone"], full["email"]) == ("0912345678", "a@example.com")


async def test_tree_children_follow_birth_order_then_creation_order(admin):
    root = await add(admin, "Root")
    third = await add(admin, "C", root, birth_order=3)
    unordered_1 = await add(admin, "U1", root)
    first = await add(admin, "A", root, birth_order=1)
    unordered_2 = await add(admin, "U2", root)
    second = await add(admin, "B", root, birth_order=2)
    names = [c["name"] for c in (await admin.get("/members/tree")).json()["children"]]
    assert names == ["A", "B", "C", "U1", "U2"]


async def test_sibling_rank_uses_birth_order_before_birth_year(admin):
    root = await add(admin, "Root")
    # born in the opposite order of the manual order: the manual order wins
    younger_but_first = await add(admin, "First", root, gender="male", birth_year=1960, birth_order=1)
    older_but_second = await add(admin, "Second", root, gender="male", birth_year=1950, birth_order=2)
    assert (await admin.get(f"/members/{younger_but_first}")).json()["sibling_rank"] == "Trưởng nam"
    assert (await admin.get(f"/members/{older_but_second}")).json()["sibling_rank"] == "Út nam"


# --------------------------------------------------------------------- B3


async def test_a_child_can_name_a_recorded_spouse_of_the_father_as_mother(admin):
    father = await add(admin, "Father")
    await add_spouse(admin, father, "Wife 1")
    detail = (await admin.get(f"/members/{father}")).json()
    wife_id = detail["spouses"][0]["id"]
    child = await add(admin, "Child", father, mother_id=wife_id, is_adopted=False)
    body = (await admin.get(f"/members/{child}")).json()
    assert body["mother_id"] == wife_id and body["is_adopted"] is False


async def test_the_mother_must_be_a_spouse_of_the_father(admin):
    father, other = await add(admin, "Father"), await add(admin, "Other man")
    await add_spouse(admin, other, "Someone else's wife")
    stranger_wife = (await admin.get(f"/members/{other}")).json()["spouses"][0]["id"]
    refused = await admin.post("/members", json={"full_name": "Child", "parent_id": father, "mother_id": stranger_wife})
    assert refused.status_code == 400
    assert "spouse" in refused.json()["detail"]
    no_father = await admin.post("/members", json={"full_name": "Orphan", "mother_id": stranger_wife})
    assert no_father.status_code == 400


async def test_changing_the_father_requires_the_mother_to_follow(admin):
    father, other = await add(admin, "Father"), await add(admin, "Other")
    await add_spouse(admin, father, "Wife")
    wife = (await admin.get(f"/members/{father}")).json()["spouses"][0]["id"]
    child = await add(admin, "Child", father, mother_id=wife)
    moved = await admin.put(f"/members/{child}", json={"full_name": "Child", "parent_id": other, "mother_id": wife})
    assert moved.status_code == 400
    cleared = await admin.put(f"/members/{child}", json={"full_name": "Child", "parent_id": other})
    assert cleared.status_code == 200 and cleared.json()["mother_id"] is None


async def test_deleting_the_mother_keeps_the_child_and_clears_the_link(admin):
    father = await add(admin, "Father")
    await add_spouse(admin, father, "Wife")
    wife = (await admin.get(f"/members/{father}")).json()["spouses"][0]["id"]
    child = await add(admin, "Child", father, mother_id=wife)
    assert (await admin.delete(f"/members/{wife}")).status_code == 204
    body = (await admin.get(f"/members/{child}")).json()
    assert body["mother_id"] is None


async def test_adoption_flag_persists(admin):
    father = await add(admin, "Father")
    child = await add(admin, "Adopted", father, is_adopted=True)
    assert (await admin.get(f"/members/{child}")).json()["is_adopted"] is True


async def test_spouses_are_listed_by_marriage_year_with_unknown_last(admin):
    man = await add(admin, "Man")
    await add_spouse(admin, man, "Unknown year")
    await add_spouse(admin, man, "Married 1980", marriage_year=1980)
    await add_spouse(admin, man, "Married 1970", marriage_year=1970)
    names = [s["full_name"] for s in (await admin.get(f"/members/{man}")).json()["spouses"]]
    assert names == ["Married 1970", "Married 1980", "Unknown year"]
