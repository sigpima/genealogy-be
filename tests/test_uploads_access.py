"""Avatars are served through the API and follow the same access rules as the member they belong to."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login, set_setting, set_user

IMAGE = b"\xff\xd8\xff fake jpeg bytes"


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [
        ("root", "superadmin", None),
        ("admin_a", "admin", tree_a),
        ("member_a", "member", tree_a),
        ("admin_b", "admin", tree_b),
    ]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"tree_a": tree_a, "tree_b": tree_b}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


@pytest.fixture
async def avatar(world, make_client):
    """Tree A's admin uploads an avatar for a member of tree A; returns (url, admin_client, member_id)."""
    admin = await signed_in(make_client, "admin_a")
    member_id = (await admin.post("/members", json={"full_name": "Có ảnh"})).json()["id"]
    uploaded = await admin.post(
        f"/members/{member_id}/avatar", files={"file": ("a.jpg", IMAGE, "image/jpeg")}
    )
    assert uploaded.status_code == 200
    return uploaded.json()["avatar_url"], admin, member_id


async def test_the_owner_tree_can_fetch_the_image(avatar, make_client):
    url, admin, _ = avatar
    response = await admin.get(url)
    assert response.status_code == 200
    assert response.content == IMAGE
    assert response.headers["content-type"] == "image/jpeg"
    assert "private" in response.headers["cache-control"]
    member = await signed_in(make_client, "member_a")
    assert (await member.get(url)).status_code == 200


async def test_another_tree_gets_404(avatar, make_client):
    url, *_ = avatar
    other = await signed_in(make_client, "admin_b")
    assert (await other.get(url)).status_code == 404


async def test_a_guest_cannot_fetch_from_a_private_tree(avatar, make_client):
    url, *_ = avatar
    assert (await make_client().get(url)).status_code == 404


async def test_a_guest_can_fetch_from_a_public_tree(avatar, make_client, session, world):
    url, *_ = avatar
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert (await make_client().get(url)).status_code == 200
    await set_setting(session, "visibility", "private", tree_id=world["tree_a"].id)
    assert (await make_client().get(url)).status_code == 404


async def test_the_superadmin_can_fetch_from_any_tree(avatar, make_client):
    url, *_ = avatar
    root = await signed_in(make_client, "root")
    assert (await root.get(url)).status_code == 200


async def test_a_disabled_account_is_treated_like_a_stranger(avatar, make_client, session):
    url, *_ = avatar
    member = await signed_in(make_client, "member_a")
    await set_user(session, "member_a@example.com", status="disabled")
    assert (await member.get(url)).status_code == 404


async def test_unknown_malformed_and_orphan_names_are_404(avatar, make_client, upload_dir):
    _, admin, _ = avatar
    (upload_dir / "avatars" / "00000000-0000-0000-0000-000000000000.jpg").write_bytes(b"orphan")
    for name in (
        "00000000-0000-0000-0000-000000000000.jpg",  # a file on disk that no member points at
        "11111111-1111-1111-1111-111111111111.jpg",  # not on disk at all
        "..%2F..%2Fetc%2Fpasswd",
        "not-a-uuid.jpg",
        "00000000-0000-0000-0000-000000000000.exe",
    ):
        assert (await admin.get(f"/uploads/avatars/{name}")).status_code == 404, name
    assert (await admin.get("/uploads/")).status_code == 404
    assert (await admin.get("/uploads/avatars/")).status_code == 404


async def test_a_replaced_or_removed_avatar_is_no_longer_served(avatar):
    url, admin, member_id = avatar
    second = await admin.post(f"/members/{member_id}/avatar", files={"file": ("b.png", IMAGE, "image/png")})
    new_url = second.json()["avatar_url"]
    assert (await admin.get(url)).status_code == 404
    assert (await admin.get(new_url)).status_code == 200
    assert (await admin.delete(f"/members/{member_id}/avatar")).status_code == 204
    assert (await admin.get(new_url)).status_code == 404
