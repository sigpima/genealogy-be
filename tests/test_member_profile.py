from tests.test_member import _authenticate

PROFILE = {
    "courtesy_name": "Phúc Khang",
    "title": "Trưởng Chi",
    "residence": "Tiên Điền, Hà Tĩnh",
    "burial_place": "Nghĩa trang dòng họ",
    "burial_latitude": 18.55,
    "burial_longitude": 105.72,
}


async def _make(client, name, parent_id, **extra):
    response = await client.post(
        "/members", json={"full_name": name, "parent_id": parent_id, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_create_returns_and_detail_exposes_profile_fields(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", **PROFILE})
    assert created.status_code == 201
    for key, value in PROFILE.items():
        assert created.json()[key] == value

    detail = (await client.get(f"/members/{created.json()['id']}")).json()
    for key, value in PROFILE.items():
        assert detail[key] == value


async def test_new_member_has_null_profile_fields(client):
    await _authenticate(client)
    member_id = await _make(client, "Root", None)
    detail = (await client.get(f"/members/{member_id}")).json()
    for key in PROFILE:
        assert detail[key] is None


async def test_update_replaces_profile_fields_and_omitted_become_null(client):
    await _authenticate(client)
    member_id = await _make(client, "Root", None, **PROFILE)

    updated = await client.put(
        f"/members/{member_id}", json={"full_name": "Root", "title": "Tộc Trưởng"}
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Tộc Trưởng"
    assert updated.json()["courtesy_name"] is None
    assert updated.json()["burial_latitude"] is None


async def test_update_rejects_half_a_gps_pair(client):
    await _authenticate(client)
    member_id = await _make(client, "Root", None)
    response = await client.put(
        f"/members/{member_id}", json={"full_name": "Root", "burial_latitude": 10.0}
    )
    assert response.status_code == 422


async def test_tree_stays_skeleton_only(client):
    await _authenticate(client)
    await _make(client, "Root", None, **PROFILE)
    tree = (await client.get("/members/tree")).json()
    assert set(tree.keys()) == {"id", "name", "children"}


async def test_rank_is_none_for_root_and_unknown_gender(client):
    await _authenticate(client)
    root = await _make(client, "Root", None, gender="male")
    nogender = await _make(client, "Kid", root)
    other = await _make(client, "Kid2", root, gender="other")
    assert (await client.get(f"/members/{root}")).json()["sibling_rank"] is None
    assert (await client.get(f"/members/{nogender}")).json()["sibling_rank"] is None
    assert (await client.get(f"/members/{other}")).json()["sibling_rank"] is None


async def test_only_son_is_truong_nam(client):
    await _authenticate(client)
    root = await _make(client, "Root", None)
    son = await _make(client, "Son", root, gender="male", birth_year=1950)
    assert (await client.get(f"/members/{son}")).json()["sibling_rank"] == "Trưởng nam"


async def test_sons_are_ranked_by_birth_year_with_truong_thu_ut(client):
    await _authenticate(client)
    root = await _make(client, "Root", None)
    youngest = await _make(client, "C", root, gender="male", birth_year=1960)
    eldest = await _make(client, "A", root, gender="male", birth_year=1950)
    middle = await _make(client, "B", root, gender="male", birth_year=1955)

    ranks = {
        name: (await client.get(f"/members/{mid}")).json()["sibling_rank"]
        for name, mid in {"eldest": eldest, "middle": middle, "youngest": youngest}.items()
    }
    assert ranks == {"eldest": "Trưởng nam", "middle": "Thứ nam", "youngest": "Út nam"}


async def test_two_siblings_are_truong_and_ut(client):
    await _authenticate(client)
    root = await _make(client, "Root", None)
    first = await _make(client, "A", root, gender="female", birth_year=1950)
    second = await _make(client, "B", root, gender="female", birth_year=1953)
    assert (await client.get(f"/members/{first}")).json()["sibling_rank"] == "Trưởng nữ"
    assert (await client.get(f"/members/{second}")).json()["sibling_rank"] == "Út nữ"


async def test_sons_and_daughters_are_ranked_separately(client):
    await _authenticate(client)
    root = await _make(client, "Root", None)
    daughter = await _make(client, "D", root, gender="female", birth_year=1948)
    son = await _make(client, "S", root, gender="male", birth_year=1952)
    assert (await client.get(f"/members/{daughter}")).json()["sibling_rank"] == "Trưởng nữ"
    assert (await client.get(f"/members/{son}")).json()["sibling_rank"] == "Trưởng nam"


async def test_unknown_birth_years_sort_last_then_by_id(client):
    await _authenticate(client)
    root = await _make(client, "Root", None)
    unknown_a = await _make(client, "UA", root, gender="male")
    known = await _make(client, "K", root, gender="male", birth_year=1970)
    unknown_b = await _make(client, "UB", root, gender="male")
    ranks = [
        (await client.get(f"/members/{m}")).json()["sibling_rank"]
        for m in (known, unknown_a, unknown_b)
    ]
    assert ranks == ["Trưởng nam", "Thứ nam", "Út nam"]


async def test_spouse_is_not_ranked_among_children(client):
    await _authenticate(client)
    root = await _make(client, "Root", None)
    marriage = await client.post(
        f"/members/{root}/marriages", json={"spouse_full_name": "Spouse"}
    )
    spouse_id = marriage.json()["id"]
    assert (await client.get(f"/members/{spouse_id}")).json()["sibling_rank"] is None
