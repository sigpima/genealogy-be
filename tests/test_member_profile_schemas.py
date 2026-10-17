from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("schema_name", ["MemberCreate", "MemberUpdate"])
def test_profile_strings_are_stripped_and_blank_becomes_none(schema_name):
    from app.schemas import member as schemas

    schema = getattr(schemas, schema_name)
    data = schema(
        full_name="A",
        courtesy_name="  Phúc Khang ",
        title="   ",
        residence="",
        burial_place=" Nghĩa trang X ",
    )
    assert data.courtesy_name == "Phúc Khang"
    assert data.title is None
    assert data.residence is None
    assert data.burial_place == "Nghĩa trang X"


@pytest.mark.parametrize("schema_name", ["MemberCreate", "MemberUpdate"])
def test_gps_requires_both_coordinates(schema_name):
    from app.schemas import member as schemas

    schema = getattr(schemas, schema_name)
    with pytest.raises(ValidationError):
        schema(full_name="A", burial_latitude=21.0)
    with pytest.raises(ValidationError):
        schema(full_name="A", burial_longitude=105.0)
    ok = schema(full_name="A", burial_latitude=21.0, burial_longitude=105.8)
    assert (ok.burial_latitude, ok.burial_longitude) == (21.0, 105.8)


@pytest.mark.parametrize(
    "lat,lng",
    [(90.1, 0), (-90.1, 0), (0, 180.1), (0, -180.1)],
)
def test_gps_range_is_checked(lat, lng):
    from app.schemas.member import MemberCreate

    with pytest.raises(ValidationError):
        MemberCreate(full_name="A", burial_latitude=lat, burial_longitude=lng)


def test_gps_boundaries_are_allowed():
    from app.schemas.member import MemberCreate

    MemberCreate(full_name="A", burial_latitude=-90, burial_longitude=-180)
    MemberCreate(full_name="A", burial_latitude=90, burial_longitude=180)


def test_member_read_includes_profile_fields():
    from app.schemas.member import MemberRead

    class FakeMember:
        id = 1
        full_name = "A"
        parent_id = None
        birth_year = None
        death_year = None
        gender = None
        notes = None
        avatar_url = None
        courtesy_name = "Phúc Khang"
        title = "Trưởng Chi"
        residence = "Hà Nội"
        burial_place = "Nghĩa trang X"
        burial_latitude = 21.0
        burial_longitude = 105.8
        created_at = datetime.now(timezone.utc)

    read = MemberRead.model_validate(FakeMember())
    assert read.courtesy_name == "Phúc Khang"
    assert read.title == "Trưởng Chi"
    assert read.burial_latitude == 21.0


def test_member_detail_has_profile_fields_and_rank_defaults():
    from app.schemas.member import MemberDetail

    detail = MemberDetail(id=1)
    assert detail.courtesy_name is None
    assert detail.sibling_rank is None
