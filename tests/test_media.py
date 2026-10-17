"""GĐ6: photos and documents on people and places, with thumbnails, access checks and cleanup."""

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


@pytest.fixture
async def admin(world, make_client):
    return await signed_in(make_client, "admin_a")


def image_bytes(fmt="PNG", size=(1200, 800), color="red") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
CONTENT = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


async def member_id(c, name="Ông A"):
    return (await c.post("/members", json={"full_name": name})).json()["id"]


async def upload(c, owner, fmt="PNG", caption=None, kind="members", **kw):
    data = kw.pop("data", None)
    if data is None:
        data = image_bytes(fmt)
    content_type = kw.pop("content_type", CONTENT.get(fmt, "image/png"))
    files = {"file": (kw.pop("filename", f"scan.{fmt.lower()}"), data, content_type)}
    return await c.post(f"/{kind}/{owner}/media", files=files, data={"caption": caption} if caption else None)


# ------------------------------------------------------------------ uploading


async def test_an_image_gets_metadata_and_a_thumbnail(admin, upload_dir):
    owner = await member_id(admin)
    r = await upload(admin, owner, caption="Ảnh cưới 1950")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "image" and body["caption"] == "Ảnh cưới 1950" and body["member_id"] == owner and body["place_id"] is None
    assert (body["width"], body["height"]) == (1200, 800) and body["original_name"] == "scan.png" and body["size"] > 0
    assert body["url"].startswith("/uploads/media/") and body["thumb_url"].startswith("/uploads/media/thumbs/")
    original = await admin.get(body["url"])
    assert original.status_code == 200 and original.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(original.content)).size == (1200, 800)
    thumb = await admin.get(body["thumb_url"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg" and "private" in thumb.headers["cache-control"]
    assert max(Image.open(io.BytesIO(thumb.content)).size) <= 480
    assert len(list((upload_dir / "media").iterdir())) == 2  # the original and the thumbs folder
    assert len(list((upload_dir / "media" / "thumbs").iterdir())) == 1


@pytest.mark.parametrize("fmt", ["JPEG", "WEBP"])
async def test_other_image_formats(admin, fmt):
    owner = await member_id(admin)
    r = await upload(admin, owner, fmt)
    assert r.status_code == 201 and r.json()["kind"] == "image"


async def test_a_pdf_is_a_document_without_a_thumbnail(admin):
    owner = await member_id(admin)
    r = await upload(admin, owner, data=PDF, content_type="application/pdf", filename="giay-khai-sinh.pdf")
    assert r.status_code == 201
    body = r.json()
    assert body["kind"] == "document" and body["thumb_url"] is None and body["width"] is None
    fetched = await admin.get(body["url"])
    assert fetched.headers["content-type"] == "application/pdf" and fetched.content == PDF


async def test_the_content_is_checked_not_just_the_declared_type(admin):
    owner = await member_id(admin)
    assert (await upload(admin, owner, data=b"just some text", content_type="image/png")).status_code == 400  # not an image
    assert (await upload(admin, owner, data=b"<html></html>", content_type="application/pdf")).status_code == 400  # not a pdf
    assert (await upload(admin, owner, data=b"hello", content_type="text/plain", filename="a.txt")).status_code == 400  # type not allowed
    assert (await upload(admin, owner, data=PDF, content_type="image/png")).status_code == 400  # a pdf pretending to be an image
    assert (await upload(admin, owner, data=b"", content_type="image/png")).status_code == 400
    assert (await admin.get(f"/members/{owner}/media")).json() == []  # nothing half-saved


async def test_size_limit(admin):
    owner = await member_id(admin)
    big = b"%PDF-" + b"0" * (10 * 1024 * 1024)
    assert (await upload(admin, owner, data=big, content_type="application/pdf")).status_code == 400


async def test_only_admins_upload_edit_and_delete(world, admin, make_client):
    owner = await member_id(admin)
    media = (await upload(admin, owner)).json()
    viewer = await signed_in(make_client, "member_a")
    assert (await upload(viewer, owner)).status_code == 403
    assert (await viewer.patch(f"/media/{media['id']}", json={"caption": "x"})).status_code == 403
    assert (await viewer.delete(f"/media/{media['id']}")).status_code == 403
    assert (await make_client().post(f"/members/{owner}/media", files={"file": ("a.png", image_bytes(), "image/png")})).status_code == 401


async def test_upload_to_an_unknown_or_foreign_owner(world, admin, make_client):
    other = await signed_in(make_client, "admin_b")
    foreign_member = await member_id(other, "Người họ B")
    assert (await upload(admin, 99999)).status_code == 404
    assert (await upload(admin, foreign_member)).status_code == 404
    assert (await upload(admin, 99999, kind="places")).status_code == 404


# ------------------------------------------------------------------ listing, caption, delete


async def test_list_caption_and_delete(admin, upload_dir):
    owner = await member_id(admin)
    first = (await upload(admin, owner, caption="Một")).json()
    second = (await upload(admin, owner, caption="Hai")).json()
    listed = (await admin.get(f"/members/{owner}/media")).json()
    assert [m["caption"] for m in listed] == ["Một", "Hai"]
    changed = await admin.patch(f"/media/{first['id']}", json={"caption": "  Ảnh chân dung  "})
    assert changed.status_code == 200 and changed.json()["caption"] == "Ảnh chân dung"
    assert (await admin.patch(f"/media/{first['id']}", json={"caption": None})).json()["caption"] is None
    assert (await admin.delete(f"/media/{first['id']}")).status_code == 204
    assert (await admin.get(first["url"])).status_code == 404
    assert (await admin.get(first["thumb_url"])).status_code == 404
    assert [m["id"] for m in (await admin.get(f"/members/{owner}/media")).json()] == [second["id"]]
    assert (await admin.delete(f"/media/{first['id']}")).status_code == 404
    assert len(list((upload_dir / "media" / "thumbs").iterdir())) == 1


async def test_deleting_the_person_or_place_removes_their_files(admin, upload_dir):
    owner = await member_id(admin, "Sẽ xoá")
    await upload(admin, owner)
    place = (await admin.post("/places", json={"kind": "tomb", "name": "Lăng"})).json()
    await upload(admin, place["id"], kind="places")
    assert len(list((upload_dir / "media" / "thumbs").iterdir())) == 2
    assert (await admin.delete(f"/members/{owner}")).status_code == 204
    assert (await admin.delete(f"/places/{place['id']}")).status_code == 204
    assert [p.name for p in (upload_dir / "media").iterdir() if p.is_file()] == []
    assert list((upload_dir / "media" / "thumbs").iterdir()) == []


async def test_place_media(admin):
    place = (await admin.post("/places", json={"kind": "clan_house", "name": "Nhà thờ"})).json()
    r = await upload(admin, place["id"], kind="places", caption="Mặt tiền")
    assert r.status_code == 201 and r.json()["place_id"] == place["id"] and r.json()["member_id"] is None
    assert [m["caption"] for m in (await admin.get(f"/places/{place['id']}/media")).json()] == ["Mặt tiền"]
    assert (await admin.get(f"/places/{place['id']}")).json()["media_count"] == 1


# ------------------------------------------------------------------ who can see the files


async def test_signed_in_family_members_see_media_others_do_not(world, admin, make_client, session):
    owner = await member_id(admin)
    media = (await upload(admin, owner)).json()
    viewer = await signed_in(make_client, "member_a")
    assert (await viewer.get(media["url"])).status_code == 200 and (await viewer.get(media["thumb_url"])).status_code == 200
    assert len((await viewer.get(f"/members/{owner}/media")).json()) == 1
    other = await signed_in(make_client, "admin_b")
    assert (await other.get(media["url"])).status_code == 404
    assert (await other.get(f"/members/{owner}/media")).status_code == 404
    # a guest of a PUBLIC tree sees neither the list nor the files
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert (await guest.get(media["url"])).status_code == 404
    assert (await guest.get(f"/members/{owner}/media")).status_code == 401


async def test_unknown_or_malformed_file_names_are_404(admin, upload_dir):
    (upload_dir / "media").mkdir(exist_ok=True)
    (upload_dir / "media" / "00000000-0000-0000-0000-000000000000.png").write_bytes(b"orphan")
    for path in (
        "/uploads/media/00000000-0000-0000-0000-000000000000.png",  # on disk, no row
        "/uploads/media/11111111-1111-1111-1111-111111111111.png",
        "/uploads/media/..%2Fetc%2Fpasswd",
        "/uploads/media/not-a-name.png",
        "/uploads/media/thumbs/00000000-0000-0000-0000-000000000000.jpg",
        "/uploads/media/",
    ):
        assert (await admin.get(path)).status_code == 404, path


async def test_media_changes_are_audited(admin):
    owner = await member_id(admin, "Ông A")
    media = (await upload(admin, owner, caption="x")).json()
    await admin.patch(f"/media/{media['id']}", json={"caption": "y"})
    await admin.delete(f"/media/{media['id']}")
    entries = (await admin.get("/audit", params={"member_id": owner})).json()["items"]
    assert [e["action"] for e in entries][:3] == ["media.delete", "media.update", "media.upload"]
    assert entries[2]["details"]["original_name"] == "scan.png"
