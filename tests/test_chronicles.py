"""GĐ7: articles (sử ký, tộc ước...), the timeline and the generation words (bài đệm)."""

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


async def add(c, name, parent_id=None, **extra):
    r = await c.post("/members", json={"full_name": name, "parent_id": parent_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def article(c, title="Nguồn gốc dòng họ", **extra):
    body = {"title": title, "kind": "origin", "body": "# Xưa\n\nTổ tiên từ **Nghệ An**.", "status": "published", **extra}
    r = await c.post("/articles", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), "navy").save(buffer, "PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------ articles


async def test_admin_writes_and_readers_read_published_articles(admin, make_client):
    made = await article(admin)
    assert made["slug"] == "nguon-goc-dong-ho" and made["kind"] == "origin" and made["pinned"] is False
    assert made["body"].startswith("# Xưa")
    member = await signed_in(make_client, "member_a")
    listed = (await member.get("/articles")).json()
    assert [a["title"] for a in listed] == ["Nguồn gốc dòng họ"]
    assert "body" not in listed[0] and listed[0]["excerpt"].startswith("Xưa")  # the list carries an excerpt, not the text
    full = (await member.get(f"/articles/{made['id']}")).json()
    assert full["body"].startswith("# Xưa")
    assert (await member.get("/articles/by-slug/nguon-goc-dong-ho")).json()["id"] == made["id"]
    assert (await member.post("/articles", json={"title": "x", "kind": "other", "body": "y"})).status_code == 403
    assert (await member.put(f"/articles/{made['id']}", json={"title": "x", "kind": "other", "body": "y"})).status_code == 403
    assert (await member.delete(f"/articles/{made['id']}")).status_code == 403


async def test_slugs_are_unique_per_tree_and_stable(admin, world, make_client):
    first = await article(admin, "Tộc ước")
    second = await article(admin, "Tộc ước")
    third = await article(admin, "Tộc  ƯỚC!!")
    assert [first["slug"], second["slug"], third["slug"]] == ["toc-uoc", "toc-uoc-2", "toc-uoc-3"]
    renamed = (await admin.put(f"/articles/{first['id']}", json={"title": "Tộc ước (bản mới)", "kind": "precepts", "body": "x", "status": "published"})).json()
    assert renamed["slug"] == "toc-uoc"  # a link to the article keeps working after a rename
    other = await signed_in(make_client, "admin_b")
    assert (await article(other, "Tộc ước"))["slug"] == "toc-uoc"  # another family has its own namespace
    assert (await admin.post("/articles", json={"title": "!!!", "kind": "other", "body": "x"})).json()["slug"].startswith("bai-viet")


async def test_drafts_are_for_admins_only(admin, make_client):
    draft = await article(admin, "Bản nháp", status="draft")
    member = await signed_in(make_client, "member_a")
    assert (await member.get("/articles")).json() == []
    assert (await member.get(f"/articles/{draft['id']}")).status_code == 404
    assert (await member.get("/articles/by-slug/ban-nhap")).status_code == 404
    assert [a["title"] for a in (await admin.get("/articles")).json()] == ["Bản nháp"]
    assert (await admin.get(f"/articles/{draft['id']}")).status_code == 200


async def test_guests_read_published_articles_of_a_public_tree_only(world, admin, make_client, session):
    pub = await article(admin, "Công khai")
    await article(admin, "Nháp", status="draft")
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    assert (await guest.get("/articles")).status_code == 401  # private tree
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert [a["title"] for a in (await guest.get("/articles")).json()] == ["Công khai"]
    assert (await guest.get(f"/articles/{pub['id']}")).status_code == 200
    assert (await guest.get("/articles/by-slug/nhap")).status_code == 404


async def test_ordering_pinned_then_position_then_newest(admin):
    a = await article(admin, "A")
    b = await article(admin, "B")
    c = await article(admin, "C", pinned=True)
    assert [x["title"] for x in (await admin.get("/articles")).json()] == ["C", "B", "A"]  # pinned first, then newest
    done = await admin.post("/articles/reorder", json={"ids": [a["id"], b["id"], c["id"]]})
    assert done.status_code == 204
    assert [x["title"] for x in (await admin.get("/articles")).json()] == ["C", "A", "B"]  # pinned still first, then the new order
    assert (await admin.post("/articles/reorder", json={"ids": [a["id"], 99999]})).status_code == 404


async def test_kind_filter_and_validation(admin):
    await article(admin, "Gốc", kind="origin")
    await article(admin, "Ước", kind="precepts")
    assert [a["title"] for a in (await admin.get("/articles", params={"kind": "precepts"})).json()] == ["Ước"]
    assert (await admin.get("/articles", params={"kind": "poem"})).status_code == 422
    ok = {"title": "T", "kind": "other", "body": "x"}
    assert (await admin.post("/articles", json={**ok, "title": "  "})).status_code == 422
    assert (await admin.post("/articles", json={**ok, "kind": "novel"})).status_code == 422
    assert (await admin.post("/articles", json={**ok, "status": "secret"})).status_code == 422
    assert (await admin.post("/articles", json={**ok, "body": "x" * 100_001})).status_code == 422


async def test_articles_mention_people_and_profiles_list_them(admin, make_client):
    root = await add(admin, "Tổ")
    kid = await add(admin, "Con", root)
    made = await article(admin, "Chuyện ông Tổ", kind="person", member_ids=[root, kid, kid])
    assert sorted(m["id"] for m in made["members"]) == [root, kid]
    assert {m["name"] for m in made["members"]} == {"Tổ", "Con"}
    draft = await article(admin, "Nháp về Con", status="draft", member_ids=[kid])
    member = await signed_in(make_client, "member_a")
    mentioned = (await member.get(f"/members/{kid}/articles")).json()
    assert [a["title"] for a in mentioned] == ["Chuyện ông Tổ"]  # the draft is not shown to members
    assert sorted(a["title"] for a in (await admin.get(f"/members/{kid}/articles")).json()) == ["Chuyện ông Tổ", "Nháp về Con"]
    assert draft["id"]
    again = (await admin.put(f"/articles/{made['id']}", json={"title": "Chuyện ông Tổ", "kind": "person", "body": "x", "status": "published", "member_ids": [root]})).json()
    assert [m["id"] for m in again["members"]] == [root]
    assert [a["title"] for a in (await member.get(f"/members/{kid}/articles")).json()] == []


async def test_mentions_must_be_people_of_the_same_tree(world, admin, make_client):
    other = await signed_in(make_client, "admin_b")
    foreign = await add(other, "Người họ B")
    r = await admin.post("/articles", json={"title": "T", "kind": "other", "body": "x", "member_ids": [foreign]})
    assert r.status_code == 404
    assert (await admin.post("/articles", json={"title": "T", "kind": "other", "body": "x", "member_ids": [99999]})).status_code == 404
    assert (await admin.get(f"/members/{foreign}/articles")).status_code == 404


async def test_cover_and_images_come_from_the_articles_own_media(admin, upload_dir, make_client):
    made = await article(admin, "Có ảnh")
    uploaded = await admin.post(f"/articles/{made['id']}/media", files={"file": ("a.png", png(), "image/png")}, data={"caption": "Nhà thờ"})
    assert uploaded.status_code == 201 and uploaded.json()["article_id"] == made["id"] and uploaded.json()["member_id"] is None
    media_id = uploaded.json()["id"]
    assert (await admin.get(f"/articles/{made['id']}/media")).json()[0]["id"] == media_id
    set_cover = await admin.put(f"/articles/{made['id']}", json={"title": "Có ảnh", "kind": "origin", "body": "x", "status": "published", "cover_media_id": media_id})
    assert set_cover.status_code == 200 and set_cover.json()["cover_url"].startswith("/uploads/media/thumbs/")
    other_article = await article(admin, "Khác")
    foreign_cover = await admin.put(f"/articles/{other_article['id']}", json={"title": "Khác", "kind": "origin", "body": "x", "status": "published", "cover_media_id": media_id})
    assert foreign_cover.status_code == 404  # a cover must be one of the article's own images
    viewer = await signed_in(make_client, "member_a")
    assert (await viewer.get(uploaded.json()["url"])).status_code == 200
    assert len((await viewer.get(f"/articles/{made['id']}/media")).json()) == 1
    assert (await viewer.post(f"/articles/{made['id']}/media", files={"file": ("a.png", png(), "image/png")})).status_code == 403
    # deleting the article removes its files and rows
    assert (await admin.delete(f"/articles/{made['id']}")).status_code == 204
    assert [p for p in (upload_dir / "media").iterdir() if p.is_file()] == []
    assert (await admin.get(f"/articles/{made['id']}")).status_code == 404


async def test_deleting_the_cover_image_clears_the_cover(admin):
    made = await article(admin, "Có ảnh")
    media = (await admin.post(f"/articles/{made['id']}/media", files={"file": ("a.png", png(), "image/png")})).json()
    await admin.put(f"/articles/{made['id']}", json={"title": "Có ảnh", "kind": "origin", "body": "x", "status": "published", "cover_media_id": media["id"]})
    assert (await admin.delete(f"/media/{media['id']}")).status_code == 204
    assert (await admin.get(f"/articles/{made['id']}")).json()["cover_url"] is None


async def test_trees_are_isolated(world, admin, make_client):
    made = await article(admin)
    other = await signed_in(make_client, "admin_b")
    assert (await other.get("/articles")).json() == []
    assert (await other.get(f"/articles/{made['id']}")).status_code == 404
    assert (await other.put(f"/articles/{made['id']}", json={"title": "x", "kind": "other", "body": "y"})).status_code == 404
    assert (await other.delete(f"/articles/{made['id']}")).status_code == 404


async def test_article_changes_are_audited(admin):
    made = await article(admin, "Tộc ước", kind="precepts")
    await admin.put(f"/articles/{made['id']}", json={"title": "Tộc ước", "kind": "precepts", "body": "đã sửa", "status": "published"})
    await admin.delete(f"/articles/{made['id']}")
    entries = (await admin.get("/audit")).json()["items"][:3]
    assert [e["action"] for e in entries] == ["article.delete", "article.update", "article.create"]
    assert entries[1]["changes"]["body"][1] == "đã sửa" and entries[1]["details"]["title"] == "Tộc ước"


# ------------------------------------------------------------------ timeline


async def test_timeline_crud_ordering_and_links(admin, make_client):
    root = await add(admin, "Tổ")
    art = await article(admin, "Cuộc di cư")
    later = await admin.post("/timeline", json={"year": 1950, "title": "Xây nhà thờ", "body": "Cả họ góp công"})
    earlier = await admin.post("/timeline", json={"year": 1820, "month": 3, "day": 5, "title": "Tổ khai khẩn", "member_id": root, "article_id": art["id"]})
    same_year = await admin.post("/timeline", json={"year": 1950, "month": 2, "title": "Lễ khánh thành"})
    assert later.status_code == earlier.status_code == same_year.status_code == 201
    member = await signed_in(make_client, "member_a")
    rows = (await member.get("/timeline")).json()
    assert [r["title"] for r in rows] == ["Tổ khai khẩn", "Xây nhà thờ", "Lễ khánh thành"]  # a year without month sorts before dated ones
    assert rows[0]["member_name"] == "Tổ" and rows[0]["article_id"] == art["id"]
    entry = rows[1]
    assert (await member.post("/timeline", json={"year": 1, "title": "x"})).status_code == 403
    changed = await admin.put(f"/timeline/{entry['id']}", json={"year": 1951, "title": "Xây xong nhà thờ"})
    assert changed.status_code == 200 and changed.json()["body"] is None  # PUT replaces
    assert (await admin.delete(f"/timeline/{entry['id']}")).status_code == 204
    assert (await admin.delete(f"/timeline/{entry['id']}")).status_code == 404


async def test_timeline_validation_and_isolation(world, admin, make_client):
    assert (await admin.post("/timeline", json={"year": 1950, "title": " "})).status_code == 422
    assert (await admin.post("/timeline", json={"year": 0, "title": "x"})).status_code == 422
    assert (await admin.post("/timeline", json={"year": 1950, "month": 13, "title": "x"})).status_code == 422
    assert (await admin.post("/timeline", json={"year": 1950, "day": 5, "title": "x"})).status_code == 422  # a day needs its month
    assert (await admin.post("/timeline", json={"year": 1950, "month": 2, "day": 31, "title": "x"})).status_code == 422
    other = await signed_in(make_client, "admin_b")
    foreign = await add(other, "Người họ B")
    assert (await admin.post("/timeline", json={"year": 1950, "title": "x", "member_id": foreign})).status_code == 404
    mine = (await admin.post("/timeline", json={"year": 1950, "title": "Việc của họ A"})).json()
    assert (await other.get("/timeline")).json() == []
    assert (await other.delete(f"/timeline/{mine['id']}")).status_code == 404


async def test_timeline_for_guests_follows_visibility(world, admin, make_client, session):
    await admin.post("/timeline", json={"year": 1950, "title": "Xây nhà thờ"})
    guest = make_client()
    guest.cookies.set("tree_slug", "ho-a")
    assert (await guest.get("/timeline")).status_code == 401
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    assert len((await guest.get("/timeline")).json()) == 1


# ------------------------------------------------------------------ generation words


async def test_generation_words_are_replaced_as_a_whole(admin, make_client):
    assert (await admin.get("/generation-poem")).json() == []
    put = await admin.put("/generation-poem", json={"words": [
        {"generation": 3, "word": "Đình", "meaning": "sân đình"},
        {"generation": 1, "word": "Văn"},
        {"generation": 2, "word": "Đức", "meaning": " "},
    ]})
    assert put.status_code == 200
    assert [(w["generation"], w["word"], w["meaning"]) for w in put.json()] == [(1, "Văn", None), (2, "Đức", None), (3, "Đình", "sân đình")]
    member = await signed_in(make_client, "member_a")
    assert [w["word"] for w in (await member.get("/generation-poem")).json()] == ["Văn", "Đức", "Đình"]
    assert (await member.put("/generation-poem", json={"words": []})).status_code == 403
    replaced = await admin.put("/generation-poem", json={"words": [{"generation": 2, "word": "Quang"}]})
    assert [w["word"] for w in replaced.json()] == ["Quang"]
    assert (await admin.put("/generation-poem", json={"words": []})).json() == []


async def test_generation_words_validation_and_isolation(world, admin, make_client):
    assert (await admin.put("/generation-poem", json={"words": [{"generation": 1, "word": "A"}, {"generation": 1, "word": "B"}]})).status_code == 422
    assert (await admin.put("/generation-poem", json={"words": [{"generation": 0, "word": "A"}]})).status_code == 422
    assert (await admin.put("/generation-poem", json={"words": [{"generation": 1, "word": " "}]})).status_code == 422
    assert (await admin.put("/generation-poem", json={"words": [{"generation": g, "word": "x"} for g in range(1, 202)]})).status_code == 422
    await admin.put("/generation-poem", json={"words": [{"generation": 1, "word": "Văn"}]})
    other = await signed_in(make_client, "admin_b")
    assert (await other.get("/generation-poem")).json() == []
