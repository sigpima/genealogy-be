"""GĐ10 J2: the "quyển phả" PDF."""

import io
import time

import pytest
from PIL import Image
from pypdf import PdfReader

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ Nguyễn", "ho-nguyen")
    tree_b = await create_tree(session, "Họ Khác", "ho-khac")
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
    ids = {"admin": admin, "mk": make_client}
    place = (await admin.post("/places", json={"kind": "tomb", "name": "Nghĩa trang Phú Ốc"})).json()
    ids["to"] = await add(
        admin, "Nguyễn Văn Tổ", gender="male", birth_year=1900, death_year=1970, death_month=8, death_day=15, death_is_lunar=True,
        hometown="Huế", notes="Khai khẩn vùng đất Phú Ốc", burial_place_id=place["id"], burial_plot="Khu B, mộ 3", courtesy_name="Phúc Khang",
    )
    await admin.post(f"/members/{ids['to']}/marriages", json={"spouse_full_name": "Trần Thị Lan", "marriage_year": 1925})
    ids["a"] = await add(admin, "Nguyễn Văn An", ids["to"], gender="male", birth_year=1925, phone="0912345678", email="an@example.com")
    ids["b"] = await add(admin, "Nguyễn Thị Bình", ids["to"], gender="female", birth_year=1930, notes="Người giữ gia phả")
    ids["a1"] = await add(admin, "Nguyễn Văn Anh", ids["a"], birth_year=1950)
    await admin.post("/branches", json={"name": "Chi An", "root_member_id": ids["a"]})
    await admin.post("/articles", json={"title": "Tộc ước dòng họ Nguyễn", "kind": "precepts", "status": "published", "body": "# Điều một\n\nCon cháu **luôn nhớ** nguồn cội & hiếu thảo.\n\n- Đoàn kết\n- Học hành\n\n> Uống nước nhớ nguồn"})
    await admin.post("/articles", json={"title": "Bản nháp bí mật", "kind": "other", "status": "draft", "body": "chưa công bố"})
    await admin.post("/timeline", json={"year": 1950, "title": "Xây nhà thờ họ"})
    await admin.put("/generation-poem", json={"words": [{"generation": 2, "word": "Văn", "meaning": "văn hay"}]})
    buffer = io.BytesIO()
    Image.new("RGB", (300, 300), "teal").save(buffer, "PNG")
    await admin.post(f"/members/{ids['to']}/avatar", files={"file": ("a.png", buffer.getvalue(), "image/png")})
    return ids


async def book(c, **params):
    r = await c.get("/book.pdf", params=params)
    assert r.status_code == 200, r.text
    return r


def text_of(response) -> str:
    reader = PdfReader(io.BytesIO(response.content))
    return " ".join(" ".join((page.extract_text() or "").split()) for page in reader.pages)


def pages_of(response) -> int:
    return len(PdfReader(io.BytesIO(response.content)).pages)


async def test_the_book_is_a_real_pdf_named_after_the_family(family):
    r = await book(family["admin"])
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF-")
    assert "ho-nguyen" in r.headers["content-disposition"] and ".pdf" in r.headers["content-disposition"]
    assert pages_of(r) >= 5  # cover, contents, chronicles, generations, diagram


async def test_cover_contents_and_vietnamese_text(family):
    text = text_of(await book(family["admin"]))
    for expected in ("Họ Nguyễn", "Gia phả", "Mục lục", "Tộc ước dòng họ Nguyễn", "Phả hệ theo đời", "Đời 1", "Đời 2", "Đời 3", "Phả đồ"):
        assert expected in text, expected


async def test_chronicles_section(family):
    text = text_of(await book(family["admin"]))
    assert "Điều một" in text and "luôn nhớ" in text and "nguồn cội & hiếu thảo" in text  # markdown became text, & intact
    assert "Đoàn kết" in text and "Uống nước nhớ nguồn" in text
    assert "Xây nhà thờ họ" in text and "1950" in text  # the timeline
    assert "Chữ đệm" in text and "Văn" in text  # the bài đệm
    assert "Bản nháp bí mật" not in text and "chưa công bố" not in text  # drafts are never printed
    assert "Điều một" not in text_of(await book(family["admin"], chronicles="false"))


async def test_a_block_per_person(family):
    text = text_of(await book(family["admin"]))
    assert "Nguyễn Văn Tổ" in text and "Phúc Khang" in text and "Huế" in text
    assert "Trần Thị Lan" in text and "1925" in text  # the spouse and the marriage year
    assert "15/08 âm lịch" in text  # the giỗ
    assert "Nghĩa trang Phú Ốc" in text and "Khu B, mộ 3" in text
    assert "Con của Nguyễn Văn Tổ" in text
    assert "Chi An" in text


async def test_notes_and_contacts_are_options(family):
    default = text_of(await book(family["admin"]))
    assert "Khai khẩn vùng đất Phú Ốc" in default and "Người giữ gia phả" in default  # the biography is the point of the book
    assert "0912345678" not in default and "an@example.com" not in default  # contacts never printed unless asked
    assert "Khai khẩn vùng đất" not in text_of(await book(family["admin"], notes="false"))
    with_contacts = text_of(await book(family["admin"], contacts="true"))
    assert "0912345678" in with_contacts and "an@example.com" in with_contacts


async def test_profiles_and_diagram_switches(family):
    full = await book(family["admin"])
    no_diagram = await book(family["admin"], diagram="false")
    assert pages_of(no_diagram) < pages_of(full) and "Phả đồ" not in text_of(no_diagram)
    no_profiles = await book(family["admin"], profiles="false")
    assert "Phả hệ theo đời" not in text_of(no_profiles) and "Phả đồ" in text_of(no_profiles)


async def test_generation_limit(family):
    text = text_of(await book(family["admin"], max_generation=2))
    assert "Đời 2" in text and "Đời 3" not in text
    assert "Nguyễn Văn Anh" not in text  # the great-grandchild is cut off


async def test_photos_option_embeds_the_avatar(family):
    with_photos = await book(family["admin"], photos="true")
    without = await book(family["admin"], photos="false")
    reader = PdfReader(io.BytesIO(with_photos.content))
    images = sum(len(page.images) for page in reader.pages)
    assert images >= 1 and sum(len(p.images) for p in PdfReader(io.BytesIO(without.content)).pages) == 0


async def test_only_admins_and_only_their_own_family(world, family):
    member = await signed_in(family["mk"], "member_a")
    assert (await member.get("/book.pdf")).status_code == 403
    assert (await family["mk"]().get("/book.pdf")).status_code == 401
    other = await signed_in(family["mk"], "admin_b")
    await add(other, "Người họ Khác")
    text = text_of(await book(other))
    assert "Người họ Khác" in text and "Nguyễn Văn Tổ" not in text and "Tộc ước dòng họ Nguyễn" not in text


async def test_an_empty_tree_still_produces_a_book(world, family):
    other = await signed_in(family["mk"], "admin_b")
    r = await book(other)
    assert r.content.startswith(b"%PDF-") and "Họ Khác" in text_of(r)


async def test_the_export_is_audited(family):
    await book(family["admin"], notes="false")
    entry = (await family["admin"].get("/audit")).json()["items"][0]
    assert entry["action"] == "book.export" and entry["details"]["notes"] is False


async def test_big_tree_over_http(world, session, make_client):
    from app.models.member import Member

    tree = world["tree_a"]
    root = Member(tree_id=tree.id, full_name="Nguyễn Gốc")
    session.add(root)
    await session.flush()
    level, total = [root], 1
    while total < 700:
        nxt = []
        for parent in level:
            for _ in range(4):
                if total >= 700:
                    break
                child = Member(tree_id=tree.id, full_name=f"Nguyễn Văn Số{total}", parent_id=parent.id)
                session.add(child)
                nxt.append(child)
                total += 1
        await session.flush()
        level = nxt
    await session.commit()
    admin = await signed_in(make_client, "admin_a")
    started = time.monotonic()
    r = await admin.get("/book.pdf")
    assert r.status_code == 200
    assert time.monotonic() - started < 90
    assert pages_of(r) > 40
    assert "Nguyễn Văn Số699" in text_of(r)
