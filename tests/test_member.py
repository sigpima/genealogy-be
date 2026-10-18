from tests.test_roles_auth import make_user


async def _authenticate(client):
    await make_user(client, "member-tester@example.com", "Tester", role="superadmin", password="longenough")
    await client.post(
        "/auth/login",
        json={"email": "member-tester@example.com", "password": "longenough"},
    )


async def test_tree_is_null_when_empty(client):
    await _authenticate(client)
    response = await client.get("/members/tree")
    assert response.status_code == 200
    assert response.json() is None


async def test_tree_response_only_has_skeleton_fields(client):
    await _authenticate(client)
    await client.post(
        "/members",
        json={
            "full_name": "Root",
            "parent_id": None,
            "birth_year": 1950,
            "gender": "male",
            "notes": "some notes",
        },
    )

    response = await client.get("/members/tree")
    assert response.status_code == 200
    tree = response.json()
    assert set(tree.keys()) == {"id", "name", "children"}


async def test_create_and_fetch_tree(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    root_id = root.json()["id"]
    await client.post("/members", json={"full_name": "Child A", "parent_id": root_id})
    await client.post("/members", json={"full_name": "Child B", "parent_id": root_id})

    response = await client.get("/members/tree")
    assert response.status_code == 200
    tree = response.json()
    assert tree["name"] == "Root"
    assert {child["name"] for child in tree["children"]} == {"Child A", "Child B"}


async def test_create_rejects_nonexistent_parent(client):
    await _authenticate(client)
    response = await client.post("/members", json={"full_name": "Orphan", "parent_id": 9999})
    assert response.status_code == 404


async def test_update_full_name(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Original", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.put(
        f"/members/{member_id}", json={"full_name": "Renamed", "parent_id": None}
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Renamed"


async def test_update_rejects_self_as_parent(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Solo", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.put(
        f"/members/{member_id}", json={"full_name": "Solo", "parent_id": member_id}
    )
    assert response.status_code == 400


async def test_update_rejects_descendant_as_parent(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    root_id = root.json()["id"]
    child = await client.post("/members", json={"full_name": "Child", "parent_id": root_id})
    child_id = child.json()["id"]

    response = await client.put(
        f"/members/{root_id}", json={"full_name": "Root", "parent_id": child_id}
    )
    assert response.status_code == 400


async def test_delete_leaf_member(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "ToDelete", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.delete(f"/members/{member_id}")
    assert response.status_code == 204

    tree_response = await client.get("/members/tree")
    assert tree_response.json() is None


async def test_delete_rejects_member_with_children(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    root_id = root.json()["id"]
    await client.post("/members", json={"full_name": "Child", "parent_id": root_id})

    response = await client.delete(f"/members/{root_id}")
    assert response.status_code == 409


async def test_member_endpoints_require_auth(client):
    response = await client.get("/members/tree")
    assert response.status_code == 401


async def test_create_and_fetch_member_with_details(client):
    await _authenticate(client)
    response = await client.post(
        "/members",
        json={
            "full_name": "Detailed",
            "parent_id": None,
            "birth_year": 1950,
            "death_year": 2010,
            "gender": "male",
            "notes": "Some notes",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["birth_year"] == 1950
    assert body["gender"] == "male"


async def test_get_member_detail(client):
    await _authenticate(client)
    created = await client.post(
        "/members",
        json={
            "full_name": "Detailed",
            "parent_id": None,
            "birth_year": 1950,
            "death_year": 2010,
            "gender": "male",
            "notes": "Some notes",
        },
    )
    member_id = created.json()["id"]

    response = await client.get(f"/members/{member_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == member_id
    assert body["birth_year"] == 1950
    assert body["death_year"] == 2010
    assert body["gender"] == "male"
    assert body["notes"] == "Some notes"
    assert body["spouses"] == []


async def test_get_member_detail_defaults_for_bare_member(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Bare", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.get(f"/members/{member_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["birth_year"] is None
    assert body["avatar_url"] is None
    assert body["spouses"] == []


async def test_get_member_detail_rejects_nonexistent_member(client):
    await _authenticate(client)
    response = await client.get("/members/9999")
    assert response.status_code == 404


async def test_update_member_details(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Original", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.put(
        f"/members/{member_id}",
        json={
            "full_name": "Original",
            "parent_id": None,
            "birth_year": 1900,
            "death_year": 1980,
            "gender": "female",
            "notes": "updated notes",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["birth_year"] == 1900
    assert body["gender"] == "female"
    assert body["notes"] == "updated notes"


async def test_create_rejects_death_before_birth(client):
    await _authenticate(client)
    response = await client.post(
        "/members",
        json={"full_name": "Bad Dates", "birth_year": 2010, "death_year": 1950},
    )
    assert response.status_code == 422
