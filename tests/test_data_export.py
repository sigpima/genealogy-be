"""GĐ11: the full JSON export of a tree."""

import json

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


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
async def filled(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    to = (await admin.post("/members", json={"full_name": "Nguyễn Văn Tổ", "birth_year": 1900, "phone": "0912345678", "notes": "ghi chú"})).json()["id"]
    await admin.post(f"/members/{to}/marriages", json={"spouse_full_name": "Trần Thị Lan"})
    await admin.post("/branches", json={"name": "Chi Cả", "root_member_id": to})
    await admin.post("/articles", json={"title": "Bản nháp", "kind": "other", "status": "draft", "body": "chưa công bố"})
    await admin.post("/timeline", json={"year": 1950, "title": "Xây nhà thờ"})
    await admin.post("/places", json={"kind": "tomb", "name": "Nghĩa trang"})
    event = (await admin.post("/events", json={"title": "Giỗ Tổ", "kind": "memorial", "calendar": "solar", "month": 12, "day": 20, "year": 2024})).json()
    card = (await admin.post(f"/events/{event['id']}/cards", json={"date": "2024-12-20"})).json()
    await make_client().post(f"/invitations/{card['token']}/respond", json={"name": "Khách", "response": "yes", "party_size": 2})
    admin_b = await signed_in(make_client, "admin_b")
    await admin_b.post("/members", json={"full_name": "Người họ khác", "birth_year": 1950})
    return {"admin": admin, "member": await signed_in(make_client, "member_a"), "b": admin_b, "make_client": make_client}


async def test_the_export_holds_the_whole_tree(filled):
    r = await filled["admin"].get("/export/data.json")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and "ho-a" in r.headers["content-disposition"]
    data = json.loads(r.content)
    assert data["format_version"] == 1 and data["tree"]["slug"] == "ho-a"
    assert [m["full_name"] for m in data["members"]] == ["Nguyễn Văn Tổ", "Trần Thị Lan"]
    assert data["members"][0]["phone"] == "0912345678" and data["members"][0]["notes"] == "ghi chú"
    assert len(data["marriages"]) == 1 and data["branches"][0]["name"] == "Chi Cả"
    assert data["articles"][0]["status"] == "draft"  # the owner's copy keeps drafts
    assert data["timeline"][0]["title"] == "Xây nhà thờ" and data["places"][0]["name"] == "Nghĩa trang"
    assert data["privacy"]["phone"] == "member"


async def test_other_trees_data_and_secrets_never_appear(filled):
    text = (await filled["admin"].get("/export/data.json")).text
    assert "Người họ khác" not in text and "admin_b@example.com" not in text
    assert "hashed_password" not in text and "$2" not in text  # no password hashes
    users = json.loads(text)["users"]
    assert {u["email"] for u in users} == {"admin_a@example.com", "member_a@example.com"}


async def test_secret_tokens_are_left_out_but_the_answers_are_kept(filled):
    text = (await filled["admin"].get("/export/data.json")).text
    data = json.loads(text)
    assert len(data["event_cards"]) == 1 and data["event_rsvps"][0]["name"] == "Khách"
    for table in ("event_cards", "event_rsvps"):
        for row in data[table]:
            assert "token" not in row and "invitee_token" not in row
    card_token = (await filled["admin"].get("/events/1/cards")).json()[0]["token"]
    assert card_token not in text


async def test_only_admins_export_and_it_is_audited(filled, make_client):
    assert (await filled["member"].get("/export/data.json")).status_code == 403
    assert (await make_client().get("/export/data.json")).status_code == 401
    await filled["admin"].get("/export/data.json")
    entries = (await filled["admin"].get("/audit")).json()
    items = entries["items"] if isinstance(entries, dict) else entries
    assert any(e["action"] == "data.export" for e in items)


async def test_the_audit_log_is_included_on_request(filled):
    admin = filled["admin"]
    assert "audit_log" not in json.loads((await admin.get("/export/data.json")).text)
    with_audit = json.loads((await admin.get("/export/data.json", params={"include_audit": "true"})).text)
    assert len(with_audit["audit_log"]) >= 3
