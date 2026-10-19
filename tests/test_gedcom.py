"""GEDCOM export: the pure builder on plain rows, and the endpoint."""

import datetime
from types import SimpleNamespace as NS

import pytest

from app.core.gedcom import build_gedcom, date_parts, split_name
from app.core.tenants import create_tree, create_user
from tests.test_roles_auth import PASSWORD, login

NOW = datetime.datetime(2026, 10, 20, tzinfo=datetime.timezone.utc)


def person(id, name, **kw):
    base = dict(
        id=id, full_name=name, parent_id=None, mother_id=None, gender=None, birth_year=None, death_year=None,
        birth_month=None, birth_day=None, death_month=None, death_day=None, birth_is_lunar=False, birth_leap_month=False,
        death_is_lunar=True, death_leap_month=False, courtesy_name=None, title=None, residence=None, hometown=None,
        phone=None, email=None, notes=None, birth_order=None, is_adopted=False, burial_place=None, burial_place_id=None,
        burial_plot=None, burial_map_url=None, burial_latitude=None, burial_longitude=None,
    )
    return NS(**{**base, **kw})


def build(members, marriages=(), places=None):
    return build_gedcom(tree_name="Họ Nguyễn", members=members, marriages=list(marriages), places=places or {}, exported_at=NOW)


def test_names_split_the_vietnamese_way():
    assert split_name("Nguyễn Văn Một") == ("Văn Một", "Nguyễn")
    assert split_name("Lan") == ("Lan", "")
    assert split_name("  ") == ("", "")
    assert split_name("A/B C") == ("B C", "A")  # a slash would break the NAME line


def test_dates_solar_lunar_and_partial():
    assert date_parts(1950, 3, 12, lunar=False, leap=False) == ("12 MAR 1950", None)
    assert date_parts(1950, 3, None, lunar=False, leap=False) == ("MAR 1950", None)
    assert date_parts(1950, None, None, lunar=False, leap=False) == ("1950", None)
    assert date_parts(None, 3, 12, lunar=False, leap=False) == (None, "Dương lịch: 12/3")
    assert date_parts(1950, 7, 15, lunar=True, leap=True) == ("1950", "Âm lịch: 15/7 (tháng nhuận)")
    assert date_parts(None, 7, 15, lunar=True, leap=False) == (None, "Âm lịch: 15/7")
    assert date_parts(None, None, None, lunar=True, leap=False) == (None, None)


def test_a_family_with_a_mother_and_an_unknown_mother():
    to = person(1, "Nguyễn Văn Tổ", gender="male", birth_year=1900, notes="Dòng 1\nDòng 2 @ ok")
    lan = person(2, "Trần Thị Lan", gender="female")
    hai = person(3, "Nguyễn Văn Hai", parent_id=1, mother_id=2, gender="male", birth_order=2)
    ba = person(4, "Nguyễn Thị Ba", parent_id=1, mother_id=2, gender="female", birth_order=1, is_adopted=True)
    mo = person(5, "Nguyễn Văn Mồ", parent_id=1)  # mother not recorded
    text = build([to, lan, hai, ba, mo], [NS(id=1, member_id=1, spouse_id=2, marriage_year=1925)])
    lines = text.splitlines()
    assert lines[0] == "0 HEAD" and lines[-1] == "0 TRLR" and "1 CHAR UTF-8" in lines and "2 VERS 5.5.1" in lines
    assert "1 NAME Văn Tổ /Nguyễn/" in lines and "2 SURN Nguyễn" in lines and "1 SEX M" in lines
    assert "2 DATE 1900" in lines
    # a note keeps its line breaks (CONT) and escapes the at sign
    assert "1 NOTE Dòng 1" in lines and "2 CONT Dòng 2 @@ ok" in lines
    # the married family: father, mother, the year, children by sibling order (Ba before Hai)
    fam1 = lines[lines.index("0 @F1@ FAM") :]
    assert fam1[1:3] == ["1 HUSB @I1@", "1 WIFE @I2@"] and "2 DATE 1925" in fam1[:6]
    assert [l for l in fam1[:9] if l.startswith("1 CHIL")] == ["1 CHIL @I4@", "1 CHIL @I3@"]
    # the child of an unknown mother sits in a family of the father alone
    fam2 = lines[lines.index("0 @F2@ FAM") :]
    assert fam2[1:3] == ["1 HUSB @I1@", "1 CHIL @I5@"]
    # links back from the people
    assert "1 FAMS @F1@" in lines and "1 FAMS @F2@" in lines
    adopted = lines[lines.index("0 @I4@ INDI") :]
    assert "1 FAMC @F1@" in adopted and "2 PEDI adopted" in adopted
    assert "2 PEDI birth" in lines[lines.index("0 @I3@ INDI") :]


def test_a_female_blood_member_is_the_wife():
    me = person(1, "Nguyễn Thị Mai", gender="female")
    chong = person(2, "Lê Văn Nam", gender="male")
    kid = person(3, "Lê Văn Con", parent_id=1, mother_id=2)  # mother_id is the spouse: kept as the spouse's family
    text = build([me, chong, kid], [NS(id=1, member_id=1, spouse_id=2, marriage_year=None)])
    fam = text.splitlines()
    i = fam.index("0 @F1@ FAM")
    assert fam[i + 1 : i + 3] == ["1 HUSB @I2@", "1 WIFE @I1@"]
    assert "1 MARR" in fam


def test_burial_with_place_plot_map_and_coordinates():
    place = NS(id=7, name="Nghĩa trang Bình Hưng Hoà", latitude=10.8, longitude=106.6)
    m = person(1, "Nguyễn Văn Tổ", burial_place_id=7, burial_plot="Khu B, hàng 3", burial_map_url="https://maps.app.goo.gl/x", death_year=1980)
    lines = build([m], places={7: place}).splitlines()
    i = lines.index("1 BURI")
    assert lines[i + 1] == "2 PLAC Nghĩa trang Bình Hưng Hoà"
    assert "4 LATI N10.800000" in lines and "4 LONG E106.600000" in lines
    assert "2 NOTE Vị trí mộ: Khu B, hàng 3" in lines and "3 CONT Bản đồ: https://maps.app.goo.gl/x" in lines
    assert "1 DEAT" in lines and "2 DATE 1980" in lines


def test_nothing_is_invented_for_an_empty_person_and_long_lines_are_wrapped():
    lines = build([person(1, "Lan", notes="x" * 450)]).splitlines()
    assert "1 BIRT" not in lines and "1 DEAT" not in lines and "1 NAME Lan //" in lines and "1 SEX U" in lines
    assert max(len(l) for l in lines) <= 255
    assert "".join(l.split(" ", 2)[2] for l in lines if " CONC " in l) + "x" * 200 == "x" * 450


@pytest.fixture
async def world(session):
    tree = await create_tree(session, "Họ A", "ho-a")
    await create_user(session, email="admin@example.com", full_name="admin", password=PASSWORD, role="admin", tree=tree)
    await create_user(session, email="member@example.com", full_name="member", password=PASSWORD, role="member", tree=tree)
    other = await create_tree(session, "Họ B", "ho-b")
    await create_user(session, email="adminb@example.com", full_name="adminb", password=PASSWORD, role="admin", tree=other)


async def signed_in(make_client, who):
    c = make_client()
    assert (await login(c, f"{who}@example.com")).status_code == 200
    return c


async def test_the_endpoint_exports_one_tree_for_admins_only_and_is_audited(world, make_client):
    admin = await signed_in(make_client, "admin")
    to = (await admin.post("/members", json={"full_name": "Nguyễn Văn Tổ", "birth_year": 1900})).json()["id"]
    await admin.post(f"/members/{to}/marriages", json={"spouse_full_name": "Trần Thị Lan", "marriage_year": 1925})
    await admin.post("/members", json={"full_name": "Nguyễn Văn Hai", "parent_id": to})
    adminb = await signed_in(make_client, "adminb")
    await adminb.post("/members", json={"full_name": "Người họ khác"})

    r = await admin.get("/export/data.ged")
    assert r.status_code == 200 and r.headers["content-disposition"].endswith('ho-a.ged"')
    text = r.text
    assert text.startswith("0 HEAD") and text.rstrip().endswith("0 TRLR")
    assert "Văn Tổ /Nguyễn/" in text and "Lan /Trần/" in text and "Hai /Nguyễn/" in text and "2 DATE 1925" in text
    assert "Người họ khác" not in text and "họ khác" not in text

    assert (await (await signed_in(make_client, "member")).get("/export/data.ged")).status_code == 403
    assert (await make_client().get("/export/data.ged")).status_code in (401, 403)
    items = (await admin.get("/audit")).json()
    assert any(e["action"] == "data.export_gedcom" for e in (items["items"] if isinstance(items, dict) else items))
