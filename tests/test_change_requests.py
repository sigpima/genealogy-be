"""GĐ4: members propose, admins review; the tree changes only through an admin's approval."""

import pytest

from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login, set_user


@pytest.fixture
async def world(session):
    tree_a = await create_tree(session, "Họ A", "ho-a")
    tree_b = await create_tree(session, "Họ B", "ho-b")
    for key, role, tree in [
        ("admin_a", "admin", tree_a),
        ("admin_a2", "admin", tree_a),
        ("member_a", "member", tree_a),
        ("other_a", "member", tree_a),
        ("admin_b", "admin", tree_b),
        ("member_b", "member", tree_b),
    ]:
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
async def setup(world, make_client):
    admin = await signed_in(make_client, "admin_a")
    root = await add(admin, "Tổ", birth_year=1900)
    child = await add(admin, "Nguyễn Văn Con", root, birth_year=1930, hometown="Huế")
    member = await signed_in(make_client, "member_a")
    return {"admin": admin, "member": member, "root": root, "child": child, "make_client": make_client}


async def propose(c, member_id, changes, kind="edit", message="Tôi biết thông tin này", **extra):
    return await c.post("/requests", json={"kind": kind, "member_id": member_id, "changes": changes, "message": message, **extra})


# ------------------------------------------------------------------ proposing


async def test_a_member_can_propose_an_edit_but_the_tree_does_not_change(setup):
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    r = await propose(member, child, {"birth_year": 1931, "hometown": "Hà Tĩnh"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending" and body["kind"] == "edit" and body["member_name"] == "Nguyễn Văn Con"
    assert body["requester"]["name"] == "member_a" and body["changes"] == {"birth_year": 1931, "hometown": "Hà Tĩnh"}
    assert body["base"] == {"birth_year": 1930, "hometown": "Huế"}
    assert {d["field"]: (d["old"], d["new"]) for d in body["diff"]} == {"birth_year": (1930, 1931), "hometown": ("Huế", "Hà Tĩnh")}
    assert (await admin.get(f"/members/{child}")).json()["birth_year"] == 1930  # untouched
    assert (await member.patch(f"/members/{child}", json={"birth_year": 1931})).status_code == 403  # still no direct door


async def test_proposals_are_validated_like_real_edits(setup):
    member, child = setup["member"], setup["child"]
    assert (await propose(member, child, {})).status_code == 422  # nothing proposed
    assert (await propose(member, child, {"birth_year": 1930})).status_code == 422  # no change at all
    assert (await propose(member, child, {"birth_day": 5})).status_code == 422  # day without month
    assert (await propose(member, child, {"death_year": 1800})).status_code == 422  # died before being born
    assert (await propose(member, child, {"email": "nope"})).status_code == 422
    assert (await propose(member, child, {"parent_id": setup["root"]})).status_code == 422  # structure is the admin's
    assert (await propose(member, child, {"mother_id": 1})).status_code == 422
    assert (await propose(member, child, {"shoe_size": 42})).status_code == 422
    assert (await propose(member, 99999, {"hometown": "x"})).status_code == 404


async def test_add_child_and_report_kinds(setup):
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    ok = await propose(member, child, {"full_name": "Cháu Mới", "gender": "female", "birth_year": 1960}, kind="add_child")
    assert ok.status_code == 201 and ok.json()["kind"] == "add_child"
    assert (await propose(member, child, {"birth_year": 1960}, kind="add_child")).status_code == 422  # a name is needed
    assert (await propose(member, child, {"full_name": "X", "mother_id": 5}, kind="add_child")).status_code == 422
    note = await propose(member, child, {}, kind="report", message="Ông mất năm 1975, không phải 1970")
    assert note.status_code == 201 and note.json()["changes"] == {}
    assert (await propose(member, child, {}, kind="report", message=" ")).status_code == 422
    assert (await propose(member, child, {}, kind="report", message="abc")).status_code == 422  # too short to be useful
    assert (await admin.get(f"/members/{child}")).json()["birth_year"] == 1930


async def test_guests_and_other_trees_cannot_propose(setup, world):
    guest = setup["make_client"]()
    assert (await propose(guest, setup["child"], {"hometown": "x"})).status_code == 401
    other = await signed_in(setup["make_client"], "member_b")
    assert (await propose(other, setup["child"], {"hometown": "x"})).status_code == 404  # another family's person


# ------------------------------------------------------------------ visibility


async def test_who_sees_which_requests(setup):
    member, admin, child, mk = setup["member"], setup["admin"], setup["child"], setup["make_client"]
    mine = (await propose(member, child, {"hometown": "A"})).json()
    other = await signed_in(mk, "other_a")
    theirs = (await propose(other, child, {"hometown": "B"})).json()
    assert {r["id"] for r in (await admin.get("/requests")).json()["items"]} == {mine["id"], theirs["id"]}
    assert [r["id"] for r in (await member.get("/requests")).json()["items"]] == [mine["id"]]
    assert (await member.get(f"/requests/{theirs['id']}")).status_code == 404
    assert (await member.get(f"/requests/{mine['id']}")).status_code == 200
    outsider = await signed_in(mk, "admin_b")
    assert (await outsider.get(f"/requests/{mine['id']}")).status_code == 404
    assert (await outsider.get("/requests")).json()["items"] == []


async def test_summary_and_status_filter(setup):
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    one = (await propose(member, child, {"hometown": "A"})).json()
    await propose(member, child, {"hometown": "B"})
    assert (await admin.get("/requests/summary")).json() == {"pending": 2}
    assert (await member.get("/requests/summary")).json() == {"pending": 2}
    await admin.post(f"/requests/{one['id']}/reject", json={"note": "không đúng"})
    assert (await admin.get("/requests/summary")).json() == {"pending": 1}
    assert len((await admin.get("/requests", params={"status": "pending"})).json()["items"]) == 1
    closed = (await admin.get("/requests", params={"status": "closed"})).json()["items"]
    assert [r["id"] for r in closed] == [one["id"]]
    assert (await admin.get("/requests", params={"status": "weird"})).status_code == 422


# ------------------------------------------------------------------ deciding


async def test_approving_an_edit_applies_it_and_logs_it(setup):
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    req = (await propose(member, child, {"birth_year": 1931, "hometown": "Hà Tĩnh"})).json()
    r = await admin.post(f"/requests/{req['id']}/approve", json={"note": "Cảm ơn"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved" and body["reviewer"]["name"] == "admin_a" and body["review_note"] == "Cảm ơn"
    assert body["reviewed_at"] is not None
    detail = (await admin.get(f"/members/{child}")).json()
    assert detail["birth_year"] == 1931 and detail["hometown"] == "Hà Tĩnh"
    entry = next(e for e in (await admin.get("/audit", params={"member_id": child})).json()["items"] if e["action"] == "member.update")
    assert entry["request_id"] == req["id"] and entry["actor_name"] == "admin_a"
    assert entry["changes"] == {"birth_year": [1930, 1931], "hometown": ["Huế", "Hà Tĩnh"]}
    assert (await admin.post(f"/requests/{req['id']}/approve", json={})).status_code == 409  # already decided
    assert (await admin.post(f"/requests/{req['id']}/reject", json={"note": "x"})).status_code == 409


async def test_approving_add_child_creates_the_child(setup):
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    req = (await propose(member, child, {"full_name": "Cháu Mới", "gender": "female", "birth_year": 1960}, kind="add_child")).json()
    body = (await admin.post(f"/requests/{req['id']}/approve", json={})).json()
    new_id = body["result_member_id"]
    assert new_id is not None
    detail = (await admin.get(f"/members/{new_id}")).json()
    assert detail["gender"] == "female" and detail["birth_year"] == 1960
    table = (await admin.get("/members/table", params={"q": "Cháu Mới"})).json()["items"]
    assert table[0]["parent_id"] == child
    created = next(e for e in (await admin.get("/audit", params={"member_id": new_id})).json()["items"] if e["action"] == "member.create")
    assert created["request_id"] == req["id"]


async def test_approving_a_report_only_acknowledges_it(setup):
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    req = (await propose(member, child, {}, kind="report", message="Ông mất năm 1975")).json()
    assert (await admin.post(f"/requests/{req['id']}/approve", json={"note": "Đã ghi nhận"})).json()["status"] == "approved"
    assert (await admin.get(f"/members/{child}")).json()["birth_year"] == 1930


async def test_reject_needs_a_reason_and_changes_nothing(setup):
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    req = (await propose(member, child, {"birth_year": 1931})).json()
    assert (await admin.post(f"/requests/{req['id']}/reject", json={})).status_code == 422
    assert (await admin.post(f"/requests/{req['id']}/reject", json={"note": "  "})).status_code == 422
    done = (await admin.post(f"/requests/{req['id']}/reject", json={"note": "Sai năm"})).json()
    assert done["status"] == "rejected" and done["review_note"] == "Sai năm"
    assert (await admin.get(f"/members/{child}")).json()["birth_year"] == 1930
    assert (await member.get(f"/requests/{req['id']}")).json()["review_note"] == "Sai năm"


async def test_members_cannot_decide(setup):
    member, child = setup["member"], setup["child"]
    req = (await propose(member, child, {"birth_year": 1931})).json()
    assert (await member.post(f"/requests/{req['id']}/approve", json={})).status_code == 403
    assert (await member.post(f"/requests/{req['id']}/reject", json={"note": "x"})).status_code == 403
    assert (await member.get("/audit")).status_code == 403


async def test_another_trees_admin_cannot_decide(setup):
    req = (await propose(setup["member"], setup["child"], {"birth_year": 1931})).json()
    outsider = await signed_in(setup["make_client"], "admin_b")
    assert (await outsider.post(f"/requests/{req['id']}/approve", json={})).status_code == 404
    assert (await outsider.post(f"/requests/{req['id']}/reject", json={"note": "x"})).status_code == 404


async def test_a_stale_request_is_flagged_and_still_applies_after_review(setup):
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    req = (await propose(member, child, {"hometown": "Hà Tĩnh"})).json()
    await admin.patch(f"/members/{child}", json={"hometown": "Nghệ An"})  # the tree moved on meanwhile
    shown = (await admin.get(f"/requests/{req['id']}")).json()
    assert shown["stale"] is True and shown["diff"][0]["old"] == "Nghệ An" and shown["diff"][0]["stale"] is True
    fresh = (await propose(member, child, {"birth_year": 1932})).json()
    assert (await admin.get(f"/requests/{fresh['id']}")).json()["stale"] is False
    assert (await admin.post(f"/requests/{req['id']}/approve", json={})).status_code == 200
    assert (await admin.get(f"/members/{child}")).json()["hometown"] == "Hà Tĩnh"


async def test_approving_fails_cleanly_when_the_person_is_gone_or_the_data_no_longer_fits(setup):
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    gone = (await propose(member, child, {"hometown": "x"})).json()
    await admin.delete(f"/members/{child}")
    r = await admin.post(f"/requests/{gone['id']}/approve", json={})
    assert r.status_code == 409
    assert (await admin.get(f"/requests/{gone['id']}")).json()["status"] == "pending"  # left for the admin to reject
    assert (await admin.post(f"/requests/{gone['id']}/reject", json={"note": "Người này đã bị xoá"})).status_code == 200
    # data that stopped being valid: proposed death year, then the admin moves the birth year past it
    other = await add(admin, "Người khác", setup["root"], birth_year=1950)
    req = (await propose(member, other, {"death_year": 1980})).json()
    await admin.patch(f"/members/{other}", json={"birth_year": 1990})
    assert (await admin.post(f"/requests/{req['id']}/approve", json={})).status_code == 409
    assert (await admin.get(f"/members/{other}")).json()["death_year"] is None


async def test_cancel_is_for_the_requester_while_pending(setup):
    member, admin, child, mk = setup["member"], setup["admin"], setup["child"], setup["make_client"]
    req = (await propose(member, child, {"hometown": "x"})).json()
    other = await signed_in(mk, "other_a")
    assert (await other.post(f"/requests/{req['id']}/cancel")).status_code == 404
    done = await member.post(f"/requests/{req['id']}/cancel")
    assert done.status_code == 200 and done.json()["status"] == "cancelled"
    assert (await member.post(f"/requests/{req['id']}/cancel")).status_code == 409
    assert (await admin.post(f"/requests/{req['id']}/approve", json={})).status_code == 409
    approved = (await propose(member, child, {"hometown": "y"})).json()
    await admin.post(f"/requests/{approved['id']}/approve", json={})
    assert (await member.post(f"/requests/{approved['id']}/cancel")).status_code == 409


async def test_disabled_requesters_cannot_send(setup, session):
    await set_user(session, "member_a@example.com", status="disabled")
    assert (await propose(setup["member"], setup["child"], {"hometown": "x"})).status_code == 403


# ------------------------------------------------------------------ email


async def test_emails_go_to_admins_on_arrival_and_to_the_requester_on_decision(setup, monkeypatch):
    from app.core.config import get_settings

    sent = []
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    get_settings.cache_clear()
    monkeypatch.setattr("app.routers.requests.send_email", lambda to, subject, body: sent.append((to, subject, body)))
    member, admin, child = setup["member"], setup["admin"], setup["child"]
    req = (await propose(member, child, {"hometown": "Hà Tĩnh"})).json()
    assert sorted(to for to, *_ in sent) == ["admin_a2@example.com", "admin_a@example.com"]
    assert all("Nguyễn Văn Con" in body for *_, body in sent)
    sent.clear()
    await admin.post(f"/requests/{req['id']}/reject", json={"note": "Chưa đúng"})
    assert [to for to, *_ in sent] == ["member_a@example.com"] and "Chưa đúng" in sent[0][2]


async def test_a_broken_mail_server_never_blocks_anything(setup, monkeypatch):
    from app.core.config import get_settings

    def boom(*args):
        raise OSError("smtp down")

    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    get_settings.cache_clear()
    monkeypatch.setattr("app.routers.requests.send_email", boom)
    req = await propose(setup["member"], setup["child"], {"hometown": "x"})
    assert req.status_code == 201
    assert (await setup["admin"].post(f"/requests/{req.json()['id']}/approve", json={})).status_code == 200
