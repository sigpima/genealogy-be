"""GĐ2 B2 over HTTP: PATCH, the data-entry table, completeness, split, CSV export/import."""

import csv
import io

import pytest

from app.core.tenants import create_user, lowest_tree
from tests.test_gd2_members import add, add_spouse
from tests.test_roles_auth import PASSWORD, login, make_user


@pytest.fixture
async def admin(client, session):
    await make_user(client, "root@example.com", "Root", role="superadmin")
    await create_user(
        session, email="admin@example.com", full_name="Admin", password=PASSWORD, role="admin", tree=await lowest_tree(session)
    )
    await login(client, "admin@example.com")
    return client


@pytest.fixture
def guest(make_client):
    return make_client()


async def family(c):
    """Root (gen 1) -> A, B (gen 2) -> A1 (gen 3); a spouse for Root."""
    root = await add(c, "Root")
    a = await add(c, "A", root, gender="male", birth_year=1950)
    b = await add(c, "B", root, gender="female")
    a1 = await add(c, "A1", a)
    await add_spouse(c, root, "Root wife")
    return root, a, b, a1


# ------------------------------------------------------------------ PATCH


async def test_patch_changes_only_the_fields_sent(admin):
    member = await add(admin, "Old", hometown="Huế", birth_year=1900, birth_order=3)
    response = await admin.patch(f"/members/{member}", json={"full_name": "New", "phone": "0912345678"})
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "New" and body["phone"] == "0912345678"
    assert body["hometown"] == "Huế" and body["birth_year"] == 1900 and body["birth_order"] == 3


async def test_patch_null_clears_a_field_and_validates_the_merged_result(admin):
    member = await add(admin, "M", birth_year=1900, death_year=1950)
    assert (await admin.patch(f"/members/{member}", json={"birth_year": None})).json()["birth_year"] is None
    assert (await admin.patch(f"/members/{member}", json={"death_year": 1800, "birth_year": 1900})).status_code == 422
    assert (await admin.patch(f"/members/{member}", json={"birth_day": 5})).status_code == 422  # day needs month
    assert (await admin.patch(f"/members/{member}", json={"full_name": None})).status_code == 422
    assert (await admin.patch(f"/members/{member}", json={"nonsense": 1})).status_code == 422


async def test_patch_reparenting_follows_the_same_rules_as_put(admin):
    root, a, _, a1 = await family(admin)
    assert (await admin.patch(f"/members/{root}", json={"parent_id": a1})).status_code == 400  # cycle
    assert (await admin.patch(f"/members/{a}", json={"parent_id": a})).status_code == 400
    assert (await admin.patch(f"/members/{a1}", json={"parent_id": 99999})).status_code == 404
    assert (await admin.patch("/members/99999", json={"full_name": "x"})).status_code == 404


async def test_patch_is_admin_only(admin, guest, make_client):
    member = await add(admin, "M")
    assert (await guest.patch(f"/members/{member}", json={"full_name": "x"})).status_code in (401, 403)


# ------------------------------------------------------------------ table


async def test_table_lists_members_in_tree_order_without_spouses(admin):
    root, a, b, a1 = await family(admin)
    body = (await admin.get("/members/table")).json()
    assert body["total"] == 4
    assert [r["full_name"] for r in body["items"]] == ["Root", "A", "A1", "B"]  # depth-first
    rows = {r["full_name"]: r for r in body["items"]}
    assert rows["Root"]["generation"] == 1 and rows["A1"]["generation"] == 3
    assert rows["A"]["parent_name"] == "Root" and rows["Root"]["parent_name"] is None
    assert rows["A"]["has_children"] is True and rows["B"]["has_children"] is False


async def test_table_filters(admin):
    root, a, b, a1 = await family(admin)
    names = lambda body: [r["full_name"] for r in body["items"]]  # noqa: E731
    assert names((await admin.get("/members/table", params={"generation": 2})).json()) == ["A", "B"]
    assert names((await admin.get("/members/table", params={"q": "root"})).json()) == ["Root"]
    assert names((await admin.get("/members/table", params={"under": a})).json()) == ["A", "A1"]
    assert names((await admin.get("/members/table", params={"missing": "birth_year"})).json()) == ["Root", "A1", "B"]
    both = await admin.get("/members/table", params=[("missing", "birth_year"), ("missing", "gender")])
    assert names(both.json()) == ["Root", "A1"]
    assert (await admin.get("/members/table", params={"missing": "shoe_size"})).status_code == 422
    assert (await admin.get("/members/table", params={"under": 99999})).status_code == 404


async def test_table_paging_keeps_the_total(admin):
    await family(admin)
    page = (await admin.get("/members/table", params={"limit": 2, "offset": 1})).json()
    assert page["total"] == 4 and [r["full_name"] for r in page["items"]] == ["A", "A1"]


async def test_table_is_admin_only_and_tree_scoped(admin, guest):
    await family(admin)
    assert (await guest.get("/members/table")).status_code in (401, 403, 404)


# ------------------------------------------------------------------ completeness


async def test_completeness_counts_members_only(admin):
    await family(admin)
    body = (await admin.get("/members/completeness")).json()
    assert body == {
        "total": 4, "with_gender": 2, "with_birth_year": 1, "with_hometown": 0, "basic": 1, "with_death_year": 0, "with_avatar": 0,
    }


# ------------------------------------------------------------------ split


async def test_split_replaces_one_entry_by_several_siblings(admin):
    root = await add(admin, "Root")
    vo_danh = await add(admin, "Nguyễn Vô Danh 3 Vị", root, gender="male", hometown="Huế")
    response = await admin.post(f"/members/{vo_danh}/split", json={"names": ["Vô Danh 1", "Vô Danh 2", "Vô Danh 3"]})
    assert response.status_code == 201
    created = response.json()
    assert [m["full_name"] for m in created] == ["Vô Danh 1", "Vô Danh 2", "Vô Danh 3"]
    assert created[0]["id"] == vo_danh
    assert all(m["parent_id"] == root and m["gender"] == "male" and m["hometown"] == "Huế" for m in created)
    table = (await admin.get("/members/table")).json()
    assert [r["full_name"] for r in table["items"]] == ["Root", "Vô Danh 1", "Vô Danh 2", "Vô Danh 3"]


async def test_split_refuses_members_with_children_or_spouse_and_bad_input(admin):
    root, a, b, a1 = await family(admin)
    assert (await admin.post(f"/members/{a}/split", json={"names": ["x", "y"]})).status_code == 409
    assert (await admin.post(f"/members/{root}/split", json={"names": ["x", "y"]})).status_code == 409
    assert (await admin.post(f"/members/{b}/split", json={"names": ["only"]})).status_code == 422
    assert (await admin.post(f"/members/{b}/split", json={"names": ["x", " "]})).status_code == 422
    assert (await admin.post("/members/99999/split", json={"names": ["x", "y"]})).status_code == 404


# ------------------------------------------------------------------ CSV


def parse(text):
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def upload(text):
    return {"file": ("members.csv", text.encode("utf-8"), "text/csv")}


async def test_export_is_utf8_with_bom_and_has_one_row_per_member(admin):
    await family(admin)
    response = await admin.get("/members/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(b"\xef\xbb\xbf")
    rows = parse(response.text)
    assert [r["full_name"] for r in rows] == ["Root", "A", "A1", "B"]
    assert rows[1]["gender"] == "nam" and rows[1]["birth_year"] == "1950"


async def test_export_then_import_changes_nothing(admin):
    await family(admin)
    exported = (await admin.get("/members/export.csv")).text
    result = await admin.post("/members/import", files=upload(exported))
    assert result.status_code == 200, result.text
    assert result.json() == {"dry_run": False, "created": 0, "updated": 0, "unchanged": 4}


async def test_import_blank_keeps_dash_clears_and_cells_update(admin):
    root, a, b, _ = await family(admin)
    text = (
        "id,full_name,gender,birth_year,hometown\n"
        f"{a},,nữ,-,Hà Tĩnh\n"  # blank name kept, gender changed, birth year cleared, hometown set
        f"{b},B renamed,,,\n"
    )
    result = await admin.post("/members/import", files=upload(text))
    assert result.status_code == 200, result.text
    assert result.json()["updated"] == 2
    member = (await admin.get(f"/members/{a}")).json()
    assert member["gender"] == "female" and member["birth_year"] is None and member["hometown"] == "Hà Tĩnh"
    assert (await admin.get(f"/members/{a}")).status_code == 200
    renamed = (await admin.get("/members/table")).json()["items"]
    assert "B renamed" in [r["full_name"] for r in renamed] and "A" in [r["full_name"] for r in renamed]


async def test_import_rows_without_id_create_children(admin):
    root, *_ = await family(admin)
    text = f"id,full_name,parent_id,gender,birth_year\n,New kid,{root},nam,2001\n"
    result = await admin.post("/members/import", files=upload(text))
    assert result.json() == {"dry_run": False, "created": 1, "updated": 0, "unchanged": 0}
    rows = (await admin.get("/members/table", params={"q": "New kid"})).json()["items"]
    assert rows[0]["parent_id"] == root and rows[0]["gender"] == "male" and rows[0]["birth_year"] == 2001


async def test_import_is_all_or_nothing_with_per_row_errors(admin):
    root, a, b, _ = await family(admin)
    text = (
        "id,full_name,birth_year,birth_month,birth_day\n"
        f"{a},A fixed,1951,,\n"          # fine
        f"{b},B,1900,,5\n"                # day without month -> error on row 3
        "99999,Ghost,,,\n"                # unknown id -> error on row 4
    )
    result = await admin.post("/members/import", files=upload(text))
    assert result.status_code == 422
    errors = result.json()["detail"]["errors"]
    assert sorted(e["row"] for e in errors) == [3, 4]
    assert (await admin.get(f"/members/{a}")).json()["birth_year"] == 1950  # nothing applied


async def test_import_dry_run_reports_without_writing(admin):
    root, a, *_ = await family(admin)
    text = f"id,hometown\n{a},Nowhere\n"
    result = await admin.post("/members/import", params={"dry_run": "true"}, files=upload(text))
    assert result.json() == {"dry_run": True, "created": 0, "updated": 1, "unchanged": 0}
    assert (await admin.get(f"/members/{a}")).json()["hometown"] is None


async def test_import_rejects_cycles_duplicates_foreign_ids_and_bad_files(admin):
    root, a, b, a1 = await family(admin)
    cycle = await admin.post("/members/import", files=upload(f"id,parent_id\n{root},{a1}\n"))
    assert cycle.status_code == 422
    dup = await admin.post("/members/import", files=upload(f"id,hometown\n{a},x\n{a},y\n"))
    assert dup.status_code == 422
    no_parent = await admin.post("/members/import", files=upload("id,full_name\n,Orphan\n"))
    assert no_parent.status_code == 422
    unknown_col = await admin.post("/members/import", files=upload(f"id,shoe\n{a},9\n"))
    assert unknown_col.status_code == 422
    not_utf8 = await admin.post("/members/import", files={"file": ("m.csv", b"id\n\xff\xfe\n", "text/csv")})
    assert not_utf8.status_code == 400
    mother = await admin.post("/members/import", files=upload(f"id,mother_id\n{a1},{b}\n"))
    assert mother.status_code == 422  # b is not a spouse of a1's father


async def test_import_cannot_touch_another_trees_members(admin, make_client, session):
    from app.core.tenants import create_tree

    other_tree = await create_tree(session, name="Other", slug="other")
    await create_user(session, email="o@example.com", full_name="O", password=PASSWORD, role="admin", tree=other_tree)
    other = make_client()
    await login(other, "o@example.com")
    foreign = await add(other, "Foreign")
    result = await admin.post("/members/import", files=upload(f"id,hometown\n{foreign},hacked\n"))
    assert result.status_code == 422
    assert (await other.get(f"/members/{foreign}")).json()["hometown"] is None


async def test_import_enforces_limits(admin):
    big = "id,hometown\n" + "1,x\n" * 10_001
    assert (await admin.post("/members/import", files=upload(big))).status_code == 413
