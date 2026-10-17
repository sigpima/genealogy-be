"""GĐ9: invitation cards with a secret link and RSVPs, answered without logging in."""

import datetime
from datetime import date

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ Nguyễn", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [("admin_a", "admin", tree_a), ("member_a", "member", tree_a), ("admin_b", "admin", tree_b)]:
        await create_user(session, email=f"{key}@example.com", full_name=key, password=PASSWORD, role=role, tree=tree)
    return {"tree_a": tree_a, "tree_b": tree_b}


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


@pytest.fixture
async def setup(world, make_client, monkeypatch):
    monkeypatch.setattr("app.core.calendar_items.vn_today", lambda: date(2024, 9, 10))
    admin = await signed_in(make_client, "admin_a")
    place = (await admin.post("/places", json={"kind": "clan_house", "name": "Nhà thờ họ", "address": "Xã Phú Ốc", "latitude": 18.5, "longitude": 105.7})).json()
    event = (await admin.post("/events", json={
        "title": "Giỗ Tổ họ Nguyễn", "kind": "memorial", "calendar": "lunar", "month": 3, "day": 10, "repeats_yearly": True,
        "time_text": "08:00", "place_id": place["id"],
    })).json()
    one_off = (await admin.post("/events", json={"title": "Họp họ cuối năm", "kind": "gathering", "calendar": "solar", "month": 12, "day": 20, "year": 2024})).json()
    return {"admin": admin, "event": event, "one_off": one_off, "place": place, "mk": make_client}


async def make_card(c, event, day="2025-04-07", **extra):
    r = await c.post(f"/events/{event['id']}/cards", json={"date": day, "message": "Mời cả họ về dự", **extra})
    assert r.status_code == 201, r.text
    return r.json()


async def public(mk, token):
    return await mk().get(f"/invitations/{token}")


# ------------------------------------------------------------------ cards


async def test_an_admin_creates_a_card_for_an_occurrence(setup):
    admin = setup["admin"]
    card = await make_card(admin, setup["event"])
    assert card["date"] == "2025-04-07" and card["event_title"] == "Giỗ Tổ họ Nguyễn" and card["path"] == f"/thiep/{card['token']}"
    assert card["counts"] == {"yes": 0, "no": 0, "maybe": 0, "pending": 0, "people": 0} and card["closed"] is False
    assert len(card["token"]) >= 24
    listed = (await admin.get(f"/events/{setup['event']['id']}/cards")).json()
    assert [c["id"] for c in listed] == [card["id"]]


async def test_the_date_must_be_an_occurrence_of_the_event(setup):
    admin = setup["admin"]
    assert (await admin.post(f"/events/{setup['event']['id']}/cards", json={"date": "2025-04-08"})).status_code == 422  # giỗ Tổ 2025 is 7 April
    assert (await admin.post(f"/events/{setup['event']['id']}/cards", json={"date": "not-a-date"})).status_code == 422
    one = await admin.post(f"/events/{setup['one_off']['id']}/cards", json={"date": "2024-12-20"})
    assert one.status_code == 201
    assert (await admin.post(f"/events/{setup['one_off']['id']}/cards", json={"date": "2025-12-20"})).status_code == 422  # a one-off does not repeat
    assert (await admin.post("/events/99999/cards", json={"date": "2025-04-07"})).status_code == 404


async def test_only_admins_manage_cards_and_trees_are_isolated(setup, world):
    admin, mk = setup["admin"], setup["mk"]
    card = await make_card(admin, setup["event"])
    member = await signed_in(mk, "member_a")
    assert (await member.post(f"/events/{setup['event']['id']}/cards", json={"date": "2025-04-07"})).status_code == 403
    assert (await member.get(f"/cards/{card['id']}")).status_code == 403
    assert (await member.patch(f"/cards/{card['id']}", json={"closed": True})).status_code == 403
    assert (await member.delete(f"/cards/{card['id']}")).status_code == 403
    other = await signed_in(mk, "admin_b")
    assert (await other.get(f"/cards/{card['id']}")).status_code == 404
    assert (await other.post(f"/events/{setup['event']['id']}/cards", json={"date": "2025-04-07"})).status_code == 404
    assert (await other.delete(f"/cards/{card['id']}")).status_code == 404


async def test_update_close_and_delete(setup):
    admin = setup["admin"]
    card = await make_card(admin, setup["event"])
    changed = await admin.patch(f"/cards/{card['id']}", json={"message": "Lời mời mới", "closes_on": "2025-04-01", "closed": True})
    assert changed.status_code == 200 and changed.json()["message"] == "Lời mời mới" and changed.json()["closed"] is True and changed.json()["closes_on"] == "2025-04-01"
    assert (await admin.patch(f"/cards/{card['id']}", json={"closes_on": None})).json()["closes_on"] is None
    assert (await admin.delete(f"/cards/{card['id']}")).status_code == 204
    assert (await admin.get(f"/cards/{card['id']}")).status_code == 404
    assert (await public(setup["mk"], card["token"])).status_code == 404  # the link dies with the card


async def test_deleting_the_event_removes_its_cards(setup):
    admin = setup["admin"]
    card = await make_card(admin, setup["event"])
    assert (await admin.delete(f"/events/{setup['event']['id']}")).status_code == 204
    assert (await public(setup["mk"], card["token"])).status_code == 404


# ------------------------------------------------------------------ what a stranger sees


async def test_a_stranger_sees_the_card_without_logging_in(setup):
    card = await make_card(setup["admin"], setup["event"])
    r = await public(setup["mk"], card["token"])
    assert r.status_code == 200
    body = r.json()
    assert body["family"] == "Họ Nguyễn" and body["title"] == "Giỗ Tổ họ Nguyễn" and body["kind"] == "memorial"
    assert body["date"] == "2025-04-07" and body["lunar"] == {"day": 10, "month": 3, "year": 2025, "leap": False}
    assert body["time_text"] == "08:00" and body["message"] == "Mời cả họ về dự"
    assert body["place"] == {"name": "Nhà thờ họ", "address": "Xã Phú Ốc", "latitude": 18.5, "longitude": 105.7}
    assert body["closed"] is False and body["totals"] == {"yes": 0, "people": 0} and body["guest"] is None
    assert "responses" not in body and "token" not in body


async def test_unknown_tokens_are_404(setup):
    assert (await public(setup["mk"], "nope-nope-nope-nope-nope-nope")).status_code == 404
    assert (await setup["mk"]().post("/invitations/nope-nope-nope-nope-nope-nope/respond", json={"name": "A", "response": "yes"})).status_code == 404


# ------------------------------------------------------------------ answering through the open link


async def test_open_link_answers_create_responses_and_can_be_changed(setup):
    admin, mk = setup["admin"], setup["mk"]
    card = await make_card(admin, setup["event"])
    first = await mk().post(f"/invitations/{card['token']}/respond", json={"name": "  Nguyễn Văn Hai ", "response": "yes", "party_size": 3, "note": "Cả nhà về"})
    assert first.status_code == 200, first.text
    mine = first.json()
    assert mine["guest"]["name"] == "Nguyễn Văn Hai" and mine["guest"]["response"] == "yes" and mine["guest"]["party_size"] == 3 and mine["token"]
    await mk().post(f"/invitations/{card['token']}/respond", json={"name": "Trần Thị Ba", "response": "maybe"})
    await mk().post(f"/invitations/{card['token']}/respond", json={"name": "Lê Văn Tư", "response": "no"})
    shown = (await public(mk, card["token"])).json()
    assert shown["totals"] == {"yes": 1, "people": 3}  # only the count: never other guests' names
    assert "Nguyễn Văn Hai" not in str(shown) and "Cả nhà về" not in str(shown)
    # the guest comes back with the personal token and changes their mind
    again = await mk().post(f"/invitations/{mine['token']}/respond", json={"response": "yes", "party_size": 5})
    assert again.status_code == 200 and again.json()["guest"]["party_size"] == 5 and again.json()["guest"]["name"] == "Nguyễn Văn Hai"
    detail = (await admin.get(f"/cards/{card['id']}")).json()
    assert detail["counts"] == {"yes": 1, "no": 1, "maybe": 1, "pending": 0, "people": 5}
    assert sorted(r["name"] for r in detail["responses"]) == ["Lê Văn Tư", "Nguyễn Văn Hai", "Trần Thị Ba"]
    assert next(r for r in detail["responses"] if r["name"] == "Nguyễn Văn Hai")["note"] == "Cả nhà về"


async def test_answer_validation(setup):
    card = await make_card(setup["admin"], setup["event"])
    post = lambda body: setup["mk"]().post(f"/invitations/{card['token']}/respond", json=body)  # noqa: E731
    assert (await post({"response": "yes"})).status_code == 422  # the open link needs a name
    assert (await post({"name": "  ", "response": "yes"})).status_code == 422
    assert (await post({"name": "A", "response": "perhaps"})).status_code == 422
    assert (await post({"name": "A", "response": "yes", "party_size": 0})).status_code == 422
    assert (await post({"name": "A", "response": "yes", "party_size": 21})).status_code == 422
    assert (await post({"name": "A", "response": "yes", "note": "x" * 501})).status_code == 422
    assert (await post({"name": "x" * 151, "response": "yes"})).status_code == 422
    ok = await post({"name": "<b>Hai</b>", "response": "yes"})
    assert ok.status_code == 200 and ok.json()["guest"]["name"] == "<b>Hai</b>"  # stored as plain text; the page escapes it


async def test_a_no_answer_does_not_count_people(setup):
    admin, mk = setup["admin"], setup["mk"]
    card = await make_card(admin, setup["event"])
    await mk().post(f"/invitations/{card['token']}/respond", json={"name": "A", "response": "no", "party_size": 4})
    assert (await admin.get(f"/cards/{card['id']}")).json()["counts"]["people"] == 0


# ------------------------------------------------------------------ personal links


async def test_personal_invitations(setup):
    admin, mk = setup["admin"], setup["mk"]
    card = await make_card(admin, setup["event"])
    made = await admin.post(f"/cards/{card['id']}/invitees", json={"names": ["Ông Hai", " Bà Ba ", "Ông Hai", ""]})
    assert made.status_code == 201
    invitees = made.json()
    assert [i["name"] for i in invitees] == ["Ông Hai", "Bà Ba"]  # blanks and duplicates dropped
    assert all(i["response"] is None and i["personal_token"] and i["path"] == f"/thiep/{i['personal_token']}" for i in invitees)
    token = invitees[0]["personal_token"]
    greet = (await public(mk, token)).json()
    assert greet["guest"] == {"name": "Ông Hai", "response": None, "party_size": 1, "note": None}
    done = await mk().post(f"/invitations/{token}/respond", json={"response": "yes", "party_size": 2})
    assert done.status_code == 200 and done.json()["guest"]["response"] == "yes"
    counts = (await admin.get(f"/cards/{card['id']}")).json()["counts"]
    assert counts == {"yes": 1, "no": 0, "maybe": 0, "pending": 1, "people": 2}  # Bà Ba has not answered yet
    assert (await admin.post(f"/cards/{card['id']}/invitees", json={"names": []})).status_code == 422
    assert (await admin.post(f"/cards/{card['id']}/invitees", json={"names": ["x"] * 201})).status_code == 422


async def test_deleting_a_response(setup):
    admin, mk = setup["admin"], setup["mk"]
    card = await make_card(admin, setup["event"])
    mine = (await mk().post(f"/invitations/{card['token']}/respond", json={"name": "A", "response": "yes"})).json()
    detail = (await admin.get(f"/cards/{card['id']}")).json()
    rsvp_id = detail["responses"][0]["id"]
    assert (await admin.delete(f"/cards/{card['id']}/responses/{rsvp_id}")).status_code == 204
    assert (await admin.get(f"/cards/{card['id']}")).json()["responses"] == []
    assert (await admin.delete(f"/cards/{card['id']}/responses/{rsvp_id}")).status_code == 404
    assert (await mk().post(f"/invitations/{mine['token']}/respond", json={"response": "yes"})).status_code == 404  # its link died with it


# ------------------------------------------------------------------ closing


async def test_a_closed_card_still_shows_but_refuses_answers(setup):
    admin, mk = setup["admin"], setup["mk"]
    card = await make_card(admin, setup["event"])
    await admin.patch(f"/cards/{card['id']}", json={"closed": True})
    shown = await public(mk, card["token"])
    assert shown.status_code == 200 and shown.json()["closed"] is True
    assert (await mk().post(f"/invitations/{card['token']}/respond", json={"name": "A", "response": "yes"})).status_code == 409


async def test_the_deadline_closes_the_card(setup, monkeypatch):
    admin, mk = setup["admin"], setup["mk"]
    card = await make_card(admin, setup["event"], closes_on="2024-09-12")
    assert (await mk().post(f"/invitations/{card['token']}/respond", json={"name": "A", "response": "yes"})).status_code == 200  # today is 10 Sep
    monkeypatch.setattr("app.core.calendar_items.vn_today", lambda: datetime.date(2024, 9, 13))
    shown = (await public(mk, card["token"])).json()
    assert shown["closed"] is True
    assert (await mk().post(f"/invitations/{card['token']}/respond", json={"name": "B", "response": "yes"})).status_code == 409


async def test_a_card_takes_a_limited_number_of_answers(setup, monkeypatch):
    monkeypatch.setattr("app.routers.invitations.MAX_RESPONSES", 2)
    card = await make_card(setup["admin"], setup["event"])
    for name in ("A", "B"):
        assert (await setup["mk"]().post(f"/invitations/{card['token']}/respond", json={"name": name, "response": "yes"})).status_code == 200
    assert (await setup["mk"]().post(f"/invitations/{card['token']}/respond", json={"name": "C", "response": "yes"})).status_code == 409


# ------------------------------------------------------------------ export and audit


async def test_csv_export(setup):
    admin, mk = setup["admin"], setup["mk"]
    card = await make_card(admin, setup["event"])
    await mk().post(f"/invitations/{card['token']}/respond", json={"name": "Nguyễn Văn Hai", "response": "yes", "party_size": 3, "note": "Về từ Hà Nội, ăn chay"})
    await admin.post(f"/cards/{card['id']}/invitees", json={"names": ["Bà Ba"]})
    r = await admin.get(f"/cards/{card['id']}/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and r.content.startswith(b"\xef\xbb\xbf")
    lines = r.text.lstrip("﻿").splitlines()
    assert lines[0].split(",") == ["name", "response", "party_size", "note", "responded_at"]
    assert any("Nguyễn Văn Hai" in l and "tham dự" in l and "3" in l and "ăn chay" in l for l in lines[1:])
    assert any("Bà Ba" in l and "chưa trả lời" in l for l in lines[1:])


async def test_card_changes_are_audited(setup):
    admin = setup["admin"]
    card = await make_card(admin, setup["event"])
    await admin.patch(f"/cards/{card['id']}", json={"message": "Mới"})
    await admin.delete(f"/cards/{card['id']}")
    actions = [e["action"] for e in (await admin.get("/audit")).json()["items"]][:3]
    assert actions == ["card.delete", "card.update", "card.create"]
