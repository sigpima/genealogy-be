"""GĐ8: the full statistics overview and the completeness figures."""

import io

import pytest
from PIL import Image

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
async def family(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    ids = {"admin": admin}
    ids["to"] = await add(admin, "Nguyễn Văn Tổ", gender="male", birth_year=1900, death_year=1970, hometown="Huế")
    ids["a"] = await add(admin, "Nguyễn Văn An", ids["to"], gender="male", birth_year=1925, death_year=1999)
    ids["b"] = await add(admin, "Nguyễn Thị Bình", ids["to"], gender="female", birth_year=1930, death_year=2010)
    ids["c"] = await add(admin, "Nguyễn Văn Cường", ids["to"])
    ids["a1"] = await add(admin, "Nguyễn Văn Anh", ids["a"], gender="male", birth_year=1950)
    ids["a2"] = await add(admin, "Nguyễn Thị Hoa Mai", ids["a"], gender="female", birth_year=1955, death_year=2021)
    ids["b1"] = await add(admin, "Nguyễn Đức Dũng", ids["b"], gender="male", birth_year=1960)
    await admin.post(f"/members/{ids['to']}/marriages", json={"spouse_full_name": "Trần Thị Lan"})
    await admin.post("/branches", json={"name": "Chi An", "root_member_id": ids["a"]})
    return ids


async def overview(c):
    r = await c.get("/stats/overview")
    assert r.status_code == 200, r.text
    return r.json()


async def test_totals_gender_generations_and_branches(family):
    body = await overview(family["admin"])
    assert body["totals"]["members"] == 7 and body["totals"]["spouses"] == 1 and body["totals"]["generations"] == 3
    assert body["totals"]["deceased"] == 4 and body["totals"]["living"] == 2 and body["totals"]["unknown"] == 1
    assert body["gender"] == {"male": 4, "female": 2, "other": 0, "unknown": 1}
    assert body["by_generation"] == [
        {"generation": 1, "count": 1, "male": 1, "female": 0},
        {"generation": 2, "count": 3, "male": 1, "female": 1},
        {"generation": 3, "count": 3, "male": 2, "female": 1},
    ]
    assert [(b["name"], b["count"]) for b in body["by_branch"]] == [("Chi An", 3)] and body["without_branch"] == 4


async def test_lifespan(family):
    life = (await overview(family["admin"]))["lifespan"]
    assert life == {"count": 4, "average": 72.5, "median": 72.0, "shortest": 66, "longest": 80, "male_average": 72.0, "female_average": 73.0}


async def test_lifespan_ignores_impossible_ages(family):
    admin = family["admin"]
    await add(admin, "Nguyễn Văn Lỗi", family["to"], birth_year=1900, death_year=2100)  # 200 years: a typo
    assert (await overview(admin))["lifespan"]["count"] == 4


async def test_lifespan_without_data_has_no_numbers(world, make_client):
    other = await signed_in(make_client, "admin_b")
    await add(other, "Chỉ có tên")
    life = (await overview(other))["lifespan"]
    assert life["count"] == 0 and life["average"] is None and life["median"] is None and life["shortest"] is None


async def test_birth_decades(family):
    decades = (await overview(family["admin"]))["birth_decades"]
    assert decades == [{"decade": 1900, "count": 1}, {"decade": 1920, "count": 1}, {"decade": 1930, "count": 1}, {"decade": 1950, "count": 2}, {"decade": 1960, "count": 1}]


async def test_children_figures(family):
    kids = (await overview(family["admin"]))["children"]
    assert kids["parents"] == 3 and kids["average_per_parent"] == 2.0 and kids["childless"] == 4
    assert kids["most"] == {"id": family["to"], "name": "Nguyễn Văn Tổ", "count": 3}


async def test_longest_line(family):
    line = (await overview(family["admin"]))["longest_line"]
    assert line["generations"] == 3
    assert line["names"] == ["Nguyễn Văn Tổ", "Nguyễn Văn An", "Nguyễn Văn Anh"]


async def test_common_names(family):
    body = await overview(family["admin"])
    assert body["middle_names"][:3] == [{"word": "Văn", "count": 4}, {"word": "Thị", "count": 2}, {"word": "Đức", "count": 1}]
    assert len(body["given_names"]) <= 10 and all(n["count"] >= 1 for n in body["given_names"])
    assert {n["word"] for n in body["given_names"]} >= {"An", "Mai"}


async def test_middle_names_are_counted_ignoring_accents(family):
    await add(family["admin"], "Nguyen Van Hung", family["to"])  # typed without accents
    middle = {n["word"]: n["count"] for n in (await overview(family["admin"]))["middle_names"]}
    assert middle["Văn"] == 5  # counted with the accented spelling


async def test_completeness(family):
    fields = {f["field"]: f for f in (await overview(family["admin"]))["completeness"]}
    assert fields["gender"]["have"] == 6 and fields["gender"]["total"] == 7
    assert fields["birth_year"]["have"] == 6
    assert fields["hometown"]["have"] == 1
    assert fields["residence"]["have"] == 0 and fields["avatar"]["have"] == 0 and fields["photos"]["have"] == 0
    assert fields["birth_date"]["have"] == 0
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), "red").save(buffer, "PNG")
    await family["admin"].post(f"/members/{family['a']}/media", files={"file": ("a.png", buffer.getvalue(), "image/png")})
    await family["admin"].patch(f"/members/{family['a']}", json={"birth_month": 3, "birth_day": 4, "residence": "Huế"})
    fields = {f["field"]: f for f in (await overview(family["admin"]))["completeness"]}
    assert fields["photos"]["have"] == 1 and fields["birth_date"]["have"] == 1 and fields["residence"]["have"] == 1


async def test_a_tree_with_nobody(world, make_client):
    other = await signed_in(make_client, "admin_b")
    body = await overview(other)
    assert body["totals"]["members"] == 0 and body["by_generation"] == [] and body["longest_line"]["generations"] == 0
    assert body["children"]["most"] is None and body["birth_decades"] == [] and body["middle_names"] == []
    assert all(f["total"] == 0 for f in body["completeness"])


async def test_access_and_isolation(world, family, make_client, session):
    member = await signed_in(make_client, "member_a")
    assert (await overview(member))["totals"]["members"] == 7
    other = await signed_in(make_client, "admin_b")
    assert (await overview(other))["totals"]["members"] == 0
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    assert (await guest.get("/stats/overview")).status_code == 401
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert (await guest.get("/stats/overview")).status_code == 200


async def test_table_can_filter_people_without_an_avatar(family):
    admin = family["admin"]
    everyone = (await admin.get("/members/table", params={"missing": "avatar", "limit": 100})).json()
    assert everyone["total"] == 7
    await admin.post(f"/members/{family['a']}/avatar", files={"file": ("a.jpg", b"x", "image/jpeg")})
    after = (await admin.get("/members/table", params={"missing": "avatar", "limit": 100})).json()
    assert after["total"] == 6 and family["a"] not in [r["id"] for r in after["items"]]
