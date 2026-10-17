"""GĐ11 B4: Vietnamese kinship terms."""

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


async def marry(c, member_id, name, **extra):
    r = await c.post(f"/members/{member_id}/marriages", json={"spouse_full_name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
async def f(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = {"admin": admin, "make_client": make_client}
    ids["to"] = await add(admin, "Tổ", gender="male", birth_year=1900)
    ids["an"] = await add(admin, "An", ids["to"], gender="male", birth_year=1925)
    ids["binh"] = await add(admin, "Bình", ids["to"], gender="female", birth_year=1930)
    ids["cuong"] = await add(admin, "Cường", ids["to"], gender="male", birth_year=1935)
    ids["anh"] = await add(admin, "Anh", ids["an"], gender="male", birth_year=1950)
    ids["hoa"] = await add(admin, "Hoa", ids["an"], gender="female", birth_year=1955)
    ids["dung"] = await add(admin, "Dũng", ids["binh"], gender="male", birth_year=1960)
    ids["em"] = await add(admin, "Em", ids["cuong"], gender="female", birth_year=1962)
    ids["sau"] = await add(admin, "Sâu", ids["anh"], gender="male", birth_year=1975)
    ids["ut"] = await add(admin, "Út", ids["an"], gender="male", birth_year=1985)
    await marry(admin, ids["to"], "Lan", spouse_gender="female")
    await marry(admin, ids["an"], "Mai", spouse_gender="female")
    detail = (await admin.get(f"/members/{ids['to']}")).json()
    ids["lan"] = detail["spouses"][0]["id"]
    ids["mai"] = (await admin.get(f"/members/{ids['an']}")).json()["spouses"][0]["id"]
    assert (await admin.patch(f"/members/{ids['an']}", json={"mother_id": ids["lan"]})).status_code == 200
    assert (await admin.patch(f"/members/{ids['anh']}", json={"mother_id": ids["mai"]})).status_code == 200
    return ids


async def rel(c, a, b):
    r = await c.get("/members/relationship", params={"a": a, "b": b})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["a_is"], body["b_is"]


async def test_same_person_and_spouses(f):
    assert (await f["admin"].get("/members/relationship", params={"a": f["an"], "b": f["an"]})).json()["kind"] == "self"
    assert await rel(f["admin"], f["to"], f["lan"]) == ("chồng", "vợ")
    assert await rel(f["admin"], f["lan"], f["to"]) == ("vợ", "chồng")


async def test_parents_and_ancestors(f):
    assert await rel(f["admin"], f["to"], f["an"]) == ("cha", "con")
    assert await rel(f["admin"], f["to"], f["anh"]) == ("ông", "cháu")
    assert await rel(f["admin"], f["to"], f["sau"]) == ("cụ ông", "chắt")
    assert await rel(f["admin"], f["sau"], f["to"]) == ("chắt", "cụ ông")
    assert await rel(f["admin"], f["lan"], f["an"]) == ("mẹ", "con")  # through mother_id
    assert await rel(f["admin"], f["mai"], f["anh"]) == ("mẹ", "con")


async def test_siblings_by_age_or_birth_order(f):
    assert await rel(f["admin"], f["an"], f["binh"]) == ("anh", "em gái")
    assert await rel(f["admin"], f["cuong"], f["an"]) == ("em trai", "anh")
    assert await rel(f["admin"], f["binh"], f["cuong"]) == ("chị", "em trai")
    await f["admin"].patch(f"/members/{f['cuong']}", json={"birth_order": 1})
    await f["admin"].patch(f"/members/{f['an']}", json={"birth_order": 2})
    assert await rel(f["admin"], f["cuong"], f["an"]) == ("anh", "em trai")  # the manual order wins over the years


async def test_uncles_and_aunts_older_means_bac_younger_means_chu_or_co(f):
    assert await rel(f["admin"], f["cuong"], f["anh"]) == ("chú", "cháu")
    assert await rel(f["admin"], f["binh"], f["anh"]) == ("cô", "cháu")
    await f["admin"].patch(f"/members/{f['cuong']}", json={"birth_order": 1})
    await f["admin"].patch(f"/members/{f['an']}", json={"birth_order": 2})
    assert await rel(f["admin"], f["cuong"], f["anh"]) == ("bác", "cháu")  # older than the child's father
    assert await rel(f["admin"], f["cuong"], f["sau"]) == ("ông bác", "cháu")


async def test_great_uncle_and_cousins(f):
    assert await rel(f["admin"], f["binh"], f["sau"]) == ("bà cô", "cháu")
    assert await rel(f["admin"], f["cuong"], f["sau"]) == ("ông chú", "cháu")
    assert await rel(f["admin"], f["anh"], f["dung"]) == ("anh họ", "em họ")
    assert await rel(f["admin"], f["hoa"], f["em"]) == ("chị họ", "em họ")


async def test_cousins_are_ranked_by_branch_not_by_age(f):
    # Út (born 1985) is the younger-born but belongs to the elder branch (An before Bình) => anh họ of Dũng (born 1960)
    assert await rel(f["admin"], f["ut"], f["dung"]) == ("anh họ", "em họ")
    assert await rel(f["admin"], f["dung"], f["ut"]) == ("em họ", "anh họ")


async def test_second_cousins_and_cousins_of_another_generation(f):
    chut = await add(f["admin"], "Chút Con", f["dung"], gender="male", birth_year=1990)
    assert await rel(f["admin"], f["sau"], chut) == ("anh họ (cùng cụ)", "em họ (cùng cụ)")
    assert await rel(f["admin"], f["anh"], chut) == ("bác họ", "cháu họ")  # Anh is of the elder branch
    assert await rel(f["admin"], f["dung"], f["sau"]) == ("chú họ", "cháu họ")


async def test_a_spouse_is_described_through_the_partner(f):
    assert await rel(f["admin"], f["mai"], f["cuong"]) == ("chị dâu", "em chồng")
    assert await rel(f["admin"], f["mai"], f["to"]) == ("con dâu", "cha chồng")
    assert await rel(f["admin"], f["mai"], f["dung"]) == ("bác gái", "cháu")  # An, of the elder branch, is Dũng's bác


async def test_the_sentence_names_both_people(f):
    body = (await f["admin"].get("/members/relationship", params={"a": f["cuong"], "b": f["anh"]})).json()
    assert body["sentence"] == "Cường là chú của Anh."
    assert body["common_ancestor"]["name"] == "Tổ" and (body["steps_a"], body["steps_b"]) == (1, 2)


async def test_unknown_or_foreign_people_are_404_and_reads_follow_visibility(f, world, make_client, session):
    admin_b = await signed_in(make_client, "admin_b")
    assert (await admin_b.get("/members/relationship", params={"a": f["an"], "b": f["to"]})).status_code == 404
    assert (await f["admin"].get("/members/relationship", params={"a": 999, "b": f["to"]})).status_code == 404
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    assert (await guest.get("/members/relationship", params={"a": f["an"], "b": f["to"]})).status_code == 401
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert (await guest.get("/members/relationship", params={"a": f["an"], "b": f["to"]})).status_code == 200
