import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session():
    from app.db.base import Base
    from app.models.marriage import Marriage  # noqa: F401
    from app.models.member import Member  # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_create_marriage(session):
    from app.models.marriage import Marriage
    from app.models.member import Member

    husband = Member(full_name="Husband")
    wife = Member(full_name="Wife")
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


async def test_create_marriage_without_year_defaults_to_none(session):
    from app.models.marriage import Marriage
    from app.models.member import Member

    husband = Member(full_name="Husband")
    wife = Member(full_name="Wife")
    session.add_all([husband, wife])
    await session.commit()
    await session.refresh(husband)
    await session.refresh(wife)

    marriage = Marriage(member_id=husband.id, spouse_id=wife.id)
    session.add(marriage)
    await session.commit()
    await session.refresh(marriage)

    assert marriage.marriage_year is None
