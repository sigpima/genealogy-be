import pytest
from pydantic import ValidationError

from app.schemas.member import MemberCreate, MemberUpdate

SCHEMAS = [MemberCreate, MemberUpdate]


def make(schema, **fields):
    return schema(full_name="A", **fields)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_defaults_death_is_lunar_birth_is_solar(schema):
    member = make(schema)
    assert member.death_is_lunar is True
    assert member.birth_is_lunar is False
    assert (member.birth_leap_month, member.death_leap_month, member.is_adopted) == (False, False, False)
    assert member.hometown is None and member.phone is None and member.email is None


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("field", ["birth_month", "death_month"])
@pytest.mark.parametrize("value", [0, 13, -1])
def test_month_must_be_1_to_12(schema, field, value):
    with pytest.raises(ValidationError):
        make(schema, **{field: value})


@pytest.mark.parametrize("schema", SCHEMAS)
def test_day_needs_a_month_but_month_and_day_need_no_year(schema):
    with pytest.raises(ValidationError):
        make(schema, death_day=12)
    member = make(schema, death_month=3, death_day=12)  # a giỗ only needs the lunar month+day
    assert (member.death_year, member.death_month, member.death_day) == (None, 3, 12)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_day_range_depends_on_calendar(schema):
    with pytest.raises(ValidationError):
        make(schema, birth_month=1, birth_day=0)
    with pytest.raises(ValidationError):
        make(schema, birth_month=1, birth_day=32)
    with pytest.raises(ValidationError):
        make(schema, death_month=1, death_day=31, death_is_lunar=True)  # a lunar month has at most 30 days
    make(schema, death_month=1, death_day=30, death_is_lunar=True)
    make(schema, birth_month=1, birth_day=31)  # solar January has 31


@pytest.mark.parametrize("schema", SCHEMAS)
def test_a_solar_date_with_year_must_be_a_real_date(schema):
    with pytest.raises(ValidationError):
        make(schema, birth_year=2001, birth_month=2, birth_day=29)
    with pytest.raises(ValidationError):
        make(schema, birth_year=1900, birth_month=2, birth_day=29)  # 1900 was not a leap year
    make(schema, birth_year=2000, birth_month=2, birth_day=29)
    make(schema, birth_month=2, birth_day=29)  # no year: cannot tell, accept


@pytest.mark.parametrize("schema", SCHEMAS)
def test_leap_flag_needs_a_lunar_month(schema):
    with pytest.raises(ValidationError):
        make(schema, death_leap_month=True)  # no month
    with pytest.raises(ValidationError):
        make(schema, birth_month=3, birth_leap_month=True)  # birth is solar by default
    member = make(schema, birth_month=3, birth_is_lunar=True, birth_leap_month=True, death_month=4, death_leap_month=True)
    assert member.birth_leap_month and member.death_leap_month


@pytest.mark.parametrize("schema", SCHEMAS)
def test_birth_order_is_positive(schema):
    with pytest.raises(ValidationError):
        make(schema, birth_order=0)
    assert make(schema, birth_order=3).birth_order == 3


@pytest.mark.parametrize("schema", SCHEMAS)
def test_contact_fields_are_cleaned_and_validated(schema):
    member = make(schema, hometown="  Hà Tĩnh ", phone=" +84 (912) 345-678 ", email=" a@example.com ")
    assert (member.hometown, member.phone, member.email) == ("Hà Tĩnh", "+84 (912) 345-678", "a@example.com")
    blank = make(schema, hometown="  ", phone="", email=" ")
    assert (blank.hometown, blank.phone, blank.email) == (None, None, None)
    for bad in ("12abc", "call me", "0912;345"):
        with pytest.raises(ValidationError):
            make(schema, phone=bad)
    with pytest.raises(ValidationError):
        make(schema, email="not-an-email")


@pytest.mark.parametrize("schema", SCHEMAS)
def test_death_cannot_precede_birth_even_with_months(schema):
    with pytest.raises(ValidationError):
        make(schema, birth_year=1950, death_year=1949)
    # same year: month order is checked only when both are solar-comparable (both lunar or both solar)
    with pytest.raises(ValidationError):
        make(schema, birth_year=1950, birth_month=6, birth_is_lunar=True, death_year=1950, death_month=3, death_is_lunar=True)
    make(schema, birth_year=1950, birth_month=6, death_year=1950, death_month=3, death_is_lunar=True)  # mixed calendars: not comparable
