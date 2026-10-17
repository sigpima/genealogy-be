from sqlalchemy import select


async def test_create_marriage(session, tree):
    from app.models.marriage import Marriage
    from app.models.member import Member

    husband = Member(tree_id=tree.id, full_name="Husband")
    wife = Member(tree_id=tree.id, full_name="Wife")
    session.add_all([husband, wife])
    await session.commit()
    await session.refresh(husband)
    await session.refresh(wife)

    marriage = Marriage(member_id=husband.id, spouse_id=wife.id, marriage_year=1975)
    session.add(marriage)
    await session.commit()

    result = await session.execute(select(Marriage).where(Marriage.member_id == husband.id))
    fetched = result.scalar_one()
    assert fetched.spouse_id == wife.id
    assert fetched.marriage_year == 1975
    assert fetched.created_at is not None


async def test_create_marriage_without_year_defaults_to_none(session, tree):
    from app.models.marriage import Marriage
    from app.models.member import Member

    husband = Member(tree_id=tree.id, full_name="Husband")
    wife = Member(tree_id=tree.id, full_name="Wife")
    session.add_all([husband, wife])
    await session.commit()
    await session.refresh(husband)
    await session.refresh(wife)

    marriage = Marriage(member_id=husband.id, spouse_id=wife.id)
    session.add(marriage)
    await session.commit()
    await session.refresh(marriage)

    assert marriage.marriage_year is None
