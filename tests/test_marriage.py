async def _authenticate(client):
    await client.post(
        "/auth/register",
        json={
            "email": "marriage-tester@example.com",
            "password": "longenough",
            "full_name": "Tester",
        },
    )
    await client.post(
        "/auth/login",
        json={"email": "marriage-tester@example.com", "password": "longenough"},
    )


async def test_create_marriage(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]

    response = await client.post(
        f"/members/{root_id}/marriages",
        json={"spouse_full_name": "Wife", "marriage_year": 1975},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["full_name"] == "Wife"
    assert body["marriage_year"] == 1975
    assert "marriage_id" in body


async def test_create_marriage_rejects_nonexistent_member(client):
    await _authenticate(client)
    response = await client.post("/members/9999/marriages", json={"spouse_full_name": "Wife"})
    assert response.status_code == 404


async def test_create_marriage_rejects_death_before_birth(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]

    response = await client.post(
        f"/members/{root_id}/marriages",
        json={"spouse_full_name": "Wife", "spouse_birth_year": 2000, "spouse_death_year": 1990},
    )
    assert response.status_code == 422


async def test_update_marriage(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    created = await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "Wife"})
    marriage_id = created.json()["marriage_id"]

    response = await client.put(
        f"/members/marriages/{marriage_id}",
        json={
            "spouse_full_name": "Wife Updated",
            "spouse_birth_year": 1950,
            "spouse_death_year": 2020,
            "spouse_gender": "female",
            "spouse_notes": "some notes",
            "marriage_year": 1976,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Wife Updated"
    assert body["birth_year"] == 1950
    assert body["marriage_year"] == 1976


async def test_update_marriage_rejects_nonexistent_marriage(client):
    await _authenticate(client)
    response = await client.put("/members/marriages/9999", json={"spouse_full_name": "Wife"})
    assert response.status_code == 404


async def test_marriage_endpoints_require_auth(client):
    response = await client.post("/members/1/marriages", json={"spouse_full_name": "Wife"})
    assert response.status_code == 401


async def test_tree_includes_spouse_on_correct_node(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    await client.post("/members", json={"full_name": "Child", "parent_id": root_id})
    await client.post(
        f"/members/{root_id}/marriages",
        json={"spouse_full_name": "Wife", "marriage_year": 1975},
    )

    response = await client.get("/members/tree")
    tree = response.json()
    assert tree["name"] == "Husband"
    assert len(tree["children"]) == 1
    assert tree["children"][0]["name"] == "Child"


async def test_member_detail_supports_multiple_marriages(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "First Wife"})
    await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "Second Wife"})

    response = await client.get(f"/members/{root_id}")
    names = {spouse["full_name"] for spouse in response.json()["spouses"]}
    assert names == {"First Wife", "Second Wife"}


async def test_deleting_spouse_removes_marriage(client):
    await _authenticate(client)
    root = await client.post("/members", json={"full_name": "Husband", "parent_id": None})
    root_id = root.json()["id"]
    created = await client.post(f"/members/{root_id}/marriages", json={"spouse_full_name": "Wife"})
    spouse_id = created.json()["id"]

    delete_response = await client.delete(f"/members/{spouse_id}")
    assert delete_response.status_code == 204

    detail_response = await client.get(f"/members/{root_id}")
    assert detail_response.json()["spouses"] == []
