"""Every change to the tree is written to the audit log, in the same transaction as the change."""

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
async def admin(world, make_client):
    return await signed_in(make_client, "admin_a")


async def add(c, name, parent_id=None, **extra):
    r = await c.post("/members", json={"full_name": name, "parent_id": parent_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def log(c, **params):
    r = await c.get("/audit", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def test_create_is_logged_with_actor_and_the_values_given(admin):
    member = await add(admin, "Nguyễn Văn A", birth_year=1950, hometown="Huế")
    [entry] = (await log(admin))["items"]
    assert entry["action"] == "member.create" and entry["member_id"] == member and entry["member_name"] == "Nguyễn Văn A"
    assert entry["actor_name"] == "admin_a"
    assert entry["changes"] == {
        "full_name": [None, "Nguyễn Văn A"],
        "birth_year": [None, 1950],
        "hometown": [None, "Huế"],
    }  # defaults (blank, False, the lunar death default) are not listed


async def test_update_logs_only_what_changed_and_nothing_when_nothing_did(admin):
    member = await add(admin, "Cũ", birth_year=1950)
    await admin.patch(f"/members/{member}", json={"full_name": "Mới", "birth_year": 1950})
    await admin.put(f"/members/{member}", json={"full_name": "Mới", "birth_year": 1950})  # identical: no entry
    entries = (await log(admin))["items"]
    assert [e["action"] for e in entries] == ["member.update", "member.create"]  # newest first
    assert entries[0]["changes"] == {"full_name": ["Cũ", "Mới"]}


async def test_delete_keeps_the_name_and_values_for_the_record(admin):
    member = await add(admin, "Sẽ xoá", birth_year=1900)
    assert (await admin.delete(f"/members/{member}")).status_code == 204
    entry = (await log(admin))["items"][0]
    assert entry["action"] == "member.delete" and entry["member_id"] == member and entry["member_name"] == "Sẽ xoá"
    assert entry["changes"]["birth_year"] == [1900, None]
    assert (await log(admin, member_id=member))["total"] == 2  # create + delete survive the person


async def test_marriages_avatar_and_split_are_logged(admin):
    man = await add(admin, "Chồng")
    made = await admin.post(f"/members/{man}/marriages", json={"spouse_full_name": "Vợ", "marriage_year": 1980})
    await admin.put(f"/members/marriages/{made.json()['marriage_id']}", json={
        "spouse_full_name": "Vợ (sửa)", "marriage_year": 1981})
    await admin.post(f"/members/{man}/avatar", files={"file": ("a.jpg", b"x", "image/jpeg")})
    leaf = await add(admin, "Nguyễn Vô Danh 2 Vị", man)
    await admin.post(f"/members/{leaf}/split", json={"names": ["A", "B"]})
    actions = [e["action"] for e in (await log(admin))["items"]]
    assert "marriage.create" in actions and "marriage.update" in actions
    assert "member.avatar" in actions and "member.split" in actions
    marriage = next(e for e in (await log(admin))["items"] if e["action"] == "marriage.update")
    assert marriage["member_id"] == man and marriage["changes"]["marriage_year"] == [1980, 1981]


async def test_csv_import_logs_one_entry_per_changed_person(admin):
    root = await add(admin, "Gốc")
    kid = await add(admin, "Con", root)
    csv_text = f"id,hometown\n{kid},Hà Tĩnh\n{root},\n".encode()
    r = await admin.post("/members/import", files={"file": ("m.csv", csv_text, "text/csv")})
    assert r.status_code == 200 and r.json()["updated"] == 1
    entries = [e for e in (await log(admin))["items"] if e["action"] == "member.update"]
    assert len(entries) == 1 and entries[0]["member_id"] == kid and entries[0]["changes"] == {"hometown": [None, "Hà Tĩnh"]}


async def test_branches_are_logged(admin):
    head = await add(admin, "Trưởng chi")
    branch = (await admin.post("/branches", json={"name": "Chi Cả", "root_member_id": head})).json()
    await admin.put(f"/branches/{branch['id']}", json={"name": "Chi Trưởng", "root_member_id": head})
    await admin.delete(f"/branches/{branch['id']}")
    actions = [e["action"] for e in (await log(admin, member_id=head))["items"]]
    assert actions[:3] == ["branch.delete", "branch.update", "branch.create"]
    update = (await log(admin, member_id=head))["items"][1]
    assert update["details"]["branch_name"] == "Chi Trưởng" and update["changes"]["name"] == ["Chi Cả", "Chi Trưởng"]


async def test_filter_paging_and_ordering(admin):
    a, b = await add(admin, "A"), await add(admin, "B")
    await admin.patch(f"/members/{a}", json={"hometown": "X"})
    assert [e["member_id"] for e in (await log(admin, member_id=a))["items"]] == [a, a]
    page = await log(admin, limit=2, offset=1)
    assert page["total"] == 3 and len(page["items"]) == 2
    assert (await admin.get("/audit", params={"limit": 0})).status_code == 422
    assert (await admin.get("/audit", params={"limit": 201})).status_code == 422
    assert b  # B's create is in the unfiltered total


async def test_only_admins_read_the_log_and_trees_are_isolated(world, make_client):
    admin_a, admin_b = await signed_in(make_client, "admin_a"), await signed_in(make_client, "admin_b")
    await add(admin_a, "Của họ A")
    assert (await log(admin_b))["total"] == 0
    member = await signed_in(make_client, "member_a")
    assert (await member.get("/audit")).status_code == 403
    assert (await make_client().get("/audit")).status_code == 401
