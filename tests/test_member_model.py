from sqlalchemy import select


async def test_create_root_member(session, tree):
    from app.models.member import Member

    root = Member(tree_id=tree.id, full_name="Root")
    session.add(root)
    await session.commit()
    await session.refresh(root)

    assert root.id is not None
    assert root.parent_id is None
    assert root.created_at is not None


async def test_create_child_member(session, tree):
    from app.models.member import Member

    root = Member(tree_id=tree.id, full_name="Root")
    session.add(root)
    await session.commit()
    await session.refresh(root)

    child = Member(tree_id=tree.id, full_name="Child", parent_id=root.id)
    session.add(child)
    await session.commit()

    result = await session.execute(select(Member).where(Member.full_name == "Child"))
    fetched = result.scalar_one()
    assert fetched.parent_id == root.id


async def test_create_member_with_details(session, tree):
    from app.models.member import Member

    member = Member(tree_id=tree.id, 
        full_name="Detailed",
        birth_year=1950,
        death_year=2010,
        gender="male",
        notes="Some notes",
    )
    session.add(member)
    await session.commit()
    await session.refresh(member)

    assert member.birth_year == 1950
    assert member.death_year == 2010
    assert member.gender == "male"
    assert member.notes == "Some notes"


async def test_create_member_without_details_defaults_to_none(session, tree):
    from app.models.member import Member

    member = Member(tree_id=tree.id, full_name="Minimal")
    session.add(member)
    await session.commit()
    await session.refresh(member)

    assert member.birth_year is None
    assert member.death_year is None
    assert member.gender is None
    assert member.notes is None


async def test_create_member_without_avatar_defaults_to_none(session, tree):
    from app.models.member import Member

    member = Member(tree_id=tree.id, full_name="No Avatar")
    session.add(member)
    await session.commit()
    await session.refresh(member)

    assert member.avatar_url is None
