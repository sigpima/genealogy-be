async def _authenticate(client):
    await client.post(
        "/auth/register",
        json={
            "email": "avatar-tester@example.com",
            "password": "longenough",
            "full_name": "Tester",
        },
    )
    await client.post(
        "/auth/login",
        json={"email": "avatar-tester@example.com", "password": "longenough"},
    )


async def test_upload_avatar(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["avatar_url"].startswith("/uploads/avatars/")
    assert body["avatar_url"].endswith(".jpg")


async def test_upload_avatar_writes_file_to_disk(client, upload_dir):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    relative_path = response.json()["avatar_url"].removeprefix("/uploads/")
    assert (upload_dir / relative_path).exists()


async def test_upload_avatar_replaces_previous_file(client, upload_dir):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    first = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("first.png", b"first-bytes", "image/png")},
    )
    first_relative = first.json()["avatar_url"].removeprefix("/uploads/")
    first_path = upload_dir / first_relative
    assert first_path.exists()

    second = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("second.png", b"second-bytes", "image/png")},
    )
    second_url = second.json()["avatar_url"]

    assert first.json()["avatar_url"] != second_url
    assert not first_path.exists()


async def test_upload_avatar_rejects_disallowed_content_type(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    response = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.gif", b"data", "image/gif")},
    )
    assert response.status_code == 400


async def test_upload_avatar_rejects_oversized_file(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]

    oversized = b"x" * (5 * 1024 * 1024 + 1)
    response = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", oversized, "image/jpeg")},
    )
    assert response.status_code == 400


async def test_upload_avatar_rejects_nonexistent_member(client):
    await _authenticate(client)
    response = await client.post(
        "/members/9999/avatar",
        files={"file": ("avatar.jpg", b"data", "image/jpeg")},
    )
    assert response.status_code == 404


async def test_delete_avatar(client, upload_dir):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]
    upload = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", b"data", "image/jpeg")},
    )
    relative_path = upload.json()["avatar_url"].removeprefix("/uploads/")
    file_path = upload_dir / relative_path
    assert file_path.exists()

    response = await client.delete(f"/members/{member_id}/avatar")
    assert response.status_code == 204
    assert not file_path.exists()


async def test_delete_avatar_rejects_nonexistent_member(client):
    await _authenticate(client)
    response = await client.delete("/members/9999/avatar")
    assert response.status_code == 404


async def test_member_detail_includes_avatar_url(client):
    await _authenticate(client)
    created = await client.post("/members", json={"full_name": "Root", "parent_id": None})
    member_id = created.json()["id"]
    upload = await client.post(
        f"/members/{member_id}/avatar",
        files={"file": ("avatar.jpg", b"data", "image/jpeg")},
    )
    avatar_url = upload.json()["avatar_url"]

    detail = await client.get(f"/members/{member_id}")
    assert detail.json()["avatar_url"] == avatar_url


async def test_avatar_endpoints_require_auth(client):
    response = await client.post(
        "/members/1/avatar", files={"file": ("avatar.jpg", b"data", "image/jpeg")}
    )
    assert response.status_code == 401

    response = await client.delete("/members/1/avatar")
    assert response.status_code == 401
