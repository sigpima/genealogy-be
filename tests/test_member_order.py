from tests.test_member import _authenticate


async def _make(client, name, parent_id):
    response = await client.post("/members", json={"full_name": name, "parent_id": parent_id})
    assert response.status_code == 201
    return response.json()["id"]


async def test_tree_children_keep_creation_order_after_an_update(client):
    """Postgres moves an UPDATEd row to the end of the heap, so without ORDER BY the tree
    would reshuffle siblings every time one of them is edited."""
    await _authenticate(client)
    root = await _make(client, "Root", None)
    first = await _make(client, "A", root)
    await _make(client, "B", root)
    await _make(client, "C", root)

    await client.put(f"/members/{first}", json={"full_name": "A edited", "parent_id": root})
    await client.put(f"/members/{first}", json={"full_name": "A edited again", "parent_id": root})

    tree = (await client.get("/members/tree")).json()
    assert [child["name"] for child in tree["children"]] == ["A edited again", "B", "C"]
