import pytest
from pydantic import ValidationError

from app.schemas.member import MarriageCreate, MarriageUpdate, SpouseInfo


def test_marriage_create_defaults():
    payload = MarriageCreate(spouse_full_name="Wife")
    assert payload.marriage_year is None
    assert payload.spouse_gender is None
    assert payload.spouse_birth_year is None


def test_marriage_create_rejects_death_before_birth():
    with pytest.raises(ValidationError):
        MarriageCreate(spouse_full_name="Wife", spouse_birth_year=2000, spouse_death_year=1990)


def test_marriage_create_rejects_blank_name():
    with pytest.raises(ValidationError):
        MarriageCreate(spouse_full_name="")


def test_marriage_update_rejects_death_before_birth():
    with pytest.raises(ValidationError):
        MarriageUpdate(spouse_full_name="Wife", spouse_birth_year=2000, spouse_death_year=1990)


def test_spouse_info_roundtrip():
    info = SpouseInfo(
        marriage_id=1,
        marriage_year=1975,
        id=2,
        full_name="Wife",
        birth_year=1950,
        death_year=None,
        gender="female",
        notes=None,
    )
    assert info.full_name == "Wife"
    assert info.gender == "female"
