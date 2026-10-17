"""GĐ11: privacy per field - who may see phone, email, residence, notes, burial, avatar, hometown."""

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


def guest_of(make_client, slug="ho-a"):
    c = make_client()
    c.cookies.set("tree_slug", slug)
    return c


@pytest.fixture
async def setup(world, make_client, session):
    admin = await signed_in(make_client, "admin_a")
    place = (await admin.post("/places", json={"kind": "tomb", "name": "Nghĩa trang Phú Ốc"})).json()
    r = await admin.post(
        "/members",
        json={
            "full_name": "Nguyễn Văn Tổ", "gender": "male", "birth_year": 1900, "hometown": "Huế", "residence": "Đà Nẵng",
            "phone": "0912345678", "email": "to@example.com", "notes": "ghi chú riêng", "burial_place": "Phú Ốc",
            "burial_latitude": 16.4, "burial_longitude": 107.6, "burial_place_id": place["id"], "burial_plot": "Khu B",
        },
    )
    to = r.json()["id"]
    await admin.post(f"/members/{to}/marriages", json={"spouse_full_name": "Trần Thị Lan", "spouse_notes": "ghi chú của bà"})
    buffer = io.BytesIO()
    Image.new("RGB", (100, 100), "teal").save(buffer, "PNG")
    avatar = (await admin.post(f"/members/{to}/avatar", files={"file": ("a.png", buffer.getvalue(), "image/png")})).json()
    member = await signed_in(make_client, "member_a")
    await set_setting(session, "visibility", "public", tree_id=world["tree_a"].id)
    return {"admin": admin, "member": member, "guest": guest_of(make_client), "to": to, "avatar": avatar["avatar_url"], "make_client": make_client}


async def detail(c, member_id):
    r = await c.get(f"/members/{member_id}")
    assert r.status_code == 200, r.text
    return r.json()


async def set_privacy(admin, **levels):
    r = await admin.put("/admin/privacy", json=levels)
    assert r.status_code == 200, r.text
    return r.json()


async def test_defaults_keep_the_behaviour_from_before(setup):
    admin_view = await detail(setup["admin"], setup["to"])
    member_view = await detail(setup["member"], setup["to"])
    guest_view = await detail(setup["guest"], setup["to"])
    for key in ("phone", "email", "residence", "notes", "burial_place", "burial_plot", "avatar_url"):
        assert member_view[key] == admin_view[key] and member_view[key], key
    assert guest_view["hometown"] == "Huế" and guest_view["avatar_url"] == admin_view["avatar_url"]
    for key in ("phone", "email", "residence", "notes", "burial_place", "burial_plot", "burial_place_id"):
        assert not guest_view[key], key
    assert guest_view["resting_place"] is None
    assert (await setup["admin"].get("/admin/privacy")).json()["fields"] == {
        "phone": "member", "email": "member", "residence": "member", "notes": "member", "burial": "member", "avatar": "public", "hometown": "public",
    }


async def test_a_field_set_to_admin_is_hidden_from_members_only(setup):
    await set_privacy(setup["admin"], phone="admin")
    member_view = await detail(setup["member"], setup["to"])
    assert member_view["phone"] is None and member_view["email"] == "to@example.com"
    assert (await detail(setup["admin"], setup["to"]))["phone"] == "0912345678"


async def test_a_field_set_to_public_reaches_guests_of_a_public_tree(setup, session, world):
    await set_privacy(setup["admin"], phone="public", residence="public")
    guest_view = await detail(setup["guest"], setup["to"])
    assert guest_view["phone"] == "0912345678" and guest_view["residence"] == "Đà Nẵng" and guest_view["email"] is None
    await set_setting(session, "visibility", "private", tree_id=world["tree_a"].id)
    assert (await setup["guest"].get(f"/members/{setup['to']}")).status_code == 401  # public level never opens a private tree


async def test_hometown_can_be_closed(setup):
    await set_privacy(setup["admin"], hometown="member")
    assert (await detail(setup["guest"], setup["to"]))["hometown"] is None
    assert (await detail(setup["member"], setup["to"]))["hometown"] == "Huế"
    await set_privacy(setup["admin"], hometown="admin")
    assert (await detail(setup["member"], setup["to"]))["hometown"] is None


async def test_notes_level_also_covers_the_spouses_notes(setup):
    member_view = await detail(setup["member"], setup["to"])
    assert member_view["notes"] == "ghi chú riêng" and member_view["spouses"][0]["notes"] == "ghi chú của bà"
    assert (await detail(setup["guest"], setup["to"]))["spouses"][0]["notes"] is None  # was leaking before GĐ11
    await set_privacy(setup["admin"], notes="admin")
    hidden = await detail(setup["member"], setup["to"])
    assert hidden["notes"] is None and hidden["spouses"][0]["notes"] is None
    assert (await detail(setup["admin"], setup["to"]))["spouses"][0]["notes"] == "ghi chú của bà"


async def test_burial_level_hides_the_whole_resting_place(setup):
    await set_privacy(setup["admin"], burial="admin")
    view = await detail(setup["member"], setup["to"])
    assert view["resting_place"] is None
    for key in ("burial_place", "burial_latitude", "burial_longitude", "burial_place_id", "burial_plot"):
        assert view[key] is None, key
    assert (await detail(setup["admin"], setup["to"]))["resting_place"]["name"] == "Nghĩa trang Phú Ốc"


async def test_avatar_level_governs_the_file_too(setup):
    url = setup["avatar"]
    assert (await setup["member"].get(url)).status_code == 200
    assert (await setup["guest"].get(url)).status_code == 200  # default: public (on a public tree)
    await set_privacy(setup["admin"], avatar="member")
    assert (await setup["guest"].get(url)).status_code == 404
    assert (await detail(setup["guest"], setup["to"]))["avatar_url"] is None
    assert (await setup["member"].get(url)).status_code == 200
    await set_privacy(setup["admin"], avatar="admin")
    assert (await detail(setup["member"], setup["to"]))["avatar_url"] is None
    assert (await setup["member"].get(url)).status_code == 404
    assert (await setup["admin"].get(url)).status_code == 200
    await set_privacy(setup["admin"], avatar="public")
    assert (await setup["guest"].get(url)).status_code == 200
    assert (await detail(setup["guest"], setup["to"]))["avatar_url"] == url


async def test_only_admins_read_or_change_the_levels(setup):
    assert (await setup["member"].get("/admin/privacy")).status_code == 403
    assert (await setup["member"].put("/admin/privacy", json={"phone": "public"})).status_code == 403
    assert (await setup["guest"].get("/admin/privacy")).status_code == 401


async def test_unknown_fields_and_levels_are_refused_and_updates_merge(setup):
    admin = setup["admin"]
    assert (await admin.put("/admin/privacy", json={"phone": "everyone"})).status_code == 422
    assert (await admin.put("/admin/privacy", json={"birth_year": "admin"})).status_code == 422
    await set_privacy(admin, phone="admin")
    result = await set_privacy(admin, email="admin")
    assert result["fields"]["phone"] == "admin" and result["fields"]["email"] == "admin" and result["fields"]["notes"] == "member"


async def test_levels_are_per_tree_and_audited(setup, world, make_client):
    await set_privacy(setup["admin"], phone="admin", email="public")
    admin_b = await signed_in(make_client, "admin_b")
    assert (await admin_b.get("/admin/privacy")).json()["fields"]["phone"] == "member"
    entries = (await setup["admin"].get("/audit")).json()
    entry = next(e for e in (entries["items"] if isinstance(entries, dict) else entries) if e["action"] == "privacy.update")
    assert entry["changes"] == {"phone": ["member", "admin"], "email": ["member", "public"]}


async def test_a_member_cannot_propose_a_field_they_cannot_see(setup):
    await set_privacy(setup["admin"], phone="admin")
    member, to = setup["member"], setup["to"]
    r = await member.post("/requests", json={"kind": "edit", "member_id": to, "changes": {"phone": "0999"}, "message": "số mới"})
    assert r.status_code == 422
    ok = await member.post("/requests", json={"kind": "edit", "member_id": to, "changes": {"email": "moi@example.com"}, "message": "email mới"})
    assert ok.status_code == 201


async def test_old_values_of_hidden_fields_vanish_from_a_members_view_of_requests(setup):
    member, admin, to = setup["member"], setup["admin"], setup["to"]
    r = await member.post("/requests", json={"kind": "edit", "member_id": to, "changes": {"phone": "0999", "hometown": "Hà Tĩnh"}, "message": "sửa"})
    assert r.status_code == 201
    request_id = r.json()["id"]
    await set_privacy(admin, phone="admin")  # tightened after the proposal
    seen = (await member.get(f"/requests/{request_id}")).json()
    assert "phone" not in seen["base"] and all(row["field"] != "phone" for row in seen["diff"])
    assert seen["base"]["hometown"] == "Huế"
    assert "0912345678" not in str(seen)
    full = (await admin.get(f"/requests/{request_id}")).json()
    assert full["base"]["phone"] == "0912345678"
    listing = (await member.get("/requests")).json()
    assert "0912345678" not in str(listing)
