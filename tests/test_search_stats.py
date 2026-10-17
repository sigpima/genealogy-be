"""GĐ3: accent-insensitive search with filters, typo suggestions, and basic statistics."""

import datetime

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login, set_setting

THIS_YEAR = datetime.date.today().year


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
    """Tổ (1) -> Hòa, Bình (2) -> Hoa Con (3); Hòa is married to Trần Thị Lan; Bình heads a branch."""
    admin = await signed_in(make_client, "admin_a")
    ids = {"admin": admin}
    ids["to"] = await add(admin, "Nguyễn Văn Tổ", birth_year=1900, death_year=1970, gender="male", hometown="Hà Tĩnh")
    ids["hoa"] = await add(admin, "Nguyễn Văn Hòa", ids["to"], birth_year=1930, death_year=2001, gender="male", hometown="Hà Tĩnh")
    ids["binh"] = await add(admin, "Nguyễn Thị Bình", ids["to"], birth_year=1925, gender="female", hometown="Nghệ An")
    ids["con"] = await add(admin, "Nguyễn Hoa Con", ids["hoa"], birth_year=THIS_YEAR - 30, gender="female")
    await admin.post(f"/members/{ids['hoa']}/marriages", json={"spouse_full_name": "Trần Thị Lan", "spouse_birth_year": 1932})
    branch = await admin.post("/branches", json={"name": "Chi Bình", "root_member_id": ids["binh"]})
    ids["branch"] = branch.json()["id"]
    return ids


def names(response):
    assert response.status_code == 200, response.text
    return [i["full_name"] for i in response.json()["items"]]


# ------------------------------------------------------------------ search


async def test_search_ignores_diacritics_case_and_tone_placement(people):
    admin = people["admin"]
    for query in ("hoa", "HÒA", "hoà", "Hòa"):
        found = names(await admin.get("/members/search", params={"q": query}))
        assert "Nguyễn Văn Hòa" in found and "Nguyễn Hoa Con" in found, query


async def test_every_word_must_match_in_any_order(people):
    admin = people["admin"]
    assert names(await admin.get("/members/search", params={"q": "van hoa"})) == ["Nguyễn Văn Hòa"]
    assert names(await admin.get("/members/search", params={"q": "hoa van"})) == ["Nguyễn Văn Hòa"]
    assert names(await admin.get("/members/search", params={"q": "van xyz"})) == []


async def test_results_are_ranked_exact_prefix_then_contains(people):
    admin = people["admin"]
    await add(admin, "Hoa", people["to"], gender="female")
    found = names(await admin.get("/members/search", params={"q": "hoa"}))
    assert found[0] == "Hoa"  # exact before the longer names that merely contain it


async def test_spouses_are_found_by_name_and_point_to_their_partner(people):
    admin = people["admin"]
    body = (await admin.get("/members/search", params={"q": "tran thi lan"})).json()
    [spouse] = body["items"]
    assert spouse["is_spouse"] is True and spouse["spouse_of"] == {"id": people["hoa"], "name": "Nguyễn Văn Hòa"}
    assert spouse["generation"] == 2  # a spouse counts as their partner's generation
    # without a text query only blood members are listed
    everyone = names(await admin.get("/members/search"))
    assert "Trần Thị Lan" not in everyone and len(everyone) == 4


async def test_filters(people):
    admin = people["admin"]
    get = lambda **p: names_of(admin, p)  # noqa: E731

    async def names_of(c, params):
        return names(await c.get("/members/search", params=params))

    assert await get(generation=2) == ["Nguyễn Văn Hòa", "Nguyễn Thị Bình"]
    assert await get(gender="female") == ["Nguyễn Hoa Con", "Nguyễn Thị Bình"]  # tree order: depth first
    assert await get(hometown="ha tinh") == ["Nguyễn Văn Tổ", "Nguyễn Văn Hòa"]
    assert await get(born_from=1925, born_to=1930) == ["Nguyễn Văn Hòa", "Nguyễn Thị Bình"]
    assert await get(born_from=1932) == ["Nguyễn Hoa Con"]
    assert await get(status="deceased") == ["Nguyễn Văn Tổ", "Nguyễn Văn Hòa"]
    assert await get(status="living") == ["Nguyễn Hoa Con"]
    assert await get(status="unknown") == ["Nguyễn Thị Bình"]  # born 1925, no death year, over 100 years ago
    assert await get(branch=people["branch"]) == ["Nguyễn Thị Bình"]
    assert await get(gender="female", generation=3) == ["Nguyễn Hoa Con"]
    assert await get(q="nguyen", status="deceased", generation=2) == ["Nguyễn Văn Hòa"]


async def test_gender_unknown_filter(people):
    admin = people["admin"]
    await add(admin, "Chưa rõ", people["to"])
    assert names(await admin.get("/members/search", params={"gender": "unknown"})) == ["Chưa rõ"]


async def test_paging_and_validation(people):
    admin = people["admin"]
    page = (await admin.get("/members/search", params={"limit": 2, "offset": 1})).json()
    assert page["total"] == 4 and len(page["items"]) == 2
    assert (await admin.get("/members/search", params={"limit": 0})).status_code == 422
    assert (await admin.get("/members/search", params={"limit": 101})).status_code == 422
    assert (await admin.get("/members/search", params={"status": "zombie"})).status_code == 422
    assert (await admin.get("/members/search", params={"gender": "robot"})).status_code == 422
    assert (await admin.get("/members/search", params={"branch": 99999})).status_code == 404


async def test_results_carry_branch_and_parent(people):
    admin = people["admin"]
    [item] = (await admin.get("/members/search", params={"q": "binh"})).json()["items"]
    assert item["parent_name"] == "Nguyễn Văn Tổ" and item["branch"]["name"] == "Chi Bình"
    assert item["hometown"] == "Nghệ An" and item["generation"] == 2
    assert "phone" not in item and "email" not in item


async def test_suggestions_appear_only_when_nothing_matches(people):
    admin = people["admin"]
    body = (await admin.get("/members/search", params={"q": "Nguyen Van Hao"})).json()
    assert body["items"] == []
    assert [s["full_name"] for s in body["suggestions"]][:1] == ["Nguyễn Văn Hòa"]
    hit = (await admin.get("/members/search", params={"q": "hoa"})).json()
    assert hit["suggestions"] == []
    nothing = (await admin.get("/members/search", params={"q": "zzzzzz qqqq"})).json()
    assert nothing["items"] == [] and nothing["suggestions"] == []


async def test_suggestions_list_each_name_once(people):
    admin = people["admin"]
    await add(admin, "Nguyễn Văn Hòa", people["to"])  # a namesake
    body = (await admin.get("/members/search", params={"q": "Nguyen Van Hao"})).json()
    assert [s["full_name"] for s in body["suggestions"]].count("Nguyễn Văn Hòa") == 1


async def test_access_and_isolation(people, make_client, session, world):
    member = await signed_in(make_client, "member_a")
    assert (await member.get("/members/search", params={"q": "hoa"})).status_code == 200
    other = await signed_in(make_client, "admin_b")
    assert (await other.get("/members/search", params={"q": "hoa"})).json()["items"] == []
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    assert (await guest.get("/members/search", params={"q": "hoa"})).status_code == 401
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert (await guest.get("/members/search", params={"q": "hoa"})).status_code == 200


# ------------------------------------------------------------------ stats


async def test_stats(people):
    admin = people["admin"]
    body = (await admin.get("/stats")).json()
    assert body["total"] == 4 and body["spouses"] == 1
    assert body["by_generation"] == [
        {"generation": 1, "count": 1},
        {"generation": 2, "count": 2},
        {"generation": 3, "count": 1},
    ]
    assert body["gender"] == {"male": 2, "female": 2, "other": 0, "unknown": 0}
    assert body["status"] == {"living": 1, "deceased": 2, "unknown": 1}
    assert body["by_branch"] == [
        {"id": people["branch"], "name": "Chi Bình", "color": body["by_branch"][0]["color"], "count": 1}
    ]
    assert body["without_branch"] == 3


async def test_stats_for_one_branch(people):
    admin = people["admin"]
    body = (await admin.get("/stats", params={"branch": people["branch"]})).json()
    assert body["total"] == 1 and body["gender"]["female"] == 1
    assert body["by_generation"] == [{"generation": 2, "count": 1}]
    assert (await admin.get("/stats", params={"branch": 99999})).status_code == 404


async def test_stats_are_per_tree_and_need_read_access(people, make_client):
    other = await signed_in(make_client, "admin_b")
    assert (await other.get("/stats")).json()["total"] == 0
    assert (await make_client().get("/stats")).status_code == 401
