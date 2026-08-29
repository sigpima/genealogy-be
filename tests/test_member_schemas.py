from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def test_member_create_accepts_valid_data():
    from app.schemas.member import MemberCreate

    data = MemberCreate(full_name="A B", parent_id=None)
    assert data.full_name == "A B"
    assert data.parent_id is None


def test_member_create_rejects_empty_name():
    from app.schemas.member import MemberCreate

    with pytest.raises(ValidationError):
        MemberCreate(full_name="", parent_id=None)


def test_member_read_from_attributes():
    from app.schemas.member import MemberRead

    class FakeMember:
        id = 1
        full_name = "A B"
        parent_id = None
        birth_year = None
        death_year = None
        gender = None
        notes = None
        created_at = datetime.now(timezone.utc)

    read = MemberRead.model_validate(FakeMember())
    assert read.id == 1
    assert read.full_name == "A B"


def test_member_tree_node_nests_children():
    from app.schemas.member import MemberTreeNode

    node = MemberTreeNode(
        id=1,
        name="Root",
        children=[MemberTreeNode(id=2, name="Child", children=[])],
    )
    assert node.children[0].name == "Child"


def test_member_create_accepts_all_detail_fields():
    from app.schemas.member import Gender, MemberCreate

    data = MemberCreate(
        full_name="A B",
        parent_id=None,
        birth_year=1950,
        death_year=2010,
        gender=Gender.male,
        notes="hello",
    )
    assert data.birth_year == 1950
    assert data.gender == Gender.male


def test_member_create_rejects_death_before_birth():
    from app.schemas.member import MemberCreate

    with pytest.raises(ValidationError):
        MemberCreate(full_name="A B", birth_year=2010, death_year=1950)


def test_member_create_rejects_invalid_gender():
    from app.schemas.member import MemberCreate

    with pytest.raises(ValidationError):
        MemberCreate(full_name="A B", gender="unknown")


def test_member_update_rejects_death_before_birth():
    from app.schemas.member import MemberUpdate

    with pytest.raises(ValidationError):
        MemberUpdate(full_name="A B", birth_year=2010, death_year=1950)


def test_member_tree_node_accepts_detail_fields():
    from app.schemas.member import Gender, MemberTreeNode

    node = MemberTreeNode(
        id=1, name="Root", birth_year=1900, death_year=1980, gender=Gender.female, notes="n"
    )
    assert node.gender == Gender.female
    assert node.children == []
