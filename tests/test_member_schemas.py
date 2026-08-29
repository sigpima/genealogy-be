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
